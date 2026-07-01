import uuid
import logging
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.models import (
    LegalFact,
    LegalEntity,
    LegalIssue,
    ClaimDefense,
    LegalEvidence,
    ActStatute,
    EntityRelationship,
    Document
)
from app.document_processing.models import DocumentChunk
from app.services.case_intelligence.extractors import (
    PartyExtractor,
    JudgeExtractor,
    CourtExtractor,
    IssueExtractor,
    ClaimExtractor,
    DefenseExtractor,
    EvidenceExtractor,
    WitnessExtractor,
    StatuteExtractor
)
from app.services.case_intelligence.confidence import ConfidenceScoringService
from app.services.case_intelligence.resolver import EntityResolver
from app.services.case_intelligence.arguments import ArgumentExtractor
from app.services.case_intelligence.statutes import StatuteNormalizer
from app.services.case_intelligence.issues import IssueClassifier
from app.services.case_intelligence.relationships import RelationshipInferenceService

logger = logging.getLogger(__name__)

class CaseIntelligenceService:
    """
    Main orchestration service layer responsible for executing AI-based
    Case Intelligence extraction, entity resolution, and Knowledge Graph structuring.
    Supports incremental document-level updates and hybrid scoring.
    """
    def __init__(self, db: Session) -> None:
        self.db = db
        # Register base extractors
        self.extractors = {
            "parties": PartyExtractor(),
            "judges": JudgeExtractor(),
            "courts": CourtExtractor(),
            "issues": IssueExtractor(),
            "claims": ClaimExtractor(),
            "defenses": DefenseExtractor(),
            "evidence": EvidenceExtractor(),
            "witnesses": WitnessExtractor(),
            "statutes": StatuteExtractor()
        }
        # Enterprise extensions
        self.resolver = EntityResolver(db)
        self.argument_extractor = ArgumentExtractor()
        self.statute_normalizer = StatuteNormalizer()
        self.issue_classifier = IssueClassifier()
        self.relation_service = RelationshipInferenceService(db)

    def extract_case_knowledge(self, case_id: uuid.UUID, document_id: uuid.UUID) -> Dict[str, Any]:
        """
        Extracts legal facts, entities, claims, evidence, and statutes for a single document.
        Executes resolution and graph linking across all document filings incrementally.
        """
        # Fetch chunks
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .all()
        )
        if not chunks:
            logger.warning("CaseIntelligenceService: No chunks found for document %s", document_id)
            return {"facts": 0, "entities": 0, "issues": 0, "claims": 0, "evidence": 0, "statutes": 0}

        counts = {"facts": 0, "entities": 0, "issues": 0, "claims": 0, "evidence": 0, "statutes": 0}

        # Clear previous intelligence items for this document to enable clean incremental updates
        self._clear_document_knowledge(document_id)

        # Process chunks
        for chunk in chunks:
            text = chunk.chunk_text
            metadata = {"page": chunk.page_start}

            # 1. Fact Extraction (Facts, score confidence, categories, citations)
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for sentence in sentences:
                clean_sentence = sentence.strip()
                if any(x in clean_sentence.lower() for x in ["breached", "signed", "alleged", "occurred on", "filed a", "was arrested"]):
                    category = "Procedural Facts" if any(x in clean_sentence.lower() for x in ["filed a", "suit", "appeal"]) else "Factual Findings"
                    
                    score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=0.85)

                    fact = LegalFact(
                        case_id=case_id,
                        document_id=document_id,
                        chunk_id=str(chunk.id),
                        fact_text=clean_sentence,
                        confidence_score=score_res["final_score"],
                        confidence_breakdown=json.dumps(score_res["breakdown"]),
                        citation_source=f"Page {chunk.page_start}",
                        supporting_citations=f"Chunk {chunk.chunk_index}",
                        extraction_method="hybrid",
                        category=category,
                        importance_score=0.80 if category == "Factual Findings" else 0.50,
                        processing_version="1.5.1"
                    )
                    self.db.add(fact)
                    counts["facts"] += 1

            # 2. Entity Extraction
            # Parties
            parties = self.extractors["parties"].extract(text, metadata)
            for p in parties:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=p["confidence_score"])
                ent = LegalEntity(
                    case_id=case_id,
                    document_id=document_id,
                    entity_type="party",
                    name=p["name"],
                    normalized_name=p["normalized_name"],
                    role=p["role"],
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"]),
                    resolution_status="unresolved"
                )
                self.db.add(ent)
                counts["entities"] += 1

            # Judges
            judges = self.extractors["judges"].extract(text, metadata)
            for j in judges:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=j["confidence_score"])
                ent = LegalEntity(
                    case_id=case_id,
                    document_id=document_id,
                    entity_type="judge",
                    name=j["name"],
                    normalized_name=j["normalized_name"],
                    role="judge",
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"]),
                    resolution_status="unresolved"
                )
                self.db.add(ent)
                counts["entities"] += 1

            # Courts
            courts = self.extractors["courts"].extract(text, metadata)
            for c in courts:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=c["confidence_score"])
                ent = LegalEntity(
                    case_id=case_id,
                    document_id=document_id,
                    entity_type="court",
                    name=c["name"],
                    normalized_name=c["normalized_name"],
                    role="court",
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"]),
                    resolution_status="unresolved"
                )
                self.db.add(ent)
                counts["entities"] += 1

            # Witnesses
            witnesses = self.extractors["witnesses"].extract(text, metadata)
            for w in witnesses:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=w["confidence_score"])
                ent = LegalEntity(
                    case_id=case_id,
                    document_id=document_id,
                    entity_type="witness",
                    name=w["name"],
                    normalized_name=w["normalized_name"],
                    role="witness",
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"]),
                    resolution_status="unresolved"
                )
                self.db.add(ent)
                counts["entities"] += 1

            # 3. Issues classification (multi-label)
            issues = self.extractors["issues"].extract(text, metadata)
            for i in issues:
                classification = self.issue_classifier.classify(i["issue_text"])
                issue = LegalIssue(
                    case_id=case_id,
                    document_id=document_id,
                    issue_text=i["issue_text"],
                    issue_category=classification["primary_category"],
                    labels=",".join(classification["labels"]),
                    confidence_score=classification["confidence_score"],
                    confidence_breakdown=json.dumps(classification["confidence_breakdown"])
                )
                self.db.add(issue)
                counts["issues"] += 1

            # 4. Claims, Defenses & Arguments Extraction
            claims = self.extractors["claims"].extract(text, metadata)
            for cl in claims:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=cl["confidence_score"])
                cd = ClaimDefense(
                    case_id=case_id,
                    document_id=document_id,
                    type="claim_primary",
                    statement=cl["statement"],
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"])
                )
                self.db.add(cd)
                counts["claims"] += 1

            defenses = self.extractors["defenses"].extract(text, metadata)
            for df in defenses:
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=df["confidence_score"])
                cd = ClaimDefense(
                    case_id=case_id,
                    document_id=document_id,
                    type="defense",
                    statement=df["statement"],
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"])
                )
                self.db.add(cd)
                counts["claims"] += 1

            # Arguments Extractor runs
            args = self.argument_extractor.extract(text, metadata)
            for arg in args:
                cd = ClaimDefense(
                    case_id=case_id,
                    document_id=document_id,
                    type=arg["type"],
                    statement=arg["statement"],
                    confidence_score=arg["confidence_score"],
                    confidence_breakdown=json.dumps(arg["confidence_breakdown"])
                )
                self.db.add(cd)
                counts["claims"] += 1

            # 5. Evidence strength tracking
            evidence = self.extractors["evidence"].extract(text, metadata)
            for ev in evidence:
                # Basic heuristic rules to calculate evidence strength score
                text_lower = ev["description"].lower()
                strength = 0.50
                if any(x in text_lower for x in ["confession", "signed contract", "dna", "forensic"]):
                    strength = 0.90
                elif any(x in text_lower for x in ["hearsay", "unverified", "rumor"]):
                    strength = 0.25
                
                score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=ev["confidence_score"], evidence_strength=strength)

                evidence_obj = LegalEvidence(
                    case_id=case_id,
                    document_id=document_id,
                    evidence_type=ev["evidence_type"],
                    description=ev["description"],
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"]),
                    strength_score=strength
                )
                self.db.add(evidence_obj)
                counts["evidence"] += 1

            # 6. Statute normalization & categorization
            statutes = self.extractors["statutes"].extract(text, metadata)
            for st in statutes:
                normalized = self.statute_normalizer.normalize(st["act_name"], st["section_reference"])
                score_res = ConfidenceScoringService.calculate_score(
                    base_extractor_conf=st["confidence_score"],
                    normalization_conf=0.95
                )
                
                stat = ActStatute(
                    case_id=case_id,
                    document_id=document_id,
                    act_name=normalized["canonical_act"],
                    section_reference=normalized["section_number"],
                    normalized_reference=normalized["normalized_reference"],
                    aliases=normalized["aliases"],
                    confidence_score=score_res["final_score"],
                    confidence_breakdown=json.dumps(score_res["breakdown"])
                )
                self.db.add(stat)
                counts["statutes"] += 1

        self.db.commit()

        # 7. Cross-Document Entity resolution
        self.resolve_cross_document_entities(case_id)

        # 8. Relational inferences
        self.build_knowledge_graph(case_id)

        return counts

    def _clear_document_knowledge(self, document_id: uuid.UUID) -> None:
        """Cleans all case intelligence details linked to a document."""
        self.db.query(LegalFact).filter(LegalFact.document_id == document_id).delete()
        self.db.query(LegalEntity).filter(LegalEntity.document_id == document_id).delete()
        self.db.query(LegalIssue).filter(LegalIssue.document_id == document_id).delete()
        self.db.query(ClaimDefense).filter(ClaimDefense.document_id == document_id).delete()
        self.db.query(LegalEvidence).filter(LegalEvidence.document_id == document_id).delete()
        self.db.query(ActStatute).filter(ActStatute.document_id == document_id).delete()
        self.db.commit()

    def resolve_cross_document_entities(self, case_id: uuid.UUID) -> None:
        """Calls the dedicated EntityResolver instance."""
        self.resolver.resolve_cross_document_entities(case_id)

    def build_knowledge_graph(self, case_id: uuid.UUID) -> None:
        """Calls the dedicated RelationshipInferenceService instance."""
        self.relation_service.infer_case_relationships(case_id)

    def get_knowledge_graph_data(self, case_id: uuid.UUID) -> Dict[str, Any]:
        """
        Formats database entities and relationships into standard node-link JSON structure,
        excluding merged entities to keep the graph display clean.
        """
        entities = self.db.query(LegalEntity).filter(
            and_(LegalEntity.case_id == case_id, LegalEntity.resolution_status != "merged")
        ).all()
        claims = self.db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id).all()
        evidence = self.db.query(LegalEvidence).filter(LegalEvidence.case_id == case_id).all()
        acts = self.db.query(ActStatute).filter(ActStatute.case_id == case_id).all()
        relationships = self.db.query(EntityRelationship).filter(EntityRelationship.case_id == case_id).all()

        nodes = []
        # Build Nodes
        for e in entities:
            nodes.append({
                "id": str(e.id),
                "type": e.entity_type,
                "label": e.name,
                "details": {
                    "role": e.role,
                    "aliases": e.aliases.split(",") if e.aliases else [],
                    "merge_history": json.loads(e.merge_metadata) if e.merge_metadata else [],
                    "confidence_breakdown": json.loads(e.confidence_breakdown) if e.confidence_breakdown else {}
                }
            })
        for cl in claims:
            nodes.append({
                "id": str(cl.id),
                "type": cl.type,
                "label": cl.statement[:40] + "...",
                "details": {
                    "full_statement": cl.statement,
                    "confidence_breakdown": json.loads(cl.confidence_breakdown) if cl.confidence_breakdown else {}
                }
            })
        for ev in evidence:
            nodes.append({
                "id": str(ev.id),
                "type": "evidence",
                "label": ev.description[:40] + "...",
                "details": {
                    "evidence_type": ev.evidence_type,
                    "strength_score": ev.strength_score,
                    "confidence_breakdown": json.loads(ev.confidence_breakdown) if ev.confidence_breakdown else {}
                }
            })
        for act in acts:
            nodes.append({
                "id": str(act.id),
                "type": "statute",
                "label": act.normalized_reference,
                "details": {
                    "act_name": act.act_name, 
                    "section": act.section_reference,
                    "aliases": act.aliases,
                    "confidence_breakdown": json.loads(act.confidence_breakdown) if act.confidence_breakdown else {}
                }
            })

        edges = []
        # Build Edges
        for r in relationships:
            edges.append({
                "id": str(r.id),
                "source": str(r.source_id),
                "target": str(r.target_id),
                "type": r.relationship_type,
                "confidence": r.confidence_score,
                "details": {
                    "reasoning": json.loads(r.reasoning_metadata).get("reasoning", "") if r.reasoning_metadata else "",
                    "source_doc_id": str(r.source_doc_id) if r.source_doc_id else None
                }
            })

        return {"nodes": nodes, "links": edges}

    def get_intelligence_statistics(self, case_id: uuid.UUID) -> Dict[str, Any]:
        """Gathers intelligence metrics breakdown for case statistics."""
        facts_count = self.db.query(LegalFact).filter(LegalFact.case_id == case_id).count()
        entities_count = self.db.query(LegalEntity).filter(and_(LegalEntity.case_id == case_id, LegalEntity.resolution_status != "merged")).count()
        issues_count = self.db.query(LegalIssue).filter(LegalIssue.case_id == case_id).count()
        claims_count = self.db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id).count()
        evidence_count = self.db.query(LegalEvidence).filter(LegalEvidence.case_id == case_id).count()
        statutes_count = self.db.query(ActStatute).filter(ActStatute.case_id == case_id).count()

        return {
            "facts_count": facts_count,
            "entities_count": entities_count,
            "issues_count": issues_count,
            "claims_count": claims_count,
            "evidence_count": evidence_count,
            "statutes_count": statutes_count
        }
