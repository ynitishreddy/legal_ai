"""
app.document_processing.chunking.strategies.heading_chunker — Heading-aware chunking strategy.
"""

import re
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


class HeadingAwareChunkingStrategy(ChunkingStrategy):
    """
    Heading-aware chunking strategy.
    Detects markdown headings or CAPITALized section labels, grouping paragraphs under sections.
    """

    # Headings match markdown # or lines with 3+ capitals and no final period (e.g. "I. INTRODUCTORY FACTS")
    HEADING_REGEX = re.compile(
        r"^(?:#{1,6}\s+(.+))$|^([A-Z0-9\s\.\-\:]{4,70})$"
    )

    def can_handle(self, doc_category: str) -> bool:
        # Suitable for general litigation documents and briefs
        return doc_category in ["judgment", "brief", "pleading", "order", "pdf", "docx"]

    def chunk(self, text: str, config: ChunkingConfig) -> List[ChunkResult]:
        page_offsets = parse_page_offsets(text)
        paragraph_offsets = parse_paragraph_offsets(text)

        lines = text.split("\n")
        sections: List[Tuple[str, int, List[str]]] = []  # List of (heading_title, start_line_idx, line_contents)
        
        current_heading = "Introduction"
        current_lines = []
        current_start_line = 0

        for idx, line in enumerate(lines):
            line_strip = line.strip()
            if not line_strip:
                current_lines.append(line)
                continue

            # Check if this line is a heading
            match = self.HEADING_REGEX.match(line_strip)
            # Filter out lines that look like numbers or short phrases with lowercase letters
            is_heading = False
            heading_text = line_strip
            
            if match:
                # If it's a markdown header or only capitals/symbols without ending in dot
                if match.group(1):  # markdown
                    is_heading = True
                    heading_text = match.group(1).strip()
                elif match.group(2) and not line_strip.endswith(".") and len(re.sub(r'[^A-Z]', '', line_strip)) > 3:
                    is_heading = True
                    heading_text = match.group(2).strip()

            if is_heading:
                # Flush the previous section
                if current_lines:
                    sections.append((current_heading, current_start_line, current_lines))
                current_heading = heading_text
                current_lines = [line]
                current_start_line = idx
            else:
                current_lines.append(line)

        # Flush the final section
        if current_lines:
            sections.append((current_heading, current_start_line, current_lines))

        chunks: List[ChunkResult] = []

        # Now, process each section
        for heading_title, start_line_idx, section_lines in sections:
            section_text = "\n".join(section_lines).strip()
            if not section_text:
                continue

            # Find section offset in original text
            # We can reconstruct it or search
            section_start_offset = text.find(section_text)
            if section_start_offset == -1:
                section_start_offset = 0
            section_end_offset = section_start_offset + len(section_text)

            # If the entire section is small enough, make it a single chunk
            sect_len = len(section_text)
            sect_words = len(section_text.split())
            
            if sect_len <= config.max_characters and sect_words <= config.max_words:
                page_start, page_end = get_page_range(section_start_offset, section_end_offset, page_offsets)
                para_start, para_end = get_paragraph_range(section_start_offset, section_end_offset, paragraph_offsets)
                
                chunks.append(
                    ChunkResult(
                        text=section_text,
                        page_start=page_start,
                        page_end=page_end,
                        paragraph_start=para_start,
                        paragraph_end=para_end,
                        section_title=heading_title,
                        word_count=sect_words,
                        character_count=sect_len,
                        estimated_tokens=estimate_tokens(section_text),
                    )
                )
            else:
                # Section is too large; split it using sentence boundary preservation
                sentences = split_into_sentences(section_text)
                sub_text = ""
                sub_start_offset = section_start_offset

                for s in sentences:
                    s_strip = s.strip()
                    s_pos = section_text.find(s_strip)
                    s_global_offset = section_start_offset + (s_pos if s_pos != -1 else 0)

                    temp_text = (sub_text + " " + s_strip).strip()
                    temp_words = len(temp_text.split())
                    temp_tokens = estimate_tokens(temp_text)

                    if len(temp_text) > config.max_characters or temp_words > config.max_words or temp_tokens > config.estimated_tokens:
                        if sub_text:
                            page_start, page_end = get_page_range(sub_start_offset, s_global_offset, page_offsets)
                            para_start, para_end = get_paragraph_range(sub_start_offset, s_global_offset, paragraph_offsets)
                            
                            chunks.append(
                                ChunkResult(
                                    text=sub_text,
                                    page_start=page_start,
                                    page_end=page_end,
                                    paragraph_start=para_start,
                                    paragraph_end=para_end,
                                    section_title=heading_title,
                                    word_count=len(sub_text.split()),
                                    character_count=len(sub_text),
                                    estimated_tokens=estimate_tokens(sub_text),
                                )
                            )
                        sub_text = s_strip
                        sub_start_offset = s_global_offset
                    else:
                        sub_text = temp_text

                if sub_text:
                    page_start, page_end = get_page_range(sub_start_offset, section_end_offset, page_offsets)
                    para_start, para_end = get_paragraph_range(sub_start_offset, section_end_offset, paragraph_offsets)
                    
                    chunks.append(
                        ChunkResult(
                            text=sub_text,
                            page_start=page_start,
                            page_end=page_end,
                            paragraph_start=para_start,
                            paragraph_end=para_end,
                            section_title=heading_title,
                            word_count=len(sub_text.split()),
                            character_count=len(sub_text),
                            estimated_tokens=estimate_tokens(sub_text),
                        )
                    )

        return chunks
