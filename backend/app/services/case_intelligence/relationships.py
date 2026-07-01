import uuid
import json
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models import (
    EntityRelationship,
    LegalEntity,
    ClaimDefense,
    LegalEvidence,
    LegalFact,
    ActStatute
)
from app.services.case_intelligence.confidence import ConfidenceScoringService

logger = logging.getLogger(__name__)

class RelationshipInferenceService:
    def __init__(self, db: Session):
        self.db = db

    def infer_case_relationships(self, case_id: uuid.UUID) -> int:
        """
        Deduces relational graph edges connecting legal entities, facts, claims, evidence, and statutes.
        Saves connections along with confidence score breakdowns and reasoning context.
        """
        # Fetch case node records
        entities = self.db.query(LegalEntity).filter(LegalEntity.case_id == case_id).all()
        claims = self.db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id).all()
        evidence = self.db.query(LegalEvidence).filter(LegalEvidence.case_id == case_id).all()
        facts = self.db.query(LegalFact).filter(LegalFact.case_id == case_id).all()
        acts = self.db.query(ActStatute).filter(ActStatute.case_id == case_id).all()

        # Clear existing relations to prevent duplications on rerun
        self.db.query(EntityRelationship).filter(EntityRelationship.case_id == case_id).delete()
        self.db.commit()

        count = 0

        # 1. REPRESENTS: Advocates represent parties
        parties = [e for e in entities if e.entity_type == "party"]
        advocates = [e for e in entities if e.entity_type == "advocate" or "counsel" in (e.role or "").lower()]
        for p in parties:
            for adv in advocates:
                rel = self._create_relationship(
                    case_id=case_id,
                    source_id=adv.id,
                    source_type="entity",
                    target_id=p.id,
                    target_type="entity",
                    rel_type="REPRESENTS",
                    conf=0.90,
                    reasoning=f"Advocate {adv.name} represents party {p.name} in case litigation.",
                    doc_id=adv.document_id
                )
                self.db.add(rel)
                count += 1

        # 2. HEARD_BY: Judges presiding over courts
        judges = [e for e in entities if e.entity_type == "judge"]
        courts = [e for e in entities if e.entity_type == "court"]
        for j in judges:
            for c in courts:
                rel = self._create_relationship(
                    case_id=case_id,
                    source_id=j.id,
                    source_type="entity",
                    target_id=c.id,
                    target_type="entity",
                    rel_type="HEARD_BY",
                    conf=0.95,
                    reasoning=f"Judge {j.name} hears arguments presiding over bench at {c.name}.",
                    doc_id=j.document_id
                )
                self.db.add(rel)
                count += 1

        # 3. SUPPORTS or REFUTES: Evidence linking to claims
        for ev in evidence:
            for cl in claims:
                text_ev = ev.description.lower()
                
                # Check for refuting markers
                if any(x in text_ev for x in ["refutes", "contradicts", "disputes", "denies"]):
                    rel_type = "REFUTES"
                    conf = 0.80
                else:
                    rel_type = "SUPPORTS"
                    conf = 0.85

                rel = self._create_relationship(
                    case_id=case_id,
                    source_id=ev.id,
                    source_type="evidence",
                    target_id=cl.id,
                    target_type="claim",
                    rel_type=rel_type,
                    conf=conf,
                    reasoning=f"Evidence item description connects to claim statement with relation '{rel_type}'.",
                    doc_id=ev.document_id
                )
                self.db.add(rel)
                count += 1

        # 4. RELIES_ON: Claims relying on statutes
        for cl in claims:
            for act in acts:
                rel = self._create_relationship(
                    case_id=case_id,
                    source_id=cl.id,
                    source_type="claim",
                    target_id=act.id,
                    target_type="act",
                    rel_type="RELIES_ON",
                    conf=0.88,
                    reasoning=f"Claim arguments rely on section reference {act.section_reference} of {act.act_name}.",
                    doc_id=cl.document_id
                )
                self.db.add(rel)
                count += 1

        # 5. REFERENCES: Facts mapping to statutes
        for f in facts:
            for act in acts:
                rel = self._create_relationship(
                    case_id=case_id,
                    source_id=f.id,
                    source_type="fact",
                    target_id=act.id,
                    target_type="act",
                    rel_type="REFERENCES",
                    conf=0.85,
                    reasoning=f"Factual finding references statutory provisions of {act.act_name}.",
                    doc_id=f.document_id
                )
                self.db.add(rel)
                count += 1

        self.db.commit()
        return count

    def _create_relationship(
        self,
        case_id: uuid.UUID,
        source_id: uuid.UUID,
        source_type: str,
        target_id: uuid.UUID,
        target_type: str,
        rel_type: str,
        conf: float,
        reasoning: str,
        doc_id: Optional[uuid.UUID] = None
    ) -> EntityRelationship:
        score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=conf)
        return EntityRelationship(
            case_id=case_id,
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type,
            relationship_type=rel_type,
            confidence_score=score_res["final_score"],
            confidence_breakdown=json.dumps(score_res["breakdown"]),
            reasoning_metadata=json.dumps({"reasoning": reasoning}),
            source_doc_id=doc_id
        )
