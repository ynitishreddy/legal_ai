"""
app.document_processing.chunking.pipeline — Chunking pipeline orchestrator.
"""

import logging
from typing import List, Tuple, Dict, Any, Optional

from app.document_processing.chunking.schemas import ChunkingConfig, ChunkResult
from app.document_processing.chunking.strategies.base import ChunkingStrategy
from app.document_processing.chunking.strategies.paragraph_chunker import ParagraphChunkingStrategy
from app.document_processing.chunking.strategies.sliding_window_chunker import SlidingWindowChunkingStrategy
from app.document_processing.chunking.strategies.heading_chunker import HeadingAwareChunkingStrategy
from app.document_processing.chunking.strategies.legal_chunker import LegalSectionChunkingStrategy
from app.document_processing.chunking.validator import validate_chunks
from app.document_processing.chunking.exceptions import StrategyNotFoundError

logger = logging.getLogger(__name__)


class DocumentChunkingPipeline:
    """
    Coordinates document text chunking.
    Selects suitable chunking strategies, coordinates boundaries, sets overlaps,
    runs validations, and returns trace-ready chunk objects.
    """

    CHUNKING_VERSION = "1.0.0"

    def __init__(self) -> None:
        # Register strategies in order of preference
        self.strategies: List[ChunkingStrategy] = [
            LegalSectionChunkingStrategy(),
            HeadingAwareChunkingStrategy(),
            SlidingWindowChunkingStrategy(),
            ParagraphChunkingStrategy(),  # Default fallback
        ]

    def select_strategy(self, doc_category: str, requested_strategy: Optional[str] = None) -> ChunkingStrategy:
        """
        Selects a chunking strategy based on request overrides or category match.
        """
        if requested_strategy:
            normalized = requested_strategy.lower().replace("_", "").replace("strategy", "")
            for s in self.strategies:
                s_name = s.__class__.__name__.lower()
                if normalized in s_name:
                    logger.info("Using requested chunking strategy: %s", s.__class__.__name__)
                    return s

        # Auto-detect best match
        for s in self.strategies:
            if s.can_handle(doc_category):
                logger.info("Selected auto-detected chunking strategy: %s", s.__class__.__name__)
                return s

        raise StrategyNotFoundError(f"No chunking strategy found for category {doc_category}.")

    def generate_chunks(
        self,
        text: str,
        doc_category: str,
        config: Optional[ChunkingConfig] = None,
        requested_strategy: Optional[str] = None
    ) -> Tuple[List[ChunkResult], Dict[str, Any], str]:
        """
        Runs the chunking pipeline.
        Returns:
            Tuple of (list_of_ChunkResult, report_metadata, strategy_name)
        """
        if not config:
            config = ChunkingConfig()

        logger.info("Starting chunking pipeline for doc_category: %s", doc_category)

        # 1. Select strategy
        strategy = self.select_strategy(doc_category, requested_strategy)
        strategy_name = strategy.__class__.__name__

        # 2. Split text
        chunks = strategy.chunk(text, config)

        # 3. Validate results
        validate_chunks(chunks, config)

        # 4. Generate metadata report
        total_chunks = len(chunks)
        char_lens = [c.character_count for c in chunks]
        word_counts = [c.word_count for c in chunks]
        token_estimates = [c.estimated_tokens for c in chunks]

        report = {
            "total_chunks": total_chunks,
            "average_chunk_size": sum(char_lens) / total_chunks if total_chunks > 0 else 0,
            "largest_chunk": max(char_lens) if total_chunks > 0 else 0,
            "smallest_chunk": min(char_lens) if total_chunks > 0 else 0,
            "average_words": sum(word_counts) / total_chunks if total_chunks > 0 else 0,
            "estimated_tokens": sum(token_estimates),
            "strategy_used": strategy_name,
            "chunking_version": self.CHUNKING_VERSION,
        }

        return chunks, report, strategy_name


# Singleton pipeline instance
document_chunking_pipeline = DocumentChunkingPipeline()
