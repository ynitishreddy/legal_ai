"""
app.document_processing.cleaning.strategies.whitespace — Whitespace cleanup strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class WhitespaceCleanupStrategy(CleaningStrategy):
    """
    Cleans up repeated spaces, tabs, and excess blank lines.
    Ensures paragraph boundaries (double newlines) are preserved.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        original_len = len(text)

        # 1. Strip trailing whitespace from every line, keep leading spaces (for indentation/lists)
        lines = [line.rstrip() for line in text.split("\n")]
        text_rstripped = "\n".join(lines)

        # 2. Collapse repeated horizontal spaces (spaces and tabs) to a single space on each line
        # Use regex to replace 2 or more horizontal spaces with a single space
        cleaned = re.sub(r"[ \t]+", " ", text_rstripped)

        # 3. Collapse 3 or more consecutive newlines into exactly two newlines (paragraph boundary)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # 4. Clean leading/trailing spaces at the start/end of the overall document text
        cleaned = cleaned.strip()

        # Update metrics
        reduction = original_len - len(cleaned)
        if reduction > 0:
            context["whitespace_reductions"] = context.get("whitespace_reductions", 0) + reduction

        return cleaned, context
