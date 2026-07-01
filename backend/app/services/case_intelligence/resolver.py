import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import numpy as np
from sqlalchemy.orm import Session

from app.models import LegalEntity, EntityRelationship
from app.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

class EntityResolver:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()

    def resolve_cross_document_entities(self, case_id: uuid.UUID) -> None:
        """
        Deduplicates and groups case entities using a hybrid similarity formula:
        Similarity = 0.6 * Embedding Cosine Similarity + 0.4 * String Name Match
        Updates canonical reference targets, resolution_status, and merge history logs.
        """
        entities = (
            self.db.query(LegalEntity)
            .filter(LegalEntity.case_id == case_id)
            .all()
        )
        
        if not entities:
            return

        # 1. Reset all to unresolved/canonical default state to prevent stale graph links
        for ent in entities:
            ent.canonical_id = None
            ent.resolution_status = "unresolved"
            ent.similarity_score = None
            ent.merge_metadata = None
        self.db.commit()

        # Compute embeddings for all entity names in batch for efficiency
        names = [ent.name for ent in entities]
        try:
            embeddings = self.embedding_service.embed_batch(names)
        except Exception as e:
            logger.warning("Failed to generate embeddings for entity resolution: %s. Using mock zero vectors.", str(e))
            embeddings = [[0.0] * 384 for _ in range(len(names))]

        # Map entity ID to its embedding
        embedding_map = {entities[i].id: embeddings[i] for i in range(len(entities))}

        resolved_canonical_groups: List[LegalEntity] = []

        for i, ent in enumerate(entities):
            # Normalize name for string comparison rules
            clean_name = self._normalize_name(ent.name)
            
            best_match: Optional[LegalEntity] = None
            best_score = 0.0

            for canonical in resolved_canonical_groups:
                # Type matches must match to merge (e.g. don't merge a court with a judge)
                if ent.entity_type != canonical.entity_type:
                    continue

                # 1. Calculate rule-based string similarity (intersection of tokens)
                clean_canonical_name = self._normalize_name(canonical.name)
                string_similarity = self._jaccard_similarity(clean_name, clean_canonical_name)

                # 2. Calculate embedding similarity
                v1 = np.array(embedding_map[ent.id])
                v2 = np.array(embedding_map[canonical.id])
                
                norm1 = np.linalg.norm(v1)
                norm2 = np.linalg.norm(v2)
                if norm1 > 0 and norm2 > 0:
                    embedding_similarity = float(np.dot(v1, v2) / (norm1 * norm2))
                else:
                    embedding_similarity = 1.0 if clean_name == clean_canonical_name else 0.0

                # Hybrid scoring formula
                hybrid_score = (0.6 * embedding_similarity) + (0.4 * string_similarity)

                if hybrid_score > best_score:
                    best_score = hybrid_score
                    best_match = canonical

            # Merging Threshold (e.g., 0.78 similarity)
            if best_match and best_score >= 0.78:
                # Merge current entity into best canonical match
                ent.canonical_id = best_match.id
                ent.resolution_status = "merged"
                ent.similarity_score = round(best_score, 3)
                
                # Merge aliases
                canonical_aliases = best_match.aliases.split(",") if best_match.aliases else []
                if ent.name not in canonical_aliases and ent.name != best_match.name:
                    canonical_aliases.append(ent.name)
                    best_match.aliases = ",".join(canonical_aliases)

                # Append merge transaction history details to canonical metadata
                history = []
                if best_match.merge_metadata:
                    try:
                        history = json.loads(best_match.merge_metadata)
                    except Exception:
                        pass
                
                history.append({
                    "merged_entity_id": str(ent.id),
                    "original_name": ent.name,
                    "similarity_score": round(best_score, 3),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "document_id": str(ent.document_id) if ent.document_id else None
                })
                best_match.merge_metadata = json.dumps(history)
                best_match.resolution_status = "canonical"
            else:
                # Make current entity the new canonical record for this cluster
                ent.resolution_status = "canonical"
                resolved_canonical_groups.append(ent)

        self.db.commit()

        # Update all Knowledge Graph relationships pointing to merged nodes to point to canonical nodes instead!
        self._update_relationship_references()

    def _normalize_name(self, name: str) -> str:
        """Removes common prefix titles, commas, and dots to return clean lowercased tokens."""
        clean = name.lower()
        for prefix in ["hon'ble", "justice", "judge", "advocate", "counsel", "witness", "dr.", "mr.", "mrs."]:
            clean = clean.replace(prefix, "")
        clean = clean.replace(".", " ").replace(",", " ")
        return " ".join(clean.split())

    def _jaccard_similarity(self, s1: str, s2: str) -> float:
        """Calculates Jaccard token overlap similarity."""
        w1 = set(s1.split())
        w2 = set(s2.split())
        if not w1 or not w2:
            return 0.0
        intersection = w1.intersection(w2)
        union = w1.union(w2)
        return float(len(intersection) / len(union))

    def _update_relationship_references(self) -> None:
        """Finds all merged entities and updates relationship targets/sources to canonical equivalents."""
        merged_entities = (
            self.db.query(LegalEntity)
            .filter(LegalEntity.resolution_status == "merged")
            .all()
        )
        
        entity_map = {ent.id: ent.canonical_id for ent in merged_entities if ent.canonical_id}
        if not entity_map:
            return

        relationships = self.db.query(EntityRelationship).all()
        for rel in relationships:
            if rel.source_id in entity_map:
                rel.source_id = entity_map[rel.source_id]
            if rel.target_id in entity_map:
                rel.target_id = entity_map[rel.target_id]
        
        self.db.commit()
