"""
app.document_processing.chunking.strategies.sliding_window_chunker — Sliding window chunking strategy.
"""

from typing import List, Tuple
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


class SlidingWindowChunkingStrategy(ChunkingStrategy):
    """
    Sliding window chunking strategy.
    Preserves sentence boundaries by grouping sentences and backtracking
    to create overlaps of approximately `overlap_size` words.
    """

    def can_handle(self, doc_category: str) -> bool:
        # Standard utility chunker
        return True

    def chunk(self, text: str, config: ChunkingConfig) -> List[ChunkResult]:
        page_offsets = parse_page_offsets(text)
        paragraph_offsets = parse_paragraph_offsets(text)

        # 1. Parse sentences and find their character bounds
        sentences_raw = split_into_sentences(text)
        sentences: List[Tuple[str, int, int]] = []
        
        char_cursor = 0
        for s in sentences_raw:
            s_strip = s.strip()
            if not s_strip:
                continue
            
            s_start = text.find(s_strip, char_cursor)
            if s_start == -1:
                s_start = char_cursor
            
            s_end = s_start + len(s_strip)
            sentences.append((s_strip, s_start, s_end))
            char_cursor = s_end

        if not sentences:
            return []

        chunks: List[ChunkResult] = []
        i = 0
        n = len(sentences)

        while i < n:
            window_sentences = []
            window_words = 0
            window_chars = 0
            
            # Start of the current chunk
            chunk_start_idx = i
            chunk_start_offset = sentences[i][1]
            chunk_end_offset = sentences[i][2]

            # Add sentences to the window until we reach limits
            while i < n:
                s_text, s_start, s_end = sentences[i]
                s_words = len(s_text.split())
                
                # Check limits
                if (window_words + s_words > config.max_words or 
                    window_chars + len(s_text) > config.max_characters or
                    estimate_tokens(s_text) + estimate_tokens(" ".join(window_sentences)) > config.estimated_tokens):
                    
                    # If this is the very first sentence, we must add it to avoid infinite loops/empty chunks
                    if not window_sentences:
                        window_sentences.append(s_text)
                        chunk_end_offset = s_end
                        i += 1
                    break
                
                window_sentences.append(s_text)
                chunk_end_offset = s_end
                window_words += s_words
                window_chars += len(s_text)
                i += 1

            # Commit the chunk
            chunk_text = " ".join(window_sentences)
            
            page_start, page_end = get_page_range(chunk_start_offset, chunk_end_offset, page_offsets)
            para_start, para_end = get_paragraph_range(chunk_start_offset, chunk_end_offset, paragraph_offsets)

            chunks.append(
                ChunkResult(
                    text=chunk_text,
                    page_start=page_start,
                    page_end=page_end,
                    paragraph_start=para_start,
                    paragraph_end=para_end,
                    section_title=None,
                    word_count=len(chunk_text.split()),
                    character_count=len(chunk_text),
                    estimated_tokens=estimate_tokens(chunk_text),
                )
            )

            # If we've processed all sentences, we are done
            if i >= n:
                break

            # 2. Determine backtracking step for overlap
            overlap_words = 0
            backtrack_index = i - 1
            
            while backtrack_index > chunk_start_idx:
                s_text = sentences[backtrack_index][0]
                s_words = len(s_text.split())
                if overlap_words + s_words <= config.overlap_size:
                    overlap_words += s_words
                    backtrack_index -= 1
                else:
                    break
            
            # The next chunk starts at the backtrack_index + 1
            # Ensure we make forward progress by checking:
            next_start_idx = backtrack_index + 1
            if next_start_idx <= chunk_start_idx:
                next_start_idx = chunk_start_idx + 1
            
            i = next_start_idx

        return chunks
