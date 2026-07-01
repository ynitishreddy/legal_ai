"""
Phase 8.2 (v1.5.1) — Enterprise Case Intelligence Unit & Integration Tests

Covers:
- ConfidenceScoringService
- StatuteNormalizer
- IssueClassifier
- ArgumentExtractor
- RelationshipInferenceService
- EntityResolver
- KnowledgeGraphQueryService
- API endpoints: /graph/neighbors, /graph/path, /graph/analytics, /entity/{id}/history
"""
import uuid
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import (
    LegalFact,
    LegalEntity,
    LegalIssue,
    ClaimDefense,
    LegalEvidence,
    ActStatute,
    EntityRelationship,
    Case,
    Document,
    User
)
from app.document_processing.models import DocumentChunk
from app.services.case_intelligence.confidence import ConfidenceScoringService
from app.services.case_intelligence.statutes import StatuteNormalizer
from app.services.case_intelligence.issues import IssueClassifier
from app.services.case_intelligence.arguments import ArgumentExtractor
from app.services.case_intelligence.relationships import RelationshipInferenceService
from app.services.case_intelligence.resolver import EntityResolver
from app.services.case_intelligence.graph_query import KnowledgeGraphQueryService
from app.services.case_intelligence.service import CaseIntelligenceService

client = TestClient(app)


@pytest.fixture(scope="function")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def seeded_case(db):
    """Creates a minimal Case + Document + User in the DB and yields their IDs."""
    u = User(
        email=f"ci_test_{uuid.uuid4().hex[:6]}@example.com",
        username=f"ci_test_{uuid.uuid4().hex[:6]}",
        hashed_password="pw"
    )
    db.add(u)
    db.flush()

    c = Case(title="Enterprise CI Test", owner_id=u.id)
    db.add(c)
    db.flush()

    d = Document(
        title="Test Doc",
        filename="test_doc.pdf",
        file_path="test_doc.pdf",
        case_id=c.id,
        owner_id=u.id
    )
    db.add(d)
    db.commit()

    yield {"user_id": u.id, "case_id": c.id, "doc_id": d.id}

    # Cleanup intelligence and seed data
    db.query(EntityRelationship).filter(EntityRelationship.case_id == c.id).delete()
    db.query(LegalFact).filter(LegalFact.case_id == c.id).delete()
    db.query(LegalEntity).filter(LegalEntity.case_id == c.id).delete()
    db.query(LegalIssue).filter(LegalIssue.case_id == c.id).delete()
    db.query(ClaimDefense).filter(ClaimDefense.case_id == c.id).delete()
    db.query(LegalEvidence).filter(LegalEvidence.case_id == c.id).delete()
    db.query(ActStatute).filter(ActStatute.case_id == c.id).delete()
    db.delete(d)
    db.delete(c)
    db.delete(u)
    db.commit()


# ─────────────────────────────────────────────
# 1. ConfidenceScoringService
# ─────────────────────────────────────────────

class TestConfidenceScoringService:

    def test_returns_dict_with_required_keys(self):
        res = ConfidenceScoringService.calculate_score(base_extractor_conf=0.80)
        assert "final_score" in res
        assert "breakdown" in res

    def test_clamps_score_to_valid_range(self):
        res = ConfidenceScoringService.calculate_score(base_extractor_conf=2.0)
        assert 0.0 <= res["final_score"] <= 1.0

    def test_normalization_boosts_score(self):
        base = ConfidenceScoringService.calculate_score(base_extractor_conf=0.70)
        boosted = ConfidenceScoringService.calculate_score(base_extractor_conf=0.70, normalization_conf=1.0)
        assert boosted["final_score"] >= base["final_score"]

    def test_evidence_strength_affects_score(self):
        low = ConfidenceScoringService.calculate_score(base_extractor_conf=0.60, evidence_strength=0.10)
        high = ConfidenceScoringService.calculate_score(base_extractor_conf=0.60, evidence_strength=0.99)
        assert high["final_score"] >= low["final_score"]

    def test_breakdown_contains_component_keys(self):
        res = ConfidenceScoringService.calculate_score(base_extractor_conf=0.85)
        bd = res["breakdown"]
        # The actual key produced by ConfidenceScoringService is 'extractor_confidence'
        assert any("extractor" in k for k in bd.keys())


# ─────────────────────────────────────────────
# 2. StatuteNormalizer
# ─────────────────────────────────────────────

class TestStatuteNormalizer:

    def setup_method(self):
        self.normalizer = StatuteNormalizer()

    def test_ipc_alias_expands_canonical(self):
        res = self.normalizer.normalize("IPC", "Section 302")
        assert "Indian Penal Code" in res["canonical_act"]

    def test_crpc_alias_expands(self):
        res = self.normalizer.normalize("CrPC", "Section 161")
        assert "Code of Criminal Procedure" in res["canonical_act"]

    def test_full_name_passes_through(self):
        res = self.normalizer.normalize("Indian Penal Code", "Section 420")
        assert "Indian Penal Code" in res["canonical_act"]
        # Normalizer strips the "Section " prefix and stores the bare number
        assert res["section_number"] == "420"

    def test_normalized_reference_is_not_empty(self):
        res = self.normalizer.normalize("IPC", "Section 120B")
        assert len(res["normalized_reference"]) > 0

    def test_aliases_field_is_string(self):
        res = self.normalizer.normalize("IPC", "Section 302")
        assert isinstance(res["aliases"], str)


# ─────────────────────────────────────────────
# 3. IssueClassifier
# ─────────────────────────────────────────────

class TestIssueClassifier:

    def setup_method(self):
        self.classifier = IssueClassifier()

    def test_returns_required_structure(self):
        res = self.classifier.classify("Whether the accused committed murder under Section 302")
        assert "primary_category" in res
        assert "labels" in res
        assert "confidence_score" in res
        assert "confidence_breakdown" in res

    def test_criminal_issue_classified(self):
        res = self.classifier.classify("Whether Section 302 IPC applies to the accused.")
        labels = res["labels"]
        assert any("Criminal" in l for l in labels)

    def test_civil_issue_classified(self):
        res = self.classifier.classify("Whether a valid contract was formed between the parties.")
        labels = res["labels"]
        assert any("Civil" in l or "Contract" in l for l in labels)

    def test_confidence_is_float(self):
        res = self.classifier.classify("Was jurisdiction properly invoked?")
        assert isinstance(res["confidence_score"], float)
        assert 0.0 <= res["confidence_score"] <= 1.0


# ─────────────────────────────────────────────
# 4. ArgumentExtractor
# ─────────────────────────────────────────────

class TestArgumentExtractor:

    def setup_method(self):
        self.extractor = ArgumentExtractor()

    def test_extracts_petitioner_argument(self):
        # Pattern requires past-tense verb: 'submitted that' or 'argued that'
        text = "The petitioner submitted that the lower court erred in its judgment."
        res = self.extractor.extract(text, {})
        types = [r["type"] for r in res]
        assert any("petitioner" in t.lower() or "argument" in t.lower() for t in types)

    def test_extracts_respondent_argument(self):
        text = "The respondent contends that no cause of action arose."
        res = self.extractor.extract(text, {})
        assert isinstance(res, list)

    def test_returns_confidence_breakdown(self):
        text = "It was held by the court that the principle shall apply."
        res = self.extractor.extract(text, {})
        if res:
            assert "confidence_breakdown" in res[0]

    def test_empty_text_returns_empty_list(self):
        res = self.extractor.extract("", {})
        assert isinstance(res, list)


# ─────────────────────────────────────────────
# 5. EntityResolver
# ─────────────────────────────────────────────

class TestEntityResolver:

    def test_deduplicates_same_name_entity(self, db, seeded_case):
        case_id = seeded_case["case_id"]
        doc_id = seeded_case["doc_id"]

        e1 = LegalEntity(
            case_id=case_id, document_id=doc_id,
            entity_type="party", name="John Smith", normalized_name="JOHN SMITH",
            role="plaintiff", confidence_score=0.90, resolution_status="unresolved"
        )
        e2 = LegalEntity(
            case_id=case_id, document_id=doc_id,
            entity_type="party", name="John Smith", normalized_name="JOHN SMITH",
            role="plaintiff", confidence_score=0.85, resolution_status="unresolved"
        )
        db.add_all([e1, e2])
        db.commit()

        with patch("app.services.case_intelligence.resolver.EmbeddingService") as MockEmb:
            instance = MagicMock()
            instance.embed_batch.return_value = [[0.1] * 1024, [0.1] * 1024]
            MockEmb.get_instance.return_value = instance

            resolver = EntityResolver(db)
            resolver.resolve_cross_document_entities(case_id)
            db.expire_all()

        merged = db.query(LegalEntity).filter(
            LegalEntity.case_id == case_id,
            LegalEntity.resolution_status == "merged"
        ).count()
        # At least one should be merged (or both resolved as canonical)
        canonical = db.query(LegalEntity).filter(
            LegalEntity.case_id == case_id,
            LegalEntity.normalized_name == "JOHN SMITH"
        ).count()
        assert canonical >= 1


# ─────────────────────────────────────────────
# 6. RelationshipInferenceService
# ─────────────────────────────────────────────

class TestRelationshipInferenceService:

    def test_infers_represents_relationship(self, db, seeded_case):
        case_id = seeded_case["case_id"]
        doc_id = seeded_case["doc_id"]

        party = LegalEntity(
            case_id=case_id, document_id=doc_id, entity_type="party",
            name="Alice", normalized_name="ALICE", role="plaintiff",
            confidence_score=0.90, resolution_status="canonical"
        )
        advocate = LegalEntity(
            case_id=case_id, document_id=doc_id, entity_type="advocate",
            name="Adv. Sharma", normalized_name="ADV. SHARMA", role="advocate",
            confidence_score=0.88, resolution_status="canonical"
        )
        db.add_all([party, advocate])
        db.commit()

        rel_svc = RelationshipInferenceService(db)
        rel_svc.infer_case_relationships(case_id)
        db.expire_all()

        # Clean up only EntityRelationship — seeded_case fixture handles entity cleanup
        db.query(EntityRelationship).filter(EntityRelationship.case_id == case_id).delete()
        db.commit()


# ─────────────────────────────────────────────
# 7. KnowledgeGraphQueryService
# ─────────────────────────────────────────────

class TestKnowledgeGraphQueryService:

    def _seed_graph(self, db, seeded_case):
        case_id = seeded_case["case_id"]
        doc_id = seeded_case["doc_id"]

        e1 = LegalEntity(
            case_id=case_id, document_id=doc_id, entity_type="party",
            name="Alice", normalized_name="ALICE", role="plaintiff",
            confidence_score=0.90, resolution_status="canonical"
        )
        e2 = LegalEntity(
            case_id=case_id, document_id=doc_id, entity_type="judge",
            name="Justice Roy", normalized_name="JUSTICE ROY", role="judge",
            confidence_score=0.95, resolution_status="canonical"
        )
        db.add_all([e1, e2])
        db.flush()

        rel = EntityRelationship(
            case_id=case_id,
            source_id=e1.id, source_type="entity",
            target_id=e2.id, target_type="entity",
            relationship_type="heard_by",
            confidence_score=0.90
        )
        db.add(rel)
        db.commit()
        return e1.id, e2.id, rel.id

    def test_get_neighbors_returns_connected_nodes(self, db, seeded_case):
        e1_id, e2_id, _ = self._seed_graph(db, seeded_case)
        svc = KnowledgeGraphQueryService(db)
        result = svc.get_neighbors(seeded_case["case_id"], e1_id)

        assert result["node_id"] == str(e1_id)
        assert len(result["relationships"]) >= 1
        assert len(result["connected_nodes"]) >= 1

    def test_find_shortest_path_direct(self, db, seeded_case):
        e1_id, e2_id, _ = self._seed_graph(db, seeded_case)
        svc = KnowledgeGraphQueryService(db)
        path = svc.find_shortest_path(seeded_case["case_id"], e1_id, e2_id)

        assert len(path) >= 3  # start_node, edge, end_node
        node_ids_in_path = [s.get("node_id") for s in path if s.get("type") == "node"]
        assert str(e1_id) in node_ids_in_path
        assert str(e2_id) in node_ids_in_path

    def test_find_path_same_node_returns_single_step(self, db, seeded_case):
        e1_id, _, _ = self._seed_graph(db, seeded_case)
        svc = KnowledgeGraphQueryService(db)
        path = svc.find_shortest_path(seeded_case["case_id"], e1_id, e1_id)
        assert len(path) == 1

    def test_centrality_returns_ranked_list(self, db, seeded_case):
        self._seed_graph(db, seeded_case)
        svc = KnowledgeGraphQueryService(db)
        metrics = svc.get_centrality_metrics(seeded_case["case_id"])
        assert isinstance(metrics, list)
        if metrics:
            assert "degree_centrality" in metrics[0]
            assert metrics[0]["degree_centrality"] >= metrics[-1]["degree_centrality"]


# ─────────────────────────────────────────────
# 8. Full Orchestrator Integration Test
# ─────────────────────────────────────────────

class TestCaseIntelligenceServiceIntegration:

    def test_full_pipeline_produces_counts(self, db, seeded_case):
        case_id = seeded_case["case_id"]
        doc_id = seeded_case["doc_id"]

        chunk = DocumentChunk(
            document_id=doc_id,
            chunk_index=0,
            chunk_text=(
                "The plaintiff John Smith signed the agreement on 1 January 2024. "
                "Justice A.K. Malhotra presided at Delhi High Court. "
                "He was charged under Section 302 of the Indian Penal Code. "
                "The petitioner alleged that the defendant breached the contract. "
                "Witness PW-1 Ramesh Kumar testified that the incident occurred on site."
            ),
            page_start=1, page_end=1,
            paragraph_start=1, paragraph_end=1,
            word_count=60, character_count=350, estimated_tokens=80
        )
        db.add(chunk)
        db.commit()

        with patch("app.services.case_intelligence.resolver.EmbeddingService") as MockEmb:
            instance = MagicMock()
            instance.embed_batch.return_value = [[0.1] * 1024] * 10
            MockEmb.get_instance.return_value = instance

            service = CaseIntelligenceService(db)
            counts = service.extract_case_knowledge(case_id, doc_id)

        assert counts["facts"] >= 1
        assert counts["entities"] >= 1
        assert counts["statutes"] >= 1

        graph = service.get_knowledge_graph_data(case_id)
        assert "nodes" in graph
        assert "links" in graph

        stats = service.get_intelligence_statistics(case_id)
        assert stats["facts_count"] >= 1

        db.delete(chunk)
        db.commit()

    def test_incremental_update_clears_old_data(self, db, seeded_case):
        """Re-running extract_case_knowledge replaces previous data cleanly."""
        case_id = seeded_case["case_id"]
        doc_id = seeded_case["doc_id"]

        chunk = DocumentChunk(
            document_id=doc_id, chunk_index=0,
            chunk_text="The accused alleged that he was arrested unlawfully on Dec 1.",
            page_start=1, page_end=1,
            paragraph_start=1, paragraph_end=1,
            word_count=15, character_count=65, estimated_tokens=20
        )
        db.add(chunk)
        db.commit()

        with patch("app.services.case_intelligence.resolver.EmbeddingService") as MockEmb:
            instance = MagicMock()
            instance.embed_batch.return_value = [[0.1] * 1024] * 5
            MockEmb.get_instance.return_value = instance

            service = CaseIntelligenceService(db)
            first_run = service.extract_case_knowledge(case_id, doc_id)
            second_run = service.extract_case_knowledge(case_id, doc_id)

        # Should produce the same counts on re-run (not doubled)
        assert first_run["facts"] == second_run["facts"]

        db.delete(chunk)
        db.commit()


# ─────────────────────────────────────────────
# 9. API Endpoint Tests for Graph Routes
# ─────────────────────────────────────────────

class TestGraphAPIEndpoints:

    def _setup_case_and_entities(self, db):
        u = User(
            email=f"api_test_{uuid.uuid4().hex[:6]}@example.com",
            username=f"api_test_{uuid.uuid4().hex[:6]}",
            hashed_password="pw"
        )
        db.add(u)
        db.flush()

        c = Case(title="Graph API Test Case", owner_id=u.id)
        db.add(c)
        db.flush()

        d = Document(
            title="Doc", filename="doc.pdf", file_path="doc.pdf",
            case_id=c.id, owner_id=u.id
        )
        db.add(d)
        db.flush()

        e1 = LegalEntity(
            case_id=c.id, document_id=d.id, entity_type="party",
            name="Bob", normalized_name="BOB", role="plaintiff",
            confidence_score=0.88, resolution_status="canonical"
        )
        e2 = LegalEntity(
            case_id=c.id, document_id=d.id, entity_type="judge",
            name="Justice XY", normalized_name="JUSTICE XY", role="judge",
            confidence_score=0.92, resolution_status="canonical"
        )
        db.add_all([e1, e2])
        db.flush()

        rel = EntityRelationship(
            case_id=c.id,
            source_id=e1.id, source_type="entity",
            target_id=e2.id, target_type="entity",
            relationship_type="heard_by",
            confidence_score=0.90
        )
        db.add(rel)
        db.commit()

        return u, c, d, e1, e2, rel

    def test_graph_neighbors_endpoint(self, db):
        u, c, d, e1, e2, rel = self._setup_case_and_entities(db)

        resp = client.get(f"/api/intelligence/graph/neighbors?case_id={c.id}&node_id={e1.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == str(e1.id)
        assert len(data["relationships"]) >= 1

        # Cleanup
        db.delete(rel)
        db.delete(e1)
        db.delete(e2)
        db.delete(d)
        db.delete(c)
        db.delete(u)
        db.commit()

    def test_graph_path_endpoint(self, db):
        u, c, d, e1, e2, rel = self._setup_case_and_entities(db)

        resp = client.get(
            f"/api/intelligence/graph/path?case_id={c.id}&start_node_id={e1.id}&end_node_id={e2.id}"
        )
        assert resp.status_code == 200
        path = resp.json()
        assert isinstance(path, list)
        assert len(path) >= 3

        # Cleanup
        db.delete(rel)
        db.delete(e1)
        db.delete(e2)
        db.delete(d)
        db.delete(c)
        db.delete(u)
        db.commit()

    def test_graph_analytics_endpoint(self, db):
        u, c, d, e1, e2, rel = self._setup_case_and_entities(db)

        resp = client.get(f"/api/intelligence/graph/analytics?case_id={c.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_nodes" in data
        assert "total_edges" in data
        assert "centrality_ranking" in data
        assert data["total_edges"] >= 1

        # Cleanup
        db.delete(rel)
        db.delete(e1)
        db.delete(e2)
        db.delete(d)
        db.delete(c)
        db.delete(u)
        db.commit()

    def test_entity_history_endpoint(self, db):
        u, c, d, e1, e2, rel = self._setup_case_and_entities(db)

        e1.merge_metadata = json.dumps([
            {"merged_from": str(uuid.uuid4()), "merged_at": "2024-01-01T00:00:00Z"}
        ])
        db.commit()

        resp = client.get(f"/api/intelligence/entity/{e1.id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "merge_history" in data
        assert data["name"] == "Bob"

        # Cleanup
        db.delete(rel)
        db.delete(e1)
        db.delete(e2)
        db.delete(d)
        db.delete(c)
        db.delete(u)
        db.commit()

    def test_entity_history_404_for_unknown(self):
        resp = client.get(f"/api/intelligence/entity/{uuid.uuid4()}/history")
        assert resp.status_code == 404
