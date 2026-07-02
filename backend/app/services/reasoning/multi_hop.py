import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models import TimelineEvent, LegalEvidence, LegalEntity, SummaryCache
from app.services.retriever import RetrieverService
from app.services.case_intelligence.graph_query import KnowledgeGraphQueryService

logger = logging.getLogger(__name__)


class MultiHopRetrievalOrchestrator:
    """
    Executes multi-step / iterative retrieval across semantic embeddings,
    knowledge graph nodes, timeline events, and document summaries.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.retriever_service = RetrieverService(db)
        self.graph_service = KnowledgeGraphQueryService(db)

    async def execute_multi_hop(
        self,
        case_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        hops: int = 2,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Orchestrates iterative retrieval:
        Hop 1: Retrieve semantic chunks based on query.
        Extract entities/concepts from Hop 1 chunks.
        Hop 2: Use entities to pull related timeline events, KG neighbors, and evidence items.
        Merge and return unified context structure.
        """
        logger.info("Starting multi-hop retrieval for case %s, query: %s", case_id, query)

        # Hop 1: Semantic chunk retrieval
        retrieved_chunks = self.retriever_service.retrieve_semantic(
            user_id=user_id,
            query_text=query,
            filters={"case_id": case_id} if case_id else {},
            top_k=top_k,
            score_threshold=threshold,
        )

        if not retrieved_chunks:
            logger.warning("Hop 1 returned empty results. Falling back to case database metadata.")

        # Extract potential entities (names/terms) from retrieved chunks
        candidate_entities = []
        for chunk in retrieved_chunks:
            text = chunk.get("chunk_text", "")
            # Look for Capitalized phrases as rough entity approximations
            words = re.findall(r"\b[A-Z][a-zA-Z0-9\s]{2,20}\b", text)
            for w in words:
                w_strip = w.strip()
                if w_strip not in candidate_entities and len(w_strip) > 3:
                    candidate_entities.append(w_strip)

        # Truncate candidates to prevent excessive DB queries
        candidate_entities = candidate_entities[:10]

        # Hop 2: Expand Graph, Timeline & Database evidence using extracted candidate names
        related_entities = []
        graph_relationships = []
        timeline_events = []
        matched_evidence = []
        linked_summaries = []

        if case_id:
            # 1. Fetch matching entities in Database
            db_entities = []
            if candidate_entities:
                filters = [LegalEntity.normalized_name.ilike(f"%{e}%") for e in candidate_entities]
                db_entities = (
                    self.db.query(LegalEntity)
                    .filter(and_(LegalEntity.case_id == case_id, or_(*filters)))
                    .limit(10)
                    .all()
                )
            else:
                db_entities = (
                    self.db.query(LegalEntity)
                    .filter(LegalEntity.case_id == case_id)
                    .limit(5)
                    .all()
                )

            # 2. Get Knowledge Graph Neighbors for these entities
            seen_nodes = set()
            for ent in db_entities:
                node_id = ent.id
                if node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                try:
                    graph_data = self.graph_service.get_neighbors(case_id, node_id)
                    graph_relationships.extend(graph_data.get("relationships", []))
                    for node in graph_data.get("connected_nodes", []):
                        if node["id"] not in seen_nodes:
                            related_entities.append(node)
                except Exception as ge:
                    logger.debug("Failed fetching graph neighbors for %s: %s", node_id, ge)

            # 3. Retrieve Timeline Events
            if candidate_entities:
                timeline_filters = [TimelineEvent.description.ilike(f"%{e}%") for e in candidate_entities]
                timeline_events = (
                    self.db.query(TimelineEvent)
                    .filter(and_(TimelineEvent.case_id == case_id, or_(*timeline_filters)))
                    .order_by(TimelineEvent.event_date.asc())
                    .limit(10)
                    .all()
                )
            else:
                timeline_events = (
                    self.db.query(TimelineEvent)
                    .filter(TimelineEvent.case_id == case_id)
                    .order_by(TimelineEvent.event_date.asc())
                    .limit(5)
                    .all()
                )

            # 4. Retrieve Database Evidence
            if candidate_entities:
                evidence_filters = [LegalEvidence.description.ilike(f"%{e}%") for e in candidate_entities]
                matched_evidence = (
                    self.db.query(LegalEvidence)
                    .filter(and_(LegalEvidence.case_id == case_id, or_(*evidence_filters)))
                    .limit(10)
                    .all()
                )
            else:
                matched_evidence = (
                    self.db.query(LegalEvidence)
                    .filter(LegalEvidence.case_id == case_id)
                    .limit(5)
                    .all()
                )

            # 5. Retrieve Linked Document Summaries
            linked_summaries = (
                self.db.query(SummaryCache)
                .filter(SummaryCache.case_id == case_id)
                .limit(3)
                .all()
            )

        # Format retrieved items into plain Dict structures for synthesis
        return {
            "semantic_chunks": retrieved_chunks,
            "entities": [
                {
                    "id": str(e["id"]) if isinstance(e, dict) else str(e.id),
                    "name": e["label"] if isinstance(e, dict) else e.name,
                    "type": e["type"] if isinstance(e, dict) else e.entity_type,
                    "role": e.get("role") if isinstance(e, dict) else getattr(e, "role", None),
                }
                for e in (related_entities + list(db_entities))
            ],
            "graph_relationships": graph_relationships,
            "timeline_events": [
                {
                    "id": str(evt.id),
                    "title": evt.title,
                    "date": evt.event_date.isoformat(),
                    "description": evt.description,
                    "type": evt.event_type,
                    "confidence": evt.confidence_score,
                }
                for evt in timeline_events
            ],
            "evidence": [
                {
                    "id": str(ev.id),
                    "type": ev.evidence_type,
                    "description": ev.description,
                    "confidence": ev.confidence_score,
                    "strength": ev.strength_score,
                }
                for ev in matched_evidence
            ],
            "summaries": [
                {
                    "document_id": str(s.document_id),
                    "summary_text": s.summary_text,
                    "version": s.version_tag,
                }
                for s in linked_summaries
            ],
        }


import re
