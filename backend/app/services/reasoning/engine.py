import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.reasoning import QAHistory, ReasoningMetric
from app.services.llm import LLMService
from app.services.prompt_builder import PromptBuilder
from app.services.provider_router import ProviderRoutingEngine

from app.services.reasoning.query_understanding import QueryUnderstandingService
from app.services.reasoning.multi_hop import MultiHopRetrievalOrchestrator
from app.services.reasoning.evidence import EvidenceRankingEngine, CitationRankingEngine
from app.services.reasoning.contradiction import ContradictionDetectionEngine
from app.services.reasoning.planner import LegalReasoningPlanner, ReasoningChainBuilder
from app.services.reasoning.validation import AnswerValidationEngine
from app.services.reasoning.confidence import ConfidenceCalibrationEngine

logger = logging.getLogger(__name__)


class LegalReasoningEngine:
    """
    Unified Orchestrator Engine for Enterprise Legal Reasoning.
    Links Intent Classification, Multi-Hop Retrieval, Evidence Ranking,
    Contradiction Checks, LLM Routing Synthesis, Confidence Calibration,
    and Factual Grounding Verification.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm_service = LLMService()
        self.router = ProviderRoutingEngine()
        self.prompt_builder = PromptBuilder()

        # Phase 11 Services
        self.classifier = QueryUnderstandingService(self.llm_service)
        self.orchestrator = MultiHopRetrievalOrchestrator(db)
        self.ranker = EvidenceRankingEngine(db)
        self.citation_ranker = CitationRankingEngine()
        self.detector = ContradictionDetectionEngine(db, self.llm_service)
        self.planner = LegalReasoningPlanner()
        self.chain_builder = ReasoningChainBuilder()
        self.validator = AnswerValidationEngine()
        self.calibrator = ConfidenceCalibrationEngine()

    async def reason_query(
        self,
        question: str,
        user_id: uuid.UUID,
        case_id: Optional[uuid.UUID] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Executes non-streaming unified legal reasoning.
        """
        start_time = time.time()

        # 1. Intent Classification
        classification = self.classifier.classify_query(question)
        intent = classification["intent"]
        strategy = classification["strategy"]

        # 2. Multi-hop Retrieval
        # Determine retrieval parameters based on classification
        hops = 2 if strategy in ["Multi-hop reasoning", "Cross-document reasoning"] else 1
        
        # Execute retrieve
        retrieved_data = await self.orchestrator.execute_multi_hop(
            case_id=case_id,
            user_id=user_id,
            query=question,
            hops=hops,
            top_k=top_k,
            threshold=threshold,
        )

        # 3. Evidence & Citation Ranking
        ranked_evidence = self.ranker.rank_evidence(case_id, question, retrieved_data)
        
        # Convert retrieved chunks to base citation items
        raw_citations = []
        for idx, chunk in enumerate(retrieved_data.get("semantic_chunks", [])):
            raw_citations.append({
                "id": str(chunk.get("chunk_id", uuid.uuid4())),
                "text": chunk.get("chunk_text", ""),
                "source_doc": chunk.get("document_title", "Doc"),
                "score": chunk.get("score", 0.70),
            })
        ranked_citations = self.citation_ranker.rank_citations(raw_citations)

        # 4. Contradiction Detection
        contradiction_report = self.detector.detect_contradictions(case_id)
        contradictions = contradiction_report.get("contradictions", [])

        # 5. Confidence Calibration
        calibration = self.calibrator.calibrate_confidence(retrieved_data, ranked_citations, contradictions)
        overall_confidence = calibration["overall_confidence"]
        breakdown = calibration["breakdown"]

        # 6. Reasoning Path Steps Logs
        reasoning_steps = self.chain_builder.build_chain_steps(
            question, intent, strategy, retrieved_data, ranked_evidence, contradictions, overall_confidence
        )

        # 7. Synthesis Prompt Building & LLM Invocation
        # Load active provider routing configurations
        routing = self.router.select_route(question, config_override=provider)
        target_provider = routing["provider"]
        target_model = model or routing["model"]

        # Build prompt injecting intent directives and timelines
        timeline_str = "\n".join([f"- [{e.get('date')}] {e.get('title')}: {e.get('description')}" for e in retrieved_data.get("timeline_events", [])])
        context_str = "\n\n".join([f"Source: {c.get('source')}\nContent: {c.get('description')}" for c in ranked_evidence[:3]])

        system_prompt = (
            "You are ChronoLegal's Lead Legal Reasoning AI. Synthesize an enterprise-grade "
            "legal response. Use the provided ranked evidence, timeline chronology, and intent analysis. "
            "Do not expose internal chain-of-thought steps. Directly answer the question with precise facts."
        )

        prompt = (
            f"Query Intent: {intent}\n"
            f"Reasoning Strategy: {strategy}\n\n"
            f"Ranked Evidence Context:\n{context_str}\n\n"
            f"Timeline Events Chronology:\n{timeline_str}\n\n"
            f"Question: {question}\n\n"
            f"Generate answer:"
        )

        try:
            llm_result = self.llm_service.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                provider=target_provider,
                model=target_model,
            )
            answer = llm_result.get("content", "Failed to synthesize legal answer.")
        except Exception as e:
            logger.error("LegalReasoningEngine: Synthesis failed: %s", e)
            answer = "An error occurred while running reasoning synthesis."

        # 8. Hallucination & Answer Validation
        validation = self.validator.validate_answer(question, answer, retrieved_data, ranked_citations, overall_confidence)

        latency = (time.time() - start_time) * 1000.0

        # Save QA History
        qa_history = QAHistory(
            id=uuid.uuid4(),
            user_id=user_id,
            case_id=case_id,
            question=question,
            answer=answer,
            intent=intent,
            strategy=strategy,
            confidence=overall_confidence,
            confidence_breakdown_json=json.dumps(breakdown),
            reasoning_steps_json=json.dumps(reasoning_steps),
            citations_json=json.dumps(ranked_citations),
            validation_json=json.dumps(validation),
            latency_ms=latency,
        )
        self.db.add(qa_history)

        # Save Metrics
        self.db.add(ReasoningMetric(qa_id=qa_history.id, metric_name="latency_ms", metric_value=latency))
        self.db.add(ReasoningMetric(qa_id=qa_history.id, metric_name="confidence", metric_value=overall_confidence))
        self.db.add(ReasoningMetric(qa_id=qa_history.id, metric_name="grounding_score", metric_value=validation.get("grounding_score", 1.0)))

        self.db.commit()

        return {
            "id": qa_history.id,
            "question": question,
            "answer": answer,
            "intent": intent,
            "strategy": strategy,
            "confidence": overall_confidence,
            "confidence_breakdown": breakdown,
            "reasoning_steps": reasoning_steps,
            "citations": ranked_citations,
            "validation": validation,
            "contradictions": contradictions,
            "evidence_rankings": ranked_evidence,
            "latency_ms": latency,
            "created_at": qa_history.created_at,
        }

    async def stream_reason_query(
        self,
        question: str,
        user_id: uuid.UUID,
        case_id: Optional[uuid.UUID] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streams reasoning response tokens, yielding classification metadata first and final rankings at the end.
        """
        start_time = time.time()

        # 1. Intent Classification & yield
        classification = self.classifier.classify_query(question)
        intent = classification["intent"]
        strategy = classification["strategy"]

        yield {"event": "intent", "data": json.dumps({"intent": intent, "strategy": strategy})}

        # 2. Planning Chain & yield
        yield {"event": "planning", "data": json.dumps({"status": "initiating", "step": "Formulating reasoning chain planner"})}

        # 3. Retrieve context
        hops = 2 if strategy in ["Multi-hop reasoning", "Cross-document reasoning"] else 1
        
        retrieved_data = await self.orchestrator.execute_multi_hop(
            case_id=case_id,
            user_id=user_id,
            query=question,
            hops=hops,
            top_k=top_k,
            threshold=threshold,
        )

        # 4. Rank evidence
        ranked_evidence = self.ranker.rank_evidence(case_id, question, retrieved_data)
        
        raw_citations = []
        for idx, chunk in enumerate(retrieved_data.get("semantic_chunks", [])):
            raw_citations.append({
                "id": str(chunk.get("chunk_id", uuid.uuid4())),
                "text": chunk.get("chunk_text", ""),
                "source_doc": chunk.get("document_title", "Doc"),
                "score": chunk.get("score", 0.70),
            })
        ranked_citations = self.citation_ranker.rank_citations(raw_citations)

        # 5. Contradiction report
        contradiction_report = self.detector.detect_contradictions(case_id)
        contradictions = contradiction_report.get("contradictions", [])

        # 6. Calibrate confidence
        calibration = self.calibrator.calibrate_confidence(retrieved_data, ranked_citations, contradictions)
        overall_confidence = calibration["overall_confidence"]
        breakdown = calibration["breakdown"]

        # 7. Reasoning Steps
        reasoning_steps = self.chain_builder.build_chain_steps(
            question, intent, strategy, retrieved_data, ranked_evidence, contradictions, overall_confidence
        )

        yield {"event": "planning", "data": json.dumps({"status": "completed", "steps": reasoning_steps})}

        # 8. Run LLM stream routing
        routing = self.router.select_route(question, config_override=provider)
        target_provider = routing["provider"]
        target_model = model or routing["model"]

        timeline_str = "\n".join([f"- [{e.get('date')}] {e.get('title')}: {e.get('description')}" for e in retrieved_data.get("timeline_events", [])])
        context_str = "\n\n".join([f"Source: {c.get('source')}\nContent: {c.get('description')}" for c in ranked_evidence[:3]])

        system_prompt = (
            "You are ChronoLegal's Lead Legal Reasoning AI. Synthesize an enterprise-grade "
            "legal response. Use the provided ranked evidence, timeline chronology, and intent analysis. "
            "Do not expose internal chain-of-thought steps. Directly answer the question with precise facts."
        )

        prompt = (
            f"Query Intent: {intent}\n"
            f"Reasoning Strategy: {strategy}\n\n"
            f"Ranked Evidence Context:\n{context_str}\n\n"
            f"Timeline Events Chronology:\n{timeline_str}\n\n"
            f"Question: {question}\n\n"
            f"Generate answer:"
        )

        full_answer = ""
        try:
            stream_gen = self.llm_service.stream_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                provider=target_provider,
                model=target_model,
            )
            for chunk_data in stream_gen:
                token = chunk_data.get("content", "")
                full_answer += token
                if token:
                    yield {"event": "token", "data": token}
        except Exception as e:
            logger.error("LegalReasoningEngine: Streaming failure: %s", e)
            yield {"event": "error", "data": "Streaming synthesis error."}
            return

        # 9. Validation checks
        validation = self.validator.validate_answer(question, full_answer, retrieved_data, ranked_citations, overall_confidence)

        latency = (time.time() - start_time) * 1000.0

        # Save history in DB
        qa_history = QAHistory(
            id=uuid.uuid4(),
            user_id=user_id,
            case_id=case_id,
            question=question,
            answer=full_answer,
            intent=intent,
            strategy=strategy,
            confidence=overall_confidence,
            confidence_breakdown_json=json.dumps(breakdown),
            reasoning_steps_json=json.dumps(reasoning_steps),
            citations_json=json.dumps(ranked_citations),
            validation_json=json.dumps(validation),
            latency_ms=latency,
        )
        self.db.add(qa_history)
        self.db.commit()

        # Yield final completed details
        yield {
            "event": "done",
            "data": json.dumps({
                "id": str(qa_history.id),
                "intent": intent,
                "strategy": strategy,
                "confidence": overall_confidence,
                "confidence_breakdown": breakdown,
                "reasoning_steps": reasoning_steps,
                "citations": ranked_citations,
                "validation": validation,
                "contradictions": contradictions,
                "evidence_rankings": ranked_evidence,
                "latency_ms": latency,
            }),
        }
