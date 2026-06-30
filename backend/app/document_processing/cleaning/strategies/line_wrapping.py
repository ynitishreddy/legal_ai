"""
app.document_processing.cleaning.strategies.line_wrapping — Line wrapping repair strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple, List
from app.document_processing.cleaning.cleaner import CleaningStrategy


class LineWrappingRepairStrategy(CleaningStrategy):
    """
    Merges wrapped lines into continuous paragraphs.
    Preserves lists, headings, and legal section numbering.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        # Split text into page segments first, to avoid merging lines across page boundary markers
        page_pattern = r"(--- Page \d+ ---)"
        parts = re.split(page_pattern, text)

        cleaned_parts = []
        for part in parts:
            if re.match(page_pattern, part):
                cleaned_parts.append(part)
                continue
            
            cleaned_parts.append(self._repair_paragraph_wrapping(part))

        return "".join(cleaned_parts), context

    def _repair_paragraph_wrapping(self, text: str) -> str:
        # Split text by double newlines to isolate paragraphs
        paragraphs = text.split("\n\n")
        reconstructed_paragraphs = []

        # List markers: bullet points, (a), (1), (i), 1., a.
        list_marker_pattern = re.compile(
            r"^(\s*[-•\*#]\s+|\s*\(\s*[a-zA-Z0-9]+\s*\)\s+|\s*[a-zA-Z0-9]+\s*[\.\)]\s+)",
            re.UNICODE
        )

        # Legal header markers: Section 1, Article II, Versus, Vs, Court name
        legal_header_pattern = re.compile(
            r"^(\s*(section|article|order|rule|chapter|part|schedule|paragraph|court|vs\.?|versus|plaintiff|defendant|appellant|respondent)\b)",
            re.IGNORECASE
        )

        for paragraph in paragraphs:
            if not paragraph.strip():
                reconstructed_paragraphs.append(paragraph)
                continue

            lines = paragraph.split("\n")
            if len(lines) <= 1:
                reconstructed_paragraphs.append(paragraph)
                continue

            reconstructed_lines: List[str] = [lines[0]]
            
            for line_idx in range(1, len(lines)):
                prev_line = reconstructed_lines[-1]
                curr_line = lines[line_idx]
                
                stripped_prev = prev_line.strip()
                stripped_curr = curr_line.strip()

                if not stripped_curr:
                    reconstructed_lines.append(curr_line)
                    continue

                if not stripped_prev:
                    reconstructed_lines[-1] = curr_line
                    continue

                # 1. Decide if we should NOT merge:
                # - Current line is a list item
                # - Current line is a legal header or section number
                # - Current line is in all-caps (indicates a section heading)
                # - Previous line ends with a colon ":" or starts a quote block
                is_list_item = bool(list_marker_pattern.match(curr_line))
                is_legal_header = bool(legal_header_pattern.match(curr_line))
                is_all_caps_heading = stripped_curr.isupper() and len(stripped_curr) > 3
                
                ends_with_colon = stripped_prev.endswith(":")
                
                if is_list_item or is_legal_header or is_all_caps_heading or ends_with_colon:
                    # Keep as separate line
                    reconstructed_lines.append(curr_line)
                    continue

                # 2. Merge condition:
                # - Previous line doesn't end with standard sentence end punctuation (. ! ?)
                # - Or current line starts with a lowercase letter
                ends_with_sentence_punc = stripped_prev[-1] in (".", "?", "!")
                starts_with_lowercase = stripped_curr[0].islower() if stripped_curr else False

                if not ends_with_sentence_punc or starts_with_lowercase:
                    # Merge lines together with a space
                    reconstructed_lines[-1] = f"{prev_line} {stripped_curr}"
                else:
                    # Separate line
                    reconstructed_lines.append(curr_line)

            reconstructed_paragraphs.append("\n".join(reconstructed_lines))

        return "\n\n".join(reconstructed_paragraphs)
