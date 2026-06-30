"""
app.document_processing.chunking.utils — Utility helpers for tracking character, paragraph, page, and token counts.
"""

import re
from typing import List, Tuple, Dict, Any


def parse_page_offsets(text: str) -> List[Tuple[int, int]]:
    """
    Parses page marker offsets from the text.
    Returns:
        List of tuples: (character_start_offset, page_number)
    """
    pattern = re.compile(r"--- Page (\d+) ---")
    offsets = []
    for match in pattern.finditer(text):
        offsets.append((match.start(), int(match.group(1))))
    # Always guarantee at least one default offset if none found
    if not offsets:
        offsets.append((0, 1))
    return offsets


def get_page_range(char_start: int, char_end: int, page_offsets: List[Tuple[int, int]]) -> Tuple[int, int]:
    """
    Determines the start and end page for a given character span.
    """
    if not page_offsets:
        return (1, 1)

    start_page = page_offsets[0][1]
    end_page = page_offsets[0][1]

    # Find the page for char_start
    for offset, page_num in page_offsets:
        if char_start >= offset:
            start_page = page_num
        else:
            break

    # Find the page for char_end
    for offset, page_num in page_offsets:
        if char_end >= offset:
            end_page = page_num
        else:
            break

    return (start_page, max(start_page, end_page))


def parse_paragraph_offsets(text: str) -> List[Tuple[int, int]]:
    """
    Identifies paragraph boundaries.
    Paragraphs are separated by double newlines (\n\n).
    Returns:
        List of tuples: (character_start_offset, paragraph_index)
    """
    # Split by \n\n but find their positions
    paragraph_starts = [0]
    idx = 1
    for match in re.finditer(r"\n\n", text):
        paragraph_starts.append(match.end())
    
    return [(offset, idx) for idx, offset in enumerate(paragraph_starts, start=1)]


def get_paragraph_range(char_start: int, char_end: int, paragraph_offsets: List[Tuple[int, int]]) -> Tuple[int, int]:
    """
    Determines the paragraph index range for a given character span.
    """
    if not paragraph_offsets:
        return (1, 1)

    start_para = paragraph_offsets[0][1]
    end_para = paragraph_offsets[0][1]

    for offset, para_idx in paragraph_offsets:
        if char_start >= offset:
            start_para = para_idx
        else:
            break

    for offset, para_idx in paragraph_offsets:
        if char_end >= offset:
            end_para = para_idx
        else:
            break

    return (start_para, max(start_para, end_para))


def estimate_tokens(text: str) -> int:
    """
    Estimates token count using standard word multiplier.
    1 word = ~1.33 tokens.
    """
    word_count = len(text.split())
    return max(int(word_count * 1.33), 1)


def split_into_sentences(text: str) -> List[str]:
    """
    Splits text into sentences helper.
    Uses standard regex boundary markers (e.g. '.', '?', '!') followed by space/newlines,
    taking care of common legal abbreviations (e.g., vs., v., Co., Ltd., Corp., Art., Sec.).
    """
    # Simple abbreviations lookbehind/lookahead to prevent splitting inside sentences
    # e.g., "v. State" shouldn't split after "v."
    sentence_end = re.compile(
        r"(?<!\bvs)(?<!\bv)(?<!\bCo)(?<!\bLtd)(?<!\bCorp)(?<!\bArt)(?<!\bSec)(?<!\bNo)(?<!\bJan)(?<!\bFeb)(?<!\bMar)(?<!\bApr)(?<!\bJun)(?<!\bJul)(?<!\bAug)(?<!\bSep)(?<!\bOct)(?<!\bNov)(?<!\bDec)(?<=[.!?])\s+"
    )
    sentences = sentence_end.split(text)
    return [s.strip() for s in sentences if s.strip()]
