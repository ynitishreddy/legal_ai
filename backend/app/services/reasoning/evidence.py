import logging
import uuid
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.services.case_intelligence.graph_query import KnowledgeGraphQueryService

logger = logging.getLogger(__name__)


class EvidenceRankingEngine:
    """
    Ranks evidence items based on semantic score, citation frequency,
    knowledge graph centrality, timeline importance, and source confidence.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph_service = KnowledgeGraphQueryService(db)

    def rank_evidence(
        self,
        case_id: uuid.UUID,
        query: str,
        retrieved_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Combines retrieved semantic chunks, timeline events, and KG entities,
        scores them with custom weighting formulas, and returns ranked explainable evidence list.
        """
        raw_chunks = retrieved_data.get("semantic_chunks", [])
        events = retrieved_data.get("timeline_events", [])
        entities = retrieved_data.get("entities", [])

        # Calculate KG centrality map
        centrality_map = {}
        if case_id:
            try:
                metrics = self.graph_service.get_centrality_metrics(case_id)
                for item in metrics:
                    centrality_map[item["label"].lower()] = item["degree_centrality"]
            except Exception as e:
                logger.debug("Failed to calculate centrality metrics for case %s: %s", case_id, e)

        ranked_items = []

        # 1. Process Semantic Chunks
        for idx, chunk in enumerate(raw_chunks):
            # Base score from retriever (cosine similarity or similar)
            semantic_score = chunk.get("score", chunk.get("similarity_score", 0.70))
            confidence = chunk.get("confidence", 0.85)

            # Boost if chunk contains central entities
            centrality_boost = 0.0
            chunk_text_lower = chunk.get("chunk_text", "").lower()
            for ent_name, degree in centrality_map.items():
                if ent_name in chunk_text_lower:
                    centrality_boost = min(0.15, degree * 0.02)
                    break

            # Boost based on citation/frequency (e.g. index position in retrieval, first is higher)
            frequency_score = max(0.0, 0.10 - (idx * 0.02))

            final_score = min(1.0, semantic_score + centrality_boost + frequency_score)

            # Build explainable tag
            explanation = f"High semantic relevance ({semantic_score:.2f})"
            if centrality_boost > 0:
                explanation += f" and mentions central entity with degree centrality boost (+{centrality_boost:.2f})"
            if frequency_score > 0:
                explanation += f". Ranked early in vector search retrieval."

            ranked_items.append({
                "id": str(chunk.get("chunk_id", uuid.uuid4())),
                "type": "chunk",
                "description": chunk.get("chunk_text", "")[:250] + "...",
                "source": f"Doc: {chunk.get('document_title', 'Unknown')} - Page {chunk.get('page_start', 1)}",
                "score": round(final_score, 3),
                "explanation": explanation
            })

        # 2. Process Timeline Events
        for evt in events:
            # Base score based on event confidence
            evt_conf = evt.get("confidence", 0.80)
            
            # Boost if matched in query
            query_boost = 0.15 if any(w in evt.get("description", "").lower() for w in query.lower().split()) else 0.0
            
            final_score = min(1.0, evt_conf * 0.7 + query_boost)
            
            explanation = f"Timeline Event with extraction confidence ({evt_conf:.2f})"
            if query_boost > 0:
                explanation += f" and direct query keyword matching boost (+{query_boost:.2f})"

            ranked_items.append({
                "id": evt.get("id"),
                "type": "event",
                "description": f"[{evt.get('date')}] {evt.get('title')}: {evt.get('description')}",
                "source": "Timeline Chronology",
                "score": round(final_score, 3),
                "explanation": explanation
            })

        # Sort by score descending
        ranked_items.sort(key=lambda x: x["score"], reverse=True)
        return ranked_items


class CitationRankingEngine:
    """
    Ranks and refines citations by supporting strength, relevance, and redundancy reduction.
    """

    def rank_citations(self, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Deduplicates close citations, orders them by relevance score,
        and assigns citation strength category flags.
        """
        seen_texts = set()
        unique_citations = []

        # Sort by base relevance score descending
        sorted_citations = sorted(citations, key=lambda x: x.get("score", x.get("relevance_score", 0.50)), reverse=True)

        for cit in sorted_citations:
            text_snippet = cit.get("text", "").strip()[:50].lower()
            if text_snippet in seen_texts:
                continue
            seen_texts.add(text_snippet)

            # Assign supporting strength
            score = cit.get("score", cit.get("relevance_score", 0.50))
            if score >= 0.80:
                strength = "Primary"
            elif score >= 0.60:
                strength = "Supporting"
            else:
                strength = "Contextual"

            unique_citations.append({
                "id": cit.get("id", str(uuid.uuid4())),
                "text": cit.get("text", ""),
                "source_doc": cit.get("source_doc", "Case Document"),
                "relevance_score": round(score, 3),
                "strength": strength
            })

        return unique_citations
