"""
app.document_processing.cleaning.strategies.headers — Header removal strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple, List
from collections import Counter
from app.document_processing.cleaning.cleaner import CleaningStrategy


class HeaderRemovalStrategy(CleaningStrategy):
    """
    Detects and strips repeating headers across page boundaries (e.g. Court Name, Case Number,
    Document Title, or Corporate Headers) while preserving genuine body text.
    """

    def applies(self, doc_type: str) -> bool:
        # Headers are typical in PDFs and multi-page TIFFs/Images
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        # 1. Split text into pages based on page markers
        page_pattern = r"(--- Page \d+ ---)"
        parts = re.split(page_pattern, text)

        # If there are no page markers (or only 1 page), we cannot detect repeating headers
        if len(parts) <= 2:
            return text, context

        # Reconstruct pages: a list of dictionaries with page header and page content
        pages: List[Dict[str, str]] = []
        
        # parts will contain [leading_text, page_marker, page_text, page_marker, page_text, ...]
        # If leading_text is empty or just whitespace, we skip it
        leading = parts[0].strip()
        if leading:
            pages.append({"marker": "", "content": parts[0]})

        for i in range(1, len(parts), 2):
            marker = parts[i]
            content = parts[i + 1] if i + 1 < len(parts) else ""
            pages.append({"marker": marker, "content": content})

        # Count total pages
        total_pages = len([p for p in pages if p["marker"]])
        if total_pages < 2:
            return text, context

        # 2. Extract first few non-empty lines from each page to find repeating patterns
        top_lines_by_page = []
        all_header_candidate_lines = []

        for p in pages:
            if not p["marker"]:
                continue
            
            # Get first 3 non-empty lines of page content
            lines = [line.strip() for line in p["content"].split("\n") if line.strip()]
            top_lines = lines[:3]
            top_lines_by_page.append(top_lines)
            all_header_candidate_lines.extend(top_lines)

        # Count occurrences of header candidate lines
        line_counts = Counter(all_header_candidate_lines)

        # Define thresholds for repeating headers
        # Must appear on at least 30% of pages and be at least 5 characters long
        threshold = max(2, int(total_pages * 0.3))
        repeating_headers = {
            line for line, count in line_counts.items()
            if count >= threshold and len(line) >= 5
        }

        if not repeating_headers:
            return text, context

        # 3. Clean pages by removing the repeating header lines from the top section
        headers_removed_count = 0
        cleaned_parts = []

        # If there was leading text before first page marker, add it back
        if pages and not pages[0]["marker"]:
            cleaned_parts.append(pages[0]["content"])
            pages = pages[1:]

        for p in pages:
            lines = p["content"].split("\n")
            cleaned_lines = []
            removed_from_page_top = False
            top_line_index = 0

            # Scan the beginning of the page lines (up to the first few non-empty lines)
            # and drop them if they match a detected repeating header
            non_empty_seen = 0
            for line in lines:
                stripped = line.strip()
                if stripped:
                    non_empty_seen += 1
                    if non_empty_seen <= 4 and stripped in repeating_headers:
                        # Drop repeating header line
                        headers_removed_count += 1
                        continue
                cleaned_lines.append(line)

            p_content = "\n".join(cleaned_lines)
            cleaned_parts.append(p["marker"])
            cleaned_parts.append(p_content)

        context["headers_removed"] = context.get("headers_removed", 0) + headers_removed_count

        return "".join(cleaned_parts), context
