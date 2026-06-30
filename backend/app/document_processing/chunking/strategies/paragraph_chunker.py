"""
app.document_processing.chunking.strategies.paragraph_chunker — Paragraph chunking strategy.
"""

from typing import List
from app.document_processing.chunking.strategies.base import ChunkingStrategy
from app.document_processing.chunking.schemas import ChunkingConfig, ChunkResult
from app.document_processing.chunking.utils import (
    parse_page_offsets,
    get_page_range,
    parse_paragraph_offsets,
    get_paragraph_range,
    estimate_tokens,
    split_into_sentences,
)


class ParagraphChunkingStrategy(ChunkingStrategy):
    """
    Default paragraph-based chunker.
    Combines sequential paragraphs into chunks without exceeding limit boundaries.
    Splits extra-large paragraphs using sentence-aware subdivisions.
    """

    def can_handle(self, doc_category: str) -> bool:
        # Default fallback strategy for all categories
        return True

    def chunk(self, text: str, config: ChunkingConfig) -> List[ChunkResult]:
        page_offsets = parse_page_offsets(text)
        paragraph_offsets = parse_paragraph_offsets(text)
        
        # Split full text into paragraphs
        paragraphs = text.split("\n\n")
        
        chunks: List[ChunkResult] = []
        current_paras = []
        current_text = ""
        current_start_offset = 0

        # We keep track of current character cursor relative to original text
        char_cursor = 0

        for p_idx, p in enumerate(paragraphs):
            p_strip = p.strip()
            if not p_strip:
                char_cursor += len(p) + 2  # account for "\n\n"
                continue

            p_len = len(p_strip)
            p_words = len(p_strip.split())
            p_tokens = estimate_tokens(p_strip)

            # Find paragraph start index in original text
            p_start_offset = text.find(p_strip, char_cursor)
            if p_start_offset == -1:
                p_start_offset = char_cursor

            # 1. If a single paragraph is too large, split it by sentences
            if p_len > config.max_characters or p_words > config.max_words:
                # First, flush any accumulated chunk
                if current_text:
                    self._add_chunk(
                        chunks, current_text, current_start_offset,
                        p_start_offset, page_offsets, paragraph_offsets
                    )
                    current_text = ""
                    current_paras = []

                # Now chunk this giant paragraph into sentence blocks
                sentences = split_into_sentences(p_strip)
                s_text = ""
                s_start_offset = p_start_offset

                for s in sentences:
                    s_strip = s.strip()
                    s_pos = p_strip.find(s_strip)
                    s_global_offset = p_start_offset + (s_pos if s_pos != -1 else 0)

                    temp_text = (s_text + " " + s_strip).strip()
                    temp_words = len(temp_text.split())
                    temp_tokens = estimate_tokens(temp_text)

                    if len(temp_text) > config.max_characters or temp_words > config.max_words or temp_tokens > config.estimated_tokens:
                        if s_text:
                            self._add_chunk(
                                chunks, s_text, s_start_offset,
                                s_global_offset, page_offsets, paragraph_offsets
                            )
                        s_text = s_strip
                        s_start_offset = s_global_offset
                    else:
                        s_text = temp_text

                if s_text:
                    self._add_chunk(
                        chunks, s_text, s_start_offset,
                        p_start_offset + p_len, page_offsets, paragraph_offsets
                    )
                
                char_cursor = p_start_offset + len(p) + 2
                continue

            # 2. Check if adding this paragraph exceeds limits
            temp_text = (current_text + "\n\n" + p_strip).strip()
            temp_words = len(temp_text.split())
            temp_tokens = estimate_tokens(temp_text)

            if len(temp_text) > config.max_characters or temp_words > config.max_words or temp_tokens > config.estimated_tokens:
                # Flush existing chunk
                if current_text:
                    self._add_chunk(
                        chunks, current_text, current_start_offset,
                        p_start_offset, page_offsets, paragraph_offsets
                    )
                # Start new chunk with current paragraph
                current_text = p_strip
                current_start_offset = p_start_offset
            else:
                if not current_text:
                    current_start_offset = p_start_offset
                current_text = temp_text

            char_cursor = p_start_offset + len(p) + 2

        # Flush any remaining text
        if current_text:
            self._add_chunk(
                chunks, current_text, current_start_offset,
                len(text), page_offsets, paragraph_offsets
            )

        return chunks

    def _add_chunk(
        self,
        chunks: List[ChunkResult],
        text: str,
        start_offset: int,
        end_offset: int,
        page_offsets: List,
        paragraph_offsets: List
    ) -> None:
        word_count = len(text.split())
        char_count = len(text)
        est_tokens = estimate_tokens(text)
        
        page_start, page_end = get_page_range(start_offset, end_offset, page_offsets)
        para_start, para_end = get_paragraph_range(start_offset, end_offset, paragraph_offsets)

        chunks.append(
            ChunkResult(
                text=text,
                page_start=page_start,
                page_end=page_end,
                paragraph_start=para_start,
                paragraph_end=para_end,
                section_title=None,
                word_count=word_count,
                character_count=char_count,
                estimated_tokens=est_tokens,
            )
        )
