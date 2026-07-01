import uuid
import json
import re
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Generator
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc

from app.models import (
    Case, Document, TimelineEvent, LegalFact, LegalEntity, LegalEvidence,
    ClaimDefense, ActStatute, EntityRelationship, JobStatus
)
from app.models.summary import Summary, SummaryVersion, SummaryCitation, SummaryCache, SummaryGenerationJob
from app.services.llm import LLMService
from app.services.rag import estimate_cost

logger = logging.getLogger(__name__)


class RetrievalContextBuilder:
    def __init__(self, db: Session):
        self.db = db

    def build_context(self, case_id: uuid.UUID, summary_type: str) -> str:
        """Assembles structured intelligence tables instead of raw documents text."""
        case = self.db.get(Case, case_id)
        if not case:
            return "Case details not found."

        header = f"CASE TITLE: {case.title}\nCOURT: {case.court_name or 'N/A'}\nJURISDICTION: {case.jurisdiction or 'N/A'}\nJUDGE: {case.judge_name or 'N/A'}\n\n"
        
        t = summary_type.lower()
        if t == "executive":
            # Overview statistics + primary claims
            claims = self.db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id).limit(5).all()
            facts = self.db.query(LegalFact).filter(LegalFact.case_id == case_id).limit(5).all()
            
            ctx = "KEY FACTS:\n"
            for f in facts:
                ctx += f"- {f.fact_text} [Fact: {f.id}]\n"
            ctx += "\nPRIMARY CLAIMS/DEFENSES:\n"
            for c in claims:
                ctx += f"- {c.statement} (Type: {c.type}) [Claim: {c.id}]\n"
            return header + ctx

        elif t == "chronological" or t == "timeline":
            # Sorted timeline events
            events = self.db.query(TimelineEvent).filter(TimelineEvent.case_id == case_id).order_by(TimelineEvent.event_date).all()
            ctx = "CHRONOLOGICAL CASE EVENTS:\n"
            for e in events:
                dt_str = e.event_date.strftime("%Y-%m-%d") if e.event_date else "Unknown Date"
                ctx += f"- [{dt_str}] {e.title}: {e.description or ''} [TimelineEvent: {e.id}]\n"
            return header + ctx

        elif t == "legal" or t == "statutes":
            # Statutes mapped + facts
            statutes = self.db.query(ActStatute).filter(ActStatute.case_id == case_id).all()
            ctx = "APPLICABLE ACTS & STATUTES:\n"
            for s in statutes:
                ctx += f"- {s.normalized_reference} (Act: {s.act_name}) [Statute: {s.id}]\n"
            return header + ctx

        elif t == "parties":
            # Parties resolved
            entities = self.db.query(LegalEntity).filter(
                and_(LegalEntity.case_id == case_id, LegalEntity.entity_type == "party")
            ).all()
            ctx = "INVOLVED PARTIES:\n"
            for ent in entities:
                ctx += f"- Name: {ent.name} (Role: {ent.role or 'N/A'}) [Entity: {ent.id}]\n"
            return header + ctx

        elif t == "evidence":
            # Evidence strength
            evidence = self.db.query(LegalEvidence).filter(LegalEvidence.case_id == case_id).all()
            ctx = "CASE EVIDENCE LOGS:\n"
            for ev in evidence:
                ctx += f"- {ev.description} (Type: {ev.evidence_type}, Strength: {round(ev.strength_score * 100)}%) [Evidence: {ev.id}]\n"
            return header + ctx

        elif t == "arguments":
            # Claims + facts arguments
            claims = self.db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id).all()
            ctx = "LEGAL PLEADINGS & CONTENTIONS:\n"
            for c in claims:
                ctx += f"- {c.statement} [Claim: {c.id}]\n"
            return header + ctx

        else:
            # Fallback combining facts & timeline
            facts = self.db.query(LegalFact).filter(LegalFact.case_id == case_id).limit(10).all()
            ctx = "CASE FACTS SUMMARY:\n"
            for f in facts:
                ctx += f"- {f.fact_text} [Fact: {f.id}]\n"
            return header + ctx


class SummaryPlanner:
    @staticmethod
    def plan(summary_type: str, context: str) -> Dict[str, Any]:
        """Formulates targeted prompts and token budgets based on category."""
        t = summary_type.lower()
        
        system_prompt = (
            "You are an elite legal research assistant. Your task is to generate a professional, structured, "
            "and concise summary using ONLY the provided case intelligence context blocks.\n"
            "CRITICAL: You must append the appropriate citation tag next to every claim or fact in your output text.\n"
            "Format your citations exactly as they are provided in brackets in the context, for example: [Fact: <uuid>] or [TimelineEvent: <uuid>].\n"
            "Do not invent citation IDs."
        )

        user_prompt = f"Generate a detailed {t.upper()} summary for this case. Ensure all facts are citation-backed.\n\nCONTEXT DETAILS:\n{context}"

        # Estimate budget
        max_tokens = 1500
        if t == "executive":
            max_tokens = 800

        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": max_tokens,
            "prompt_version": "1.0.0"
        }


class SummaryCacheManager:
    def __init__(self, db: Session):
        self.db = db

    def compute_hash(self, case_id: uuid.UUID, summary_type: str) -> str:
        """Computes a SHA256 signature reflecting timelines, facts, and entities counts/dates."""
        # Query total fact count and last timeline modification
        fact_count = self.db.query(LegalFact).filter(LegalFact.case_id == case_id).count()
        event_count = self.db.query(TimelineEvent).filter(TimelineEvent.case_id == case_id).count()
        entity_count = self.db.query(LegalEntity).filter(LegalEntity.case_id == case_id).count()
        
        # Combined string signature
        sig = f"case:{case_id}|type:{summary_type}|facts:{fact_count}|events:{event_count}|entities:{entity_count}"
        return hashlib.sha256(sig.encode("utf-8")).hexdigest()

    def get_valid_cache(self, case_id: uuid.UUID, summary_type: str) -> Optional[SummaryVersion]:
        """Returns the cached summary version if inputs have not modified."""
        h = self.compute_hash(case_id, summary_type)
        cached = self.db.query(SummaryCache).filter(
            and_(
                SummaryCache.case_id == case_id,
                SummaryCache.summary_type == summary_type,
                SummaryCache.inputs_hash == h
            )
        ).first()
        
        if cached:
            return cached.summary_version
        return None

    def cache_version(self, case_id: uuid.UUID, summary_type: str, version_id: uuid.UUID) -> None:
        """Saves/updates inputs hash cached version mapping."""
        h = self.compute_hash(case_id, summary_type)
        existing = self.db.query(SummaryCache).filter(
            and_(
                SummaryCache.case_id == case_id,
                SummaryCache.summary_type == summary_type
            )
        ).first()

        if existing:
            existing.inputs_hash = h
            existing.summary_version_id = version_id
            existing.updated_at = datetime.now(timezone.utc)
        else:
            cache_entry = SummaryCache(
                case_id=case_id,
                summary_type=summary_type,
                inputs_hash=h,
                summary_version_id=version_id
            )
            self.db.add(cache_entry)
        self.db.commit()


class SummaryService:
    def __init__(self, db: Session):
        self.db = db
        self.context_builder = RetrievalContextBuilder(db)
        self.cache_manager = SummaryCacheManager(db)
        self.llm_service = LLMService()

    def generate_summary(
        self,
        case_id: uuid.UUID,
        summary_type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        regenerate: bool = False
    ) -> SummaryVersion:
        """Retrieves active cached version, or runs LLM completion to construct a versioned summary."""
        # 1. Cache hit check
        if not regenerate:
            cached_version = self.cache_manager.get_valid_cache(case_id, summary_type)
            if cached_version:
                logger.info("SummaryService: Cache hit for case_id=%s type=%s", case_id, summary_type)
                return cached_version

        # 2. Start generation job
        job = SummaryGenerationJob(
            case_id=case_id,
            summary_type=summary_type,
            status=JobStatus.RUNNING,
            progress=10
        )
        self.db.add(job)
        self.db.commit()

        try:
            # 3. Plan strategy and retrieve context
            job.progress = 30
            self.db.commit()
            context = self.context_builder.build_context(case_id, summary_type)
            plan = SummaryPlanner.plan(summary_type, context)

            # 4. Invoke LLM Adapter
            job.progress = 70
            self.db.commit()
            
            target_provider = provider or "mock"
            target_model = model or "mock-model"

            start_time = datetime.now()
            res = self.llm_service.generate_answer(
                prompt=plan["user_prompt"],
                system_prompt=plan["system_prompt"],
                provider=target_provider,
                model=target_model
            )
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000.0
            
            summary_text = res.get("content", "")

            # 5. Extract citations
            job.progress = 90
            self.db.commit()
            citations = self._parse_citations(summary_text)

            # Clean citations brackets text if needed, but keeping them inline is standard
            # Create Summary and Version
            summary = self.db.query(Summary).filter(
                and_(Summary.case_id == case_id, Summary.summary_type == summary_type)
            ).first()

            if not summary:
                summary = Summary(case_id=case_id, summary_type=summary_type)
                self.db.add(summary)
                self.db.flush()

            # Versioning
            next_ver_num = len(summary.versions) + 1
            
            # Deactivate previous versions
            for v in summary.versions:
                v.is_active = False

            # Token cost estimation
            prompt_tok = res.get("prompt_tokens", 0)
            comp_tok = res.get("completion_tokens", 0)
            cost = estimate_cost(target_provider, target_model, prompt_tok, comp_tok)

            token_usage = {
                "prompt_tokens": prompt_tok,
                "completion_tokens": comp_tok,
                "total_tokens": prompt_tok + comp_tok,
                "cost": cost,
                "latency_ms": duration_ms
            }

            version = SummaryVersion(
                summary_id=summary.id,
                version=next_ver_num,
                summary_text=summary_text,
                provider=target_provider,
                model_used=target_model,
                prompt_version=plan["prompt_version"],
                token_usage_json=json.dumps(token_usage),
                is_active=True
            )
            self.db.add(version)
            self.db.flush()

            # Insert citations
            for cit in citations:
                cit_record = SummaryCitation(
                    summary_version_id=version.id,
                    citation_type=cit["type"],
                    source_id=cit["id"],
                    source_title=cit["title"],
                    citation_text=cit["text"]
                )
                self.db.add(cit_record)

            self.db.flush()
            
            # 6. Cache version mapping
            self.cache_manager.cache_version(case_id, summary_type, version.id)

            # Complete job
            job.status = JobStatus.COMPLETED
            job.progress = 100
            self.db.commit()

            return version

        except Exception as e:
            logger.error("SummaryService: Summary generation job failed: %s", str(e), exc_info=True)
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            self.db.commit()
            raise e

    def stream_summary_generator(
        self,
        case_id: uuid.UUID,
        summary_type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """Provides SSE token streaming and saves completed result in version records."""
        context = self.context_builder.build_context(case_id, summary_type)
        plan = SummaryPlanner.plan(summary_type, context)
        
        target_provider = provider or "mock"
        target_model = model or "mock-model"

        start_time = datetime.now()
        full_text = ""
        
        try:
            stream_gen = self.llm_service.stream_answer(
                prompt=plan["user_prompt"],
                system_prompt=plan["system_prompt"],
                provider=target_provider,
                model=target_model
            )
            
            for chunk in stream_gen:
                tok = chunk.get("content", "")
                full_text += tok
                yield {"event": "token", "data": tok}
                
        except Exception as e:
            logger.error("SummaryService: Streaming failed: %s", str(e))
            yield {"event": "error", "data": str(e)}
            return

        # Successfully streamed. Save to DB cache
        try:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000.0
            citations = self._parse_citations(full_text)

            summary = self.db.query(Summary).filter(
                and_(Summary.case_id == case_id, Summary.summary_type == summary_type)
            ).first()

            if not summary:
                summary = Summary(case_id=case_id, summary_type=summary_type)
                self.db.add(summary)
                self.db.flush()

            next_ver_num = len(summary.versions) + 1
            for v in summary.versions:
                v.is_active = False

            token_usage = {
                "prompt_tokens": len(plan["user_prompt"].split()),
                "completion_tokens": len(full_text.split()),
                "latency_ms": duration_ms
            }

            version = SummaryVersion(
                summary_id=summary.id,
                version=next_ver_num,
                summary_text=full_text,
                provider=target_provider,
                model_used=target_model,
                prompt_version=plan["prompt_version"],
                token_usage_json=json.dumps(token_usage),
                is_active=True
            )
            self.db.add(version)
            self.db.flush()

            for cit in citations:
                cit_record = SummaryCitation(
                    summary_version_id=version.id,
                    citation_type=cit["type"],
                    source_id=cit["id"],
                    source_title=cit["title"],
                    citation_text=cit["text"]
                )
                self.db.add(cit_record)

            self.db.commit()
            self.cache_manager.cache_version(case_id, summary_type, version.id)
            
            yield {"event": "done", "data": json.dumps({"version_id": str(version.id)})}
        except Exception as se:
            logger.error("SummaryService: failed to save streamed output: %s", se)

    def _parse_citations(self, text: str) -> List[Dict[str, Any]]:
        """Scans the text using regex to resolve Fact, TimelineEvent, or Entity citation references."""
        pattern = r"\[(Fact|TimelineEvent|Entity|Document|Chunk|Statute|Claim|Evidence):\s*([a-f0-9\-]{36})\]"
        citations = []
        
        for match in re.finditer(pattern, text, re.IGNORECASE):
            ctype = match.group(1).lower()
            source_uuid = uuid.UUID(match.group(2))
            
            # Resolve titles based on target category tables
            title = "Reference Source"
            citation_text = ""
            try:
                if ctype == "fact":
                    fact = self.db.get(LegalFact, source_uuid)
                    if fact:
                        title = "Legal Fact"
                        citation_text = fact.fact_text
                elif ctype == "timelineevent":
                    evt = self.db.get(TimelineEvent, source_uuid)
                    if evt:
                        title = evt.title
                        citation_text = evt.description or ""
                elif ctype == "entity":
                    ent = self.db.get(LegalEntity, source_uuid)
                    if ent:
                        title = ent.name
                        citation_text = f"Entity role: {ent.role or 'N/A'}"
                elif ctype == "statute":
                    st = self.db.get(ActStatute, source_uuid)
                    if st:
                        title = st.normalized_reference
                elif ctype == "claim":
                    cl = self.db.get(ClaimDefense, source_uuid)
                    if cl:
                        title = "Claim Statement"
                        citation_text = cl.statement
                elif ctype == "evidence":
                    ev = self.db.get(LegalEvidence, source_uuid)
                    if ev:
                        title = f"Evidence Exhibit: {ev.evidence_type}"
                        citation_text = ev.description
            except Exception:
                pass

            citations.append({
                "type": ctype,
                "id": source_uuid,
                "title": title,
                "text": citation_text
            })
            
        return citations
