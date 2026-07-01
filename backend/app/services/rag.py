import json
import logging
import time
import re
from datetime import datetime, timezone
from typing import Dict, Any, Generator, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import ChatSession, ChatMessage, ChatRole, PromptTemplate
from app.services.retriever import RetrieverService
from app.services.llm import LLMService
from app.services.prompt_builder import PromptBuilder
from app.services.memory import ConversationMemoryService
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval_planner import DynamicRetrievalPlanner
from app.services.context_compression import ContextCompressionEngine
from app.services.provider_router import ProviderRoutingEngine
from app.services.response_validator import ResponseValidator
from app.services.guardrails import GuardrailsEngine

logger = logging.getLogger(__name__)


class RAGService:
    """
    Enterprise RAG Service orchestrating memory managers, query rewrites,
    dynamic planners, cost routers, response validators, and safety guardrails.
    """
    def __init__(self, db: Session) -> None:
        self.db = db
        self.retriever_svc = RetrieverService(db)
        self.llm_svc = LLMService()
        self.prompt_builder = PromptBuilder()
        
        # Conversational extensions
        self.memory_svc = ConversationMemoryService(db)
        from app.services.query_rewrite import QueryRewriteService
        self.rewrite_svc = QueryRewriteService()
        self.planner = DynamicRetrievalPlanner()
        self.compression_svc = ContextCompressionEngine()
        self.router = ProviderRoutingEngine()
        self.validator = ResponseValidator()
        self.guardrails = GuardrailsEngine()

    def query_rag(
        self,
        session_id: UUID,
        user_id: UUID,
        question: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.0,
        case_id: Optional[UUID] = None,
    ) -> ChatMessage:
        start_time = time.time()
        
        # 1. Safety Guardrails Scan
        safety_check = self.guardrails.check_safety(question)
        if not safety_check["safe"]:
            return self._create_guardrail_message(session_id, safety_check["reason"], start_time)

        # Verify / Load Session
        session = self.db.get(ChatSession, session_id)
        if not session:
            session = ChatSession(
                id=session_id,
                user_id=user_id,
                case_id=case_id,
                title=question[:40] + "..." if len(question) > 40 else question,
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        # 2. Save User Message
        user_msg = ChatMessage(
            session_id=session_id,
            content=question,
            role=ChatRole.USER,
        )
        self.db.add(user_msg)
        self.db.commit()

        # 3. Load Conversation Memory & Rewrite Query
        memory_context = self.memory_svc.get_conversation_context(session_id)
        rewritten_query = self.rewrite_svc.rewrite_query(question, memory_context["recent_turns"])

        # 4. Dynamic Retrieval Planning & Strategy Choice
        planned_strategy = self.planner.plan_strategy(rewritten_query)
        target_top_k = planned_strategy["top_k"]
        target_threshold = max(threshold, planned_strategy["threshold"])

        # 5. Retrieve Context Chunks
        retrieved_chunks = self.retriever_svc.retrieve_semantic(
            user_id=user_id,
            query_text=rewritten_query,
            filters={"case_id": case_id} if case_id else {},
            top_k=target_top_k,
            score_threshold=target_threshold,
        )

        # Clean fallback if empty retrieval context
        if not retrieved_chunks:
            return self._create_fallback_message(session_id, start_time, model)

        # 6. Context Compression & Token Budgeting
        compressed_chunks = self.compression_svc.compress_chunks(retrieved_chunks, max_tokens=3000)
        context_text = self.retriever_svc.build_context_window(compressed_chunks)

        # 7. Prompt Loading (Versioning) & Prompt Construction
        prompts_meta = self._load_active_prompts()
        system_prompt = prompts_meta["system_prompt"]
        
        if prompts_meta["user_prompt_template"]:
            # Format custom template
            prompt = prompts_meta["user_prompt_template"].replace("{query}", rewritten_query).replace("{context}", context_text)
        else:
            prompt = self.prompt_builder.build_prompt(rewritten_query, context_text)

        # 8. Provider Routing Engine Choice
        routing = self.router.select_route(rewritten_query, config_override=provider)
        target_provider = routing["provider"]
        target_model = model or routing["model"]

        # 9. Generate LLM answer
        try:
            llm_result = self.llm_svc.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                provider=target_provider,
                model=target_model,
            )
        except Exception as e:
            logger.error("RAGService: LLM Generation failed: %s", str(e), exc_info=True)
            raise e

        latency = (time.time() - start_time) * 1000.0
        raw_content = llm_result.get("content", "")

        # 10. Response Grounding Validation
        validation = self.validator.validate_response(raw_content, compressed_chunks)
        if not validation["success"]:
            # Recalculate with fallback grounding message
            raw_content = "I am sorry, but the provided document contexts do not contain any information regarding this query."

        # Resolve citations
        resolved_citations = self._resolve_citations_list(raw_content, compressed_chunks)
        clean_content = re.sub(r"\[Citation: [a-zA-Z0-9\-]+\]", "", raw_content).strip()

        # Cost tracking
        prompt_tokens = llm_result.get("prompt_tokens", 0)
        completion_tokens = llm_result.get("completion_tokens", 0)
        total_tokens = llm_result.get("total_tokens", 0)
        cost = estimate_cost(target_provider, target_model, prompt_tokens, completion_tokens)

        token_usage_meta = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": cost,
            "model_used": target_model,
            "strategy_planned": planned_strategy["strategy"],
        }

        # 11. Persist Assistant Message
        assistant_msg = ChatMessage(
            session_id=session_id,
            content=clean_content,
            role=ChatRole.ASSISTANT,
            citations_json=json.dumps(resolved_citations),
            token_usage_json=json.dumps(token_usage_meta),
            latency_ms=latency,
            token_count=total_tokens,
        )
        self.db.add(assistant_msg)
        
        # Auto rename session if needed
        if session.title == "New Chat" or session.title.endswith("..."):
            session.title = question[:40] + "..." if len(question) > 40 else question

        self.db.commit()
        self.db.refresh(assistant_msg)

        # Update analytics snapshot
        try:
            from app.services.analytics import AnalyticsService
            AnalyticsService(self.db).refresh_snapshots(case_id=case_id)
        except Exception as ae:
            logger.error("RAGService: failed to refresh analytics on query: %s", ae)

        return assistant_msg

    def stream_rag(
        self,
        session_id: UUID,
        user_id: UUID,
        question: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.0,
        case_id: Optional[UUID] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        start_time = time.time()
        
        # 1. Safety Guardrails Scan
        safety_check = self.guardrails.check_safety(question)
        if not safety_check["safe"]:
            yield {"event": "error", "data": safety_check["reason"]}
            return

        # Verify Session
        session = self.db.get(ChatSession, session_id)
        if not session:
            session = ChatSession(
                id=session_id,
                user_id=user_id,
                case_id=case_id,
                title=question[:40] + "..." if len(question) > 40 else question,
            )
            self.db.add(session)
            self.db.commit()

        # Save User Message
        user_msg = ChatMessage(
            session_id=session_id,
            content=question,
            role=ChatRole.USER,
        )
        self.db.add(user_msg)
        self.db.commit()

        # Load memory & rewrite follow-up
        memory_context = self.memory_svc.get_conversation_context(session_id)
        rewritten_query = self.rewrite_svc.rewrite_query(question, memory_context["recent_turns"])

        # Dynamic retrieval planning
        planned_strategy = self.planner.plan_strategy(rewritten_query)
        target_top_k = planned_strategy["top_k"]
        target_threshold = max(threshold, planned_strategy["threshold"])

        # Retrieve context chunks
        retrieved_chunks = self.retriever_svc.retrieve_semantic(
            user_id=user_id,
            query_text=rewritten_query,
            filters={"case_id": case_id} if case_id else {},
            top_k=target_top_k,
            score_threshold=target_threshold,
        )

        if not retrieved_chunks:
            fallback_text = "I am sorry, but the provided document contexts do not contain any information regarding this query."
            latency = (time.time() - start_time) * 1000.0
            
            # Save Assistant message
            assistant_msg = ChatMessage(
                session_id=session_id,
                content=fallback_text,
                role=ChatRole.ASSISTANT,
                citations_json=json.dumps([]),
                token_usage_json=json.dumps({
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0,
                    "model_used": model or "none",
                }),
                latency_ms=latency,
            )
            self.db.add(assistant_msg)
            self.db.commit()

            yield {"event": "token", "data": fallback_text}
            yield {"event": "done", "data": json.dumps({
                "citations": [],
                "latency_ms": latency,
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0,
                    "model_used": model or "none",
                }
            })}
            return

        # Context compression
        compressed_chunks = self.compression_svc.compress_chunks(retrieved_chunks, max_tokens=3000)
        context_text = self.retriever_svc.build_context_window(compressed_chunks)

        # Versioned prompt templates
        prompts_meta = self._load_active_prompts()
        system_prompt = prompts_meta["system_prompt"]
        if prompts_meta["user_prompt_template"]:
            prompt = prompts_meta["user_prompt_template"].replace("{query}", rewritten_query).replace("{context}", context_text)
        else:
            prompt = self.prompt_builder.build_prompt(rewritten_query, context_text)

        # Provider routing engine selection
        routing = self.router.select_route(rewritten_query, config_override=provider)
        target_provider = routing["provider"]
        target_model = model or routing["model"]

        full_raw_response = ""
        
        # Stream LLM tokens
        try:
            stream_gen = self.llm_svc.stream_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                provider=target_provider,
                model=target_model,
            )
            
            for chunk_data in stream_gen:
                token = chunk_data.get("content", "")
                full_raw_response += token
                
                clean_token = re.sub(r"\[Citation: [a-zA-Z0-9\-]+\]", "", token)
                if clean_token:
                    yield {"event": "token", "data": clean_token}
                    
        except Exception as e:
            logger.error("RAGService: Streaming invocation failed: %s", str(e))
            yield {"event": "error", "data": f"Inference execution failed: {str(e)}"}
            return

        latency = (time.time() - start_time) * 1000.0

        # Grounding validation
        validation = self.validator.validate_response(full_raw_response, compressed_chunks)
        if not validation["success"]:
            full_raw_response = "I am sorry, but the provided document contexts do not contain any information regarding this query."

        resolved_citations = self._resolve_citations_list(full_raw_response, compressed_chunks)
        clean_content = re.sub(r"\[Citation: [a-zA-Z0-9\-]+\]", "", full_raw_response).strip()

        # Token usage & estimation
        prompt_tokens = len(prompt.split()) + len(system_prompt.split())
        completion_tokens = len(full_raw_response.split())
        total_tokens = prompt_tokens + completion_tokens
        
        cost = estimate_cost(target_provider, target_model, prompt_tokens, completion_tokens)

        token_usage_meta = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": cost,
            "model_used": target_model,
            "strategy_planned": planned_strategy["strategy"],
        }

        # Save assistant msg in DB
        assistant_msg = ChatMessage(
            session_id=session_id,
            content=clean_content,
            role=ChatRole.ASSISTANT,
            citations_json=json.dumps(resolved_citations),
            token_usage_json=json.dumps(token_usage_meta),
            latency_ms=latency,
            token_count=total_tokens,
        )
        self.db.add(assistant_msg)
        
        if session.title == "New Chat" or session.title.endswith("..."):
            session.title = question[:40] + "..." if len(question) > 40 else question

        self.db.commit()

        # Update analytics snapshot
        try:
            from app.services.analytics import AnalyticsService
            AnalyticsService(self.db).refresh_snapshots(case_id=case_id)
        except Exception as ae:
            logger.error("RAGService: failed to refresh analytics on stream query: %s", ae)

        # Send terminal SSE payload with metadata
        yield {"event": "done", "data": json.dumps({
            "citations": resolved_citations,
            "latency_ms": latency,
            "token_usage": token_usage_meta,
        })}

    def _resolve_citations_list(self, text: str, retrieved_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        uuids = re.findall(r"\[Citation: ([a-zA-Z0-9\-]+)\]", text)
        resolved = []
        seen = set()

        chunk_map = {str(c["chunk_id"]): c for c in retrieved_chunks}
        for u in uuids:
            if u in seen:
                continue
            seen.add(u)

            if u in chunk_map:
                c = chunk_map[u]
                resolved.append({
                    "chunk_id": u,
                    "document_id": c["document_id"],
                    "document_name": c["document_name"],
                    "page_number": c["page_number"],
                    "section_title": c["section_title"],
                    "similarity_score": c["similarity_score"],
                    "source_path": c["source_path"],
                })
        return resolved

    def _load_active_prompts(self) -> Dict[str, Optional[str]]:
        """Loads active PromptTemplate models from DB or falls back to prompt_builder defaults."""
        sys_tmpl = self.db.query(PromptTemplate).filter(
            PromptTemplate.name == "system_prompt", PromptTemplate.is_active == True
        ).first()
        user_tmpl = self.db.query(PromptTemplate).filter(
            PromptTemplate.name == "user_prompt", PromptTemplate.is_active == True
        ).first()

        system_prompt = sys_tmpl.content if sys_tmpl else self.prompt_builder.build_system_prompt()
        user_prompt = user_tmpl.content if user_tmpl else None

        return {
            "system_prompt": system_prompt,
            "user_prompt_template": user_prompt,
        }

    def _create_guardrail_message(self, session_id: UUID, reason: str, start_time: float) -> ChatMessage:
        latency = (time.time() - start_time) * 1000.0
        msg = ChatMessage(
            session_id=session_id,
            content=reason,
            role=ChatRole.ASSISTANT,
            citations_json=json.dumps([]),
            token_usage_json=json.dumps({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost": 0.0, "model_used": "guardrail"}),
            latency_ms=latency,
        )
        self.db.add(msg)
        self.db.commit()
        return msg

    def _create_fallback_message(self, session_id: UUID, start_time: float, model: Optional[str]) -> ChatMessage:
        fallback_text = "I am sorry, but the provided document contexts do not contain any information regarding this query."
        latency = (time.time() - start_time) * 1000.0
        msg = ChatMessage(
            session_id=session_id,
            content=fallback_text,
            role=ChatRole.ASSISTANT,
            citations_json=json.dumps([]),
            token_usage_json=json.dumps({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost": 0.0, "model_used": model or "none"}),
            latency_ms=latency,
        )
        self.db.add(msg)
        self.db.commit()
        return msg

    def get_statistics(self, user_id: UUID) -> Dict[str, Any]:
        """Aggregate stats for RAG chats."""
        sessions_ids = [s.id for s in self.db.query(ChatSession).filter(ChatSession.user_id == user_id).all()]
        if not sessions_ids:
            return {
                "total_chats": 0,
                "average_latency_ms": 0.0,
                "total_tokens_used": 0,
                "total_estimated_cost": 0.0,
                "provider_usage": {},
            }

        total_msgs = self.db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.session_id.in_(sessions_ids),
            ChatMessage.role == ChatRole.ASSISTANT
        ).scalar() or 0

        avg_latency = self.db.query(func.avg(ChatMessage.latency_ms)).filter(
            ChatMessage.session_id.in_(sessions_ids),
            ChatMessage.role == ChatRole.ASSISTANT
        ).scalar() or 0.0

        total_tokens = self.db.query(func.sum(ChatMessage.token_count)).filter(
            ChatMessage.session_id.in_(sessions_ids),
            ChatMessage.role == ChatRole.ASSISTANT
        ).scalar() or 0

        msg_usages = self.db.query(ChatMessage.token_usage_json).filter(
            ChatMessage.session_id.in_(sessions_ids),
            ChatMessage.role == ChatRole.ASSISTANT
        ).all()

        total_cost = 0.0
        provider_counts = {}

        for (usage_str,) in msg_usages:
            if usage_str:
                try:
                    usage = json.loads(usage_str)
                    total_cost += usage.get("estimated_cost", 0.0)
                    model = usage.get("model_used", "default")
                    provider_counts[model] = provider_counts.get(model, 0) + 1
                except ValueError:
                    pass

        return {
            "total_chats": total_msgs,
            "average_latency_ms": round(float(avg_latency), 2),
            "total_tokens_used": int(total_tokens),
            "total_estimated_cost": round(total_cost, 5),
            "provider_usage": provider_counts,
        }


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = provider.lower() if provider else ""
    m = model.lower() if model else ""
    
    if "openai" in p or "gpt" in m:
        # GPT-4 average: input $0.005 / 1k, output $0.015 / 1k
        in_cost = (prompt_tokens / 1000.0) * 0.005
        out_cost = (completion_tokens / 1000.0) * 0.015
        return in_cost + out_cost
    elif "gemini" in p:
        # Gemini: input $0.000375 / 1k, output $0.00115 / 1k
        in_cost = (prompt_tokens / 1000.0) * 0.000375
        out_cost = (completion_tokens / 1000.0) * 0.00115
        return in_cost + out_cost
    
    return 0.0
