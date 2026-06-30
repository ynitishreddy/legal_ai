"""
app.document_processing.cleaning.strategies.page_numbers — Page number removal strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple, List
from app.document_processing.cleaning.cleaner import CleaningStrategy


class PageNumberRemovalStrategy(CleaningStrategy):
    """
    Detects and strips standard page numbers (e.g. Page 1, Pg. 4, 1 of 35, - 12 -)
    restricted to the top/bottom page lines to prevent corrupting numbering inside paragraph bodies.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        # Split text into pages based on page markers
        page_pattern = r"(--- Page \d+ ---)"
        parts = re.split(page_pattern, text)

        # List of regexes for page numbering
        page_regexes = [
            r"^page\s+\d+$",
            r"^\d+\s+of\s+\d+$",
            r"^pg\.\s+\d+$",
            r"^-\s*\d+\s*-$",
            r"^\d+\s*-$",
            r"^\[\s*\d+\s*\]$",
            r"^\d+$",  # single isolated digit
        ]

        # Precompile patterns
        patterns = [re.compile(p, re.IGNORECASE) for p in page_regexes]

        def is_page_number(line: str) -> bool:
            stripped = line.strip()
            if not stripped:
                return False
            return any(pattern.match(stripped) for pattern in patterns)

        pages_removed_count = 0
        cleaned_parts = []

        # Reconstruct pages and process top/bottom lines
        i = 0
        while i < len(parts):
            part = parts[i]
            if re.match(page_pattern, part):
                cleaned_parts.append(part)
                i += 1
                continue
            
            # This is page text
            lines = part.split("\n")
            if len(lines) <= 1:
                cleaned_parts.append(part)
                i += 1
                continue

            cleaned_lines = list(lines)
            
            # Check the first 4 non-empty lines for page numbers
            non_empty_indices = [idx for idx, line in enumerate(lines) if line.strip()]
            
            # Check top 3 lines
            for idx in non_empty_indices[:3]:
                if is_page_number(lines[idx]):
                    cleaned_lines[idx] = ""  # blank out line
                    pages_removed_count += 1

            # Check bottom 3 lines
            for idx in non_empty_indices[-3:]:
                if is_page_number(lines[idx]):
                    cleaned_lines[idx] = ""  # blank out line
                    pages_removed_count += 1

            cleaned_parts.append("\n".join(cleaned_lines))
            i += 1

        context["page_numbers_removed"] = context.get("page_numbers_removed", 0) + pages_removed_count

        return "".join(cleaned_parts), context
