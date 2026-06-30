"""
app.document_processing.cleaning.strategies.footers — Footer removal strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple, List
from collections import Counter
from app.document_processing.cleaning.cleaner import CleaningStrategy


class FooterRemovalStrategy(CleaningStrategy):
    """
    Detects and strips repeating footers across page boundaries (e.g., Confidential,
    Company/Court Footers, or repeated signatures) while preserving body text.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        # 1. Split text into pages based on page markers
        page_pattern = r"(--- Page \d+ ---)"
        parts = re.split(page_pattern, text)

        # If there are no page markers (or only 1 page), we cannot detect repeating footers
        if len(parts) <= 2:
            return text, context

        pages: List[Dict[str, str]] = []
        leading = parts[0].strip()
        if leading:
            pages.append({"marker": "", "content": parts[0]})

        for i in range(1, len(parts), 2):
            marker = parts[i]
            content = parts[i + 1] if i + 1 < len(parts) else ""
            pages.append({"marker": marker, "content": content})

        total_pages = len([p for p in pages if p["marker"]])
        if total_pages < 2:
            return text, context

        # 2. Extract last few non-empty lines from each page to find repeating patterns
        bottom_lines_by_page = []
        all_footer_candidate_lines = []

        for p in pages:
            if not p["marker"]:
                continue
            
            # Get last 3 non-empty lines of page content
            lines = [line.strip() for line in p["content"].split("\n") if line.strip()]
            bottom_lines = lines[-3:]
            bottom_lines_by_page.append(bottom_lines)
            all_footer_candidate_lines.extend(bottom_lines)

        # Count occurrences of footer candidate lines
        line_counts = Counter(all_footer_candidate_lines)

        # Define thresholds for repeating footers
        # Must appear on at least 30% of pages and be at least 5 characters long
        threshold = max(2, int(total_pages * 0.3))
        repeating_footers = {
            line for line, count in line_counts.items()
            if count >= threshold and len(line) >= 5
        }

        if not repeating_footers:
            return text, context

        # 3. Clean pages by removing the repeating footer lines from the bottom section
        footers_removed_count = 0
        cleaned_parts = []

        # If there was leading text before first page marker, add it back
        if pages and not pages[0]["marker"]:
            cleaned_parts.append(pages[0]["content"])
            pages = pages[1:]

        for p in pages:
            lines = p["content"].split("\n")
            cleaned_lines = []
            
            # Reverse lines to check bottom lines first
            reversed_lines = list(reversed(lines))
            non_empty_seen = 0
            
            for line in reversed_lines:
                stripped = line.strip()
                if stripped:
                    non_empty_seen += 1
                    if non_empty_seen <= 4 and stripped in repeating_footers:
                        # Drop repeating footer line
                        footers_removed_count += 1
                        continue
                cleaned_lines.append(line)

            # Restore original order of lines
            p_content = "\n".join(reversed(cleaned_lines))
            cleaned_parts.append(p["marker"])
            cleaned_parts.append(p_content)

        context["footers_removed"] = context.get("footers_removed", 0) + footers_removed_count

        return "".join(cleaned_parts), context
