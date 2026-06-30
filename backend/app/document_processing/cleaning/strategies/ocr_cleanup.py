"""
app.document_processing.cleaning.strategies.ocr_cleanup — OCR Artifact Cleanup Strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class OcrCleanupStrategy(CleaningStrategy):
    """
    Cleans up noise, broken characters, and duplicated symbols typical of OCR extraction.
    Keep rules conservative to prevent deleting valid document structures.
    """

    def applies(self, doc_type: str) -> bool:
        # OCR cleanup is primarily needed for PDFs and Images, but safe to run on others
        return doc_type in ("pdf", "image", "scanned_pdf")

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        original_text = text
        repairs_count = 0

        # 1. Clean up duplicate punctuation (e.g., duplicate commas, colons, semicolons)
        # Avoid removing triple dots (ellipsis '...')
        punc_rules = [
            (r",\s*,+", ",", "duplicate_commas"),
            (r";\s*;+", ";", "duplicate_semicolons"),
            (r":\s*:+", ":", "duplicate_colons"),
            (r"\?\s*\?+", "?", "duplicate_questions"),
            (r"!\s*!+", "!", "duplicate_exclamations"),
        ]
        
        cleaned = text
        for pattern, replacement, label in punc_rules:
            matches = len(re.findall(pattern, cleaned))
            if matches > 0:
                cleaned = re.sub(pattern, replacement, cleaned)
                repairs_count += matches

        # 2. Clean up noise lines (lines consisting entirely of non-alphanumeric punctuation/symbols)
        # E.g., "_______", ".......", "* * * * * *"
        # We preserve page markers like "--- Page X ---"
        lines = cleaned.split("\n")
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            # If it's a page marker, keep it
            if re.match(r"^---\s*Page\s+\d+\s*---$", stripped, re.IGNORECASE):
                filtered_lines.append(line)
                continue
            
            # If line is longer than 5 chars and consists entirely of non-alphanumeric symbols
            # like ".......", "_______", "------" (excluding page markers)
            if len(stripped) >= 5 and re.match(r"^[_\.\-\*~=\+ ]+$", stripped):
                # Classify as noise line and drop
                repairs_count += 1
                continue
            
            # Remove isolated random noise characters at line boundaries
            # E.g., "| Document Title" -> "Document Title"
            # E.g., "Document Title |" -> "Document Title"
            # OCR often misreads borders or lines as pipe "|" or slash "/"
            if stripped.startswith("| ") or stripped.startswith("/ "):
                line = line.replace("| ", "", 1).replace("/ ", "", 1)
                repairs_count += 1
            if stripped.endswith(" |") or stripped.endswith(" /"):
                # strip last 2 characters
                line = line[:-2].rstrip()
                repairs_count += 1

            filtered_lines.append(line)

        cleaned = "\n".join(filtered_lines)

        # 3. Clean up isolated single characters that are clearly junk
        # E.g., text containing lone backslashes or random non-word characters in spaces
        # Match standalone non-word chars surrounded by space like "word \ word"
        junk_matches = len(re.findall(r"\s+[\\|/_\+]\s+", cleaned))
        if junk_matches > 0:
            cleaned = re.sub(r"\s+[\\|/_\+]\s+", " ", cleaned)
            repairs_count += junk_matches

        context["ocr_repairs"] = context.get("ocr_repairs", 0) + repairs_count
        return cleaned, context
