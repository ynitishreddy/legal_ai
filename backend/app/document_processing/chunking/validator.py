"""
app.document_processing.chunking.validator — Validates integrity and consistency of generated chunks.
"""

from typing import List
from app.document_processing.chunking.schemas import ChunkingConfig, ChunkResult
from app.document_processing.chunking.exceptions import ChunkingValidationError


def validate_chunks(chunks: List[ChunkResult], config: ChunkingConfig) -> None:
    """
    Validates all generated chunks against pipeline constraints.
    Raises ChunkingValidationError if any validation check fails.
    """
    if not chunks:
        raise ChunkingValidationError("Chunking process produced 0 chunks. Empty text or strategy failure.")

    prev_page_start = 0
    prev_para_start = 0

    for idx, chunk in enumerate(chunks):
        # 1. No empty chunks
        text = chunk.text.strip()
        if not text:
            raise ChunkingValidationError(f"Chunk at index {idx} has empty or blank text.")

        # 2. Length validations
        if len(text) < config.min_chunk_size:
            # Only fail if it's extremely small (less than 10 characters)
            if len(text) < 10:
                raise ChunkingValidationError(
                    f"Chunk at index {idx} is too small ({len(text)} characters). Minimum limit is {config.min_chunk_size}."
                )

        # Allow slight overshoot (1.5x) for sentence-preservation boundaries, but raise if excessively large
        if len(text) > config.max_characters * 1.5:
            raise ChunkingValidationError(
                f"Chunk at index {idx} exceeds maximum character limit. Length: {len(text)}, Limit: {config.max_characters}."
            )

        # 3. UTF-8 Validity
        try:
            # Check for surrogates which block proper UTF-8 database encoding
            text.encode("utf-8").decode("utf-8")
            if any(55296 <= ord(c) <= 57343 for c in text):
                raise ValueError("Contains surrogate characters.")
        except Exception as exc:
            raise ChunkingValidationError(f"Chunk at index {idx} contains invalid UTF-8/surrogate text: {exc}")

        # 4. Range consistency
        if chunk.page_start < 1 or chunk.page_end < 1:
            raise ChunkingValidationError(f"Chunk at index {idx} has invalid page indices: start={chunk.page_start}, end={chunk.page_end}")

        if chunk.page_start > chunk.page_end:
            raise ChunkingValidationError(f"Chunk at index {idx} has inverted page range: start={chunk.page_start}, end={chunk.page_end}")

        if chunk.paragraph_start < 1 or chunk.paragraph_end < 1:
            raise ChunkingValidationError(f"Chunk at index {idx} has invalid paragraph indices: start={chunk.paragraph_start}, end={chunk.paragraph_end}")

        if chunk.paragraph_start > chunk.paragraph_end:
            raise ChunkingValidationError(f"Chunk at index {idx} has inverted paragraph range: start={chunk.paragraph_start}, end={chunk.paragraph_end}")

        # 5. Ordering consistency
        if chunk.page_start < prev_page_start:
            raise ChunkingValidationError(
                f"Chunk at index {idx} violates page ordering consistency. Page start {chunk.page_start} is before previous chunk's start {prev_page_start}."
            )

        if chunk.paragraph_start < prev_para_start and chunk.page_start == prev_page_start:
            raise ChunkingValidationError(
                f"Chunk at index {idx} violates paragraph ordering consistency inside same page. Paragraph start {chunk.paragraph_start} is before previous {prev_para_start}."
            )

        prev_page_start = chunk.page_start
        prev_para_start = chunk.paragraph_start
