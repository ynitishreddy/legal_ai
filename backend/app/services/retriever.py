import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, RetrievalLog
from app.document_processing.models import DocumentChunk
from app.services.embeddings import EmbeddingService
from app.services.qdrant import QdrantService

logger = logging.getLogger(__name__)


class RetrieverService:
    """
    Retriever Service Layer for semantic search, metadata filtering,
    duplicate suppression, combined ranking, and context window building.
    """
    # Thread-safe in-memory cache for query embeddings
    _embedding_cache: Dict[Tuple[str, str], List[float]] = {}
    _embedding_cache_lock = threading.Lock()

    # Thread-safe in-memory cache for retrieval runs
    _retrieval_cache: Dict[Tuple[str, str, int, float], List[Dict[str, Any]]] = {}
    _retrieval_cache_lock = threading.Lock()
    _stats = {
        "total_requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "failed_requests": 0,
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.embedding_svc = EmbeddingService()
        self.qdrant_svc = QdrantService()

    def embed_query(self, query_text: str) -> List[float]:
        """Generates query embedding using EmbeddingService, with thread-safe caching."""
        model_name = self.settings.embedding_model
        cache_key = (query_text.strip(), model_name)

        with self._embedding_cache_lock:
            if cache_key in self._embedding_cache:
                return self._embedding_cache[cache_key]

        # Generate embedding
        logger.debug("RetrieverService: Generating embedding for query: '%s'", query_text)
        embeddings = self.embedding_svc.embed_batch([query_text])
        if not embeddings or len(embeddings) == 0:
            raise ValueError("Failed to generate embedding for the query.")
        
        query_vector = embeddings[0]

        with self._embedding_cache_lock:
            # Enforce cache size limit (500 items)
            if len(self._embedding_cache) >= 500:
                self._embedding_cache.clear()
            self._embedding_cache[cache_key] = query_vector

        return query_vector

    def retrieve_semantic(
        self,
        user_id: UUID,
        query_text: str,
        filters: Dict[str, Any],
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves relevant legal chunks using Qdrant semantic similarity
        and resolves full texts and metadata from PostgreSQL.
        """
        start_time = time.time()
        self.__class__._stats["total_requests"] += 1

        # Resolve filters to standard flat dict
        filter_dict = {
            "case_id": filters.get("case_id"),
            "document_id": filters.get("document_id"),
            "owner_id": str(user_id),
            "document_type": filters.get("document_type"),
            "filename": filters.get("filename"),
            "tags": filters.get("tags"),
            "page_number": filters.get("page_number"),
            "section_title": filters.get("section_title"),
        }
        # Strip empty/None filters
        filter_dict = {k: v for k, v in filter_dict.items() if v is not None and v != ""}

        # Create retrieval cache key
        filter_tuple = tuple(sorted((k, str(v)) for k, v in filter_dict.items()))
        cache_key = (query_text.strip(), str(filter_tuple), top_k, score_threshold or 0.0)

        # Check retrieval cache
        with self._retrieval_cache_lock:
            if cache_key in self._retrieval_cache:
                self.__class__._stats["cache_hits"] += 1
                logger.info("RetrieverService: Retrieval cache HIT for query: '%s'", query_text)
                return self._retrieval_cache[cache_key]
            self.__class__._stats["cache_misses"] += 1

        try:
            # 1. Embed user query
            query_vector = self.embed_query(query_text)

            # 2. Search Qdrant (top_k * 2 to account for potential duplicates/Postgres misses)
            q_limit = top_k * 2
            qdrant_points = self.qdrant_svc.search_vectors(
                query_vector=query_vector,
                limit=q_limit,
                score_threshold=score_threshold,
                filter_dict=filter_dict,
            )

            if not qdrant_points:
                return []

            # 3. Pull chunks and documents from PostgreSQL to construct citations and texts
            chunk_ids = []
            chunk_scores = {}
            for p in qdrant_points:
                c_id_str = p["payload"].get("chunk_id")
                if c_id_str:
                    try:
                        c_id = UUID(c_id_str)
                        chunk_ids.append(c_id)
                        chunk_scores[c_id] = p["score"]
                    except ValueError:
                        pass

            if not chunk_ids:
                return []

            chunks = (
                self.db.query(DocumentChunk)
                .filter(DocumentChunk.id.in_(chunk_ids))
                .all()
            )
            chunk_map = {c.id: c for c in chunks}

            doc_ids = list(set(c.document_id for c in chunks))
            docs = (
                self.db.query(Document)
                .filter(Document.id.in_(doc_ids))
                .all()
            )
            doc_map = {d.id: d for d in docs}

            # 4. Construct ranked context records
            retrieved_items = []
            seen_chunks = set()

            for chunk_id in chunk_ids:
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)

                chunk = chunk_map.get(chunk_id)
                if not chunk:
                    continue

                doc = doc_map.get(chunk.document_id)
                if not doc:
                    continue

                score = chunk_scores.get(chunk_id, 0.0)
                # Normalize cosine score from [-1, 1] to [0, 1] if not already
                normalized_score = max(0.0, min(1.0, (score + 1.0) / 2.0))

                retrieved_items.append({
                    "chunk_id": str(chunk_id),
                    "document_id": str(doc.id),
                    "document_name": doc.title or doc.filename,
                    "case_id": str(doc.case_id) if doc.case_id else "",
                    "page_number": chunk.page_start,
                    "section_title": chunk.section_name or "",
                    "similarity_score": normalized_score,
                    "embedding_version": doc.embeddings[0].embedding_version if (hasattr(doc, "embeddings") and doc.embeddings) else "1.5",
                    "source_path": doc.file_path or doc.storage_path or f"uploads/{doc.filename}",
                    "text": chunk.chunk_text,
                    "chunk_index": chunk.chunk_index,
                })

            # 5. Apply ranking constraints & limit to top_k
            ranked_items = self.rank_chunks(retrieved_items)[:top_k]

            # Write retrieval log
            latency_ms = (time.time() - start_time) * 1000.0
            top_score = ranked_items[0]["similarity_score"] if ranked_items else 0.0

            log_entry = RetrievalLog(
                user_id=user_id,
                query_text=query_text,
                filters_json=json.dumps(filters),
                retrieved_documents_json=json.dumps([
                    {"document_id": item["document_id"], "document_name": item["document_name"], "score": item["similarity_score"]}
                    for item in ranked_items
                ]),
                latency_ms=latency_ms,
                top_score=top_score,
                chunks_returned=len(ranked_items),
            )
            self.db.add(log_entry)
            self.db.commit()

            # Cache retrieval results
            with self._retrieval_cache_lock:
                if len(self._retrieval_cache) >= 500:
                    self._retrieval_cache.clear()
                self._retrieval_cache[cache_key] = ranked_items

            return ranked_items

        except Exception as e:
            self.__class__._stats["failed_requests"] += 1
            logger.error("RetrieverService: Semantic retrieval failed: %s", str(e), exc_info=True)
            raise e

    def rank_chunks(
        self,
        chunks: List[Dict[str, Any]],
        scoring_weights: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ranks retrieved chunks using similarity score, page proximity,
        and section metadata weights. Exposes custom tuning parameters.
        """
        weights = scoring_weights or {
            "semantic_similarity": 1.0,
            "section_bonus": 0.05,
            "page_proximity_penalty": 0.01,
        }

        scored_chunks = []
        for c in chunks:
            base_score = c["similarity_score"]
            bonus = 0.0

            # Boost if chunk contains relevant section terms like "conclusion", "judgment", "summary"
            sect = (c["section_title"] or "").lower()
            if any(term in sect for term in ["summary", "conclusion", "holding", "order"]):
                bonus += weights.get("section_bonus", 0.05)

            # Proximity penalty: penalize very deep pages slightly to favor early pages/summaries
            page = c["page_number"] or 1
            penalty = (page - 1) * weights.get("page_proximity_penalty", 0.01)

            final_score = max(0.0, min(1.0, base_score + bonus - penalty))
            
            scored_chunks.append({
                **c,
                "ranking_score": final_score,
            })

        # Sort descending by custom ranking score
        return sorted(scored_chunks, key=lambda x: x["ranking_score"], reverse=True)

    def build_context_window(self, chunks: List[Dict[str, Any]], max_tokens: int = 4000) -> str:
        """
        Merges adjacent chunks from the same document to preserve paragraph integrity,
        sorts chronologically/topically, and respects token limits.
        """
        if not chunks:
            return ""

        # Group chunks by document and sort by chunk index
        from collections import defaultdict
        doc_chunks = defaultdict(list)
        for c in chunks:
            doc_chunks[c["document_id"]].append(c)

        for doc_id in doc_chunks:
            doc_chunks[doc_id].sort(key=lambda x: x["chunk_index"])

        assembled_chunks = []
        for doc_id, c_list in doc_chunks.items():
            doc_name = c_list[0]["document_name"]
            
            merged_list = []
            current_merged = None

            for c in c_list:
                if current_merged is None:
                    current_merged = {
                        "text": c["text"],
                        "start_index": c["chunk_index"],
                        "end_index": c["chunk_index"],
                        "page_number": c["page_number"],
                        "section_title": c["section_title"],
                    }
                # Check if contiguous (chunk indices are adjacent)
                elif c["chunk_index"] == current_merged["end_index"] + 1:
                    current_merged["text"] += "\n" + c["text"]
                    current_merged["end_index"] = c["chunk_index"]
                else:
                    merged_list.append(current_merged)
                    current_merged = {
                        "text": c["text"],
                        "start_index": c["chunk_index"],
                        "end_index": c["chunk_index"],
                        "page_number": c["page_number"],
                        "section_title": c["section_title"],
                    }
            if current_merged:
                merged_list.append(current_merged)

            assembled_chunks.append((doc_name, merged_list))

        # Format context window respecting token boundaries (4 tokens per word approximation)
        context_blocks = []
        token_count = 0

        for doc_name, merged_blocks in assembled_chunks:
            doc_header = f"--- SOURCE DOCUMENT: {doc_name} ---\n"
            doc_header_tokens = len(doc_header.split()) * 1.3
            
            if token_count + doc_header_tokens > max_tokens:
                break
            
            context_blocks.append(doc_header)
            token_count += doc_header_tokens

            for block in merged_blocks:
                section_lbl = f"[Section: {block['section_title']}, Page {block['page_number']}]\n"
                block_text = f"{section_lbl}{block['text']}\n\n"
                block_tokens = len(block_text.split()) * 1.3

                if token_count + block_tokens > max_tokens:
                    # Partial fit check
                    remaining_tokens = max_tokens - token_count
                    if remaining_tokens > 50:
                        words = block_text.split()
                        allowed_words = int(remaining_tokens / 1.3)
                        context_blocks.append(" ".join(words[:allowed_words]) + "... [Truncated due to token limit]\n\n")
                    break

                context_blocks.append(block_text)
                token_count += block_tokens

        return "".join(context_blocks)

    def get_statistics(self) -> Dict[str, Any]:
        """Calculates query request metrics, latencies, and cache details."""
        total_requests = self.db.query(func.count(RetrievalLog.id)).scalar() or 0
        avg_latency = self.db.query(func.avg(RetrievalLog.latency_ms)).scalar() or 0.0
        avg_score = self.db.query(func.avg(RetrievalLog.top_score)).scalar() or 0.0

        # Calculate cache hit ratio
        tot_queries = self._stats["total_requests"]
        hits = self._stats["cache_hits"]
        cache_hit_ratio = (hits / tot_queries) if tot_queries > 0 else 0.0

        # Most searched document matches
        logs = self.db.query(RetrievalLog.retrieved_documents_json).all()
        doc_counts = {}
        for (log_json,) in logs:
            if log_json:
                try:
                    docs_list = json.loads(log_json)
                    for d in docs_list:
                        d_name = d.get("document_name")
                        if d_name:
                            doc_counts[d_name] = doc_counts.get(d_name, 0) + 1
                except ValueError:
                    pass

        sorted_docs = sorted(doc_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_docs = [{"document_name": name, "searches": count} for name, count in sorted_docs]

        return {
            "total_requests": total_requests,
            "average_latency_ms": round(float(avg_latency), 2),
            "average_similarity_score": round(float(avg_score), 4),
            "cache_hit_ratio": round(cache_hit_ratio, 4),
            "failed_requests": self._stats["failed_requests"],
            "top_retrieved_documents": top_docs,
        }

    def clear_caches(self) -> None:
        """Clears query embedding and retrieval cache structures."""
        with self._embedding_cache_lock:
            self._embedding_cache.clear()
        with self._retrieval_cache_lock:
            self._retrieval_cache.clear()
        self._stats["cache_hits"] = 0
        self._stats["cache_misses"] = 0

    def delete_history_entry(self, entry_id: UUID, user_id: UUID) -> None:
        """Removes a single query log entry from database."""
        log = self.db.get(RetrievalLog, entry_id)
        if not log:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Query log entry {entry_id} not found."
            )
        if log.user_id != user_id:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied."
            )
        self.db.delete(log)
        self.db.commit()
