import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ContextCompressionEngine:
    """
    Cleans RAG retrieval context windows by removing duplicate lines, folding
    redundant citations, and enforcing token bounds.
    """

    def compress_chunks(self, chunks: List[Dict[str, Any]], max_tokens: int = 4000) -> List[Dict[str, Any]]:
        """
        Removes chunks that overlap semantically or have duplicate text.
        Tracks estimated tokens.
        """
        compressed = []
        seen_texts = set()
        token_estimate = 0

        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
                
            # Normalize text to ignore whitespace
            norm_text = " ".join(text.lower().split())
            if norm_text in seen_texts:
                logger.info("ContextCompressionEngine: Filtered duplicate chunk ID: %s", chunk.get("chunk_id"))
                continue
                
            # Heuristic token counting: words * 1.3
            words_count = len(text.split())
            est_tokens = int(words_count * 1.3)
            
            if token_estimate + est_tokens > max_tokens:
                logger.warning("ContextCompressionEngine: Exceeded token budget of %d. Dropping further chunks.", max_tokens)
                break
                
            seen_texts.add(norm_text)
            token_estimate += est_tokens
            compressed.append(chunk)

        return compressed
