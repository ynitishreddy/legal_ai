"""
app.document_processing.chunking.strategies.legal_chunker — Legal section-aware chunking strategy.
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


class LegalSectionChunkingStrategy(ChunkingStrategy):
    """
    Intelligent rule-based Legal Section Chunker.
    Identifies major phases of standard litigation documents (Facts, Issues, Orders, etc.)
    using regex matches and splits text accordingly.
    """

    # Section keyword mappings
    LEGAL_PATTERNS = {
        "Facts": re.compile(r"^(?:factual background|facts of the case|background facts|relevant facts|facts)$", re.IGNORECASE),
        "Issues": re.compile(r"^(?:issues? for consideration|points? for determination|questions? of law|issues?)$", re.IGNORECASE),
        "Arguments": re.compile(r"^(?:arguments?|submissions?|rival contentions|contention of parties)$", re.IGNORECASE),
        "Findings": re.compile(r"^(?:findings?|discussion|reasoning|deliberations|our analysis|consideration)$", re.IGNORECASE),
        "Orders": re.compile(r"^(?:orders?|decree|operative part|concluding directions?|directions)$", re.IGNORECASE),
        "Relief": re.compile(r"^(?:relief sought|prayer|relief granted)$", re.IGNORECASE),
        "Evidence": re.compile(r"^(?:evidence on record|depositions|documentary evidence|evidence)$", re.IGNORECASE),
        "Witness Statements": re.compile(r"^(?:witness statements?|testimony|cross-examination)$", re.IGNORECASE),
        "FIR": re.compile(r"^(?:first information report|f\.i\.r\.?|fir)$", re.IGNORECASE),
        "Affidavit": re.compile(r"^(?:affidavits?|solemn affirmation)$", re.IGNORECASE),
        "Judgment": re.compile(r"^(?:judgment|concluding opinion|final order)$", re.IGNORECASE),
    }

    def can_handle(self, doc_category: str) -> bool:
        # Applies specifically to legal documents
        return doc_category in ["judgment", "brief", "pleading", "order", "pdf", "docx"]

    def chunk(self, text: str, config: ChunkingConfig) -> List[ChunkResult]:
        page_offsets = parse_page_offsets(text)
        paragraph_offsets = parse_paragraph_offsets(text)

        lines = text.split("\n")
        sections: List[Tuple[str, int, List[str]]] = []  # List of (section_type, start_line_idx, lines)
        
        current_section = "Introductory Context"
        current_lines = []
        current_start_line = 0

        for idx, line in enumerate(lines):
            line_strip = line.strip()
            if not line_strip:
                current_lines.append(line)
                continue

            # Strip section numbers if present (e.g. "1. Facts of the case" -> "Facts of the case")
            clean_line = re.sub(r'^(?:[0-9]+\.|[A-Z]+\.|I+V*X*\.)\s+', '', line_strip, flags=re.IGNORECASE).strip()
            
            # Check if this line matches any legal section keywords
            matched_section = None
            for sec_name, pattern in self.LEGAL_PATTERNS.items():
                if pattern.match(clean_line):
                    matched_section = sec_name
                    break

            if matched_section:
                if current_lines:
                    sections.append((current_section, current_start_line, current_lines))
                current_section = matched_section
                current_lines = [line]
                current_start_line = idx
            else:
                current_lines.append(line)

        # Flush final section
        if current_lines:
            sections.append((current_section, current_start_line, current_lines))

        chunks: List[ChunkResult] = []

        # Process each section identically to heading chunker
        for section_title, start_line_idx, section_lines in sections:
            section_text = "\n".join(section_lines).strip()
            if not section_text:
                continue

            section_start_offset = text.find(section_text)
            if section_start_offset == -1:
                section_start_offset = 0
            section_end_offset = section_start_offset + len(section_text)

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
                        section_title=section_title,
                        word_count=sect_words,
                        character_count=sect_len,
                        estimated_tokens=estimate_tokens(section_text),
                    )
                )
            else:
                # Split large section
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
                                    section_title=section_title,
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
                            section_title=section_title,
                            word_count=len(sub_text.split()),
                            character_count=len(sub_text),
                            estimated_tokens=estimate_tokens(sub_text),
                        )
                    )

        return chunks
