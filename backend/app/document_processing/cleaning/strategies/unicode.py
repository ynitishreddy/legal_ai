"""
app.document_processing.cleaning.strategies.unicode — Unicode Normalization Strategy (Phase 5.3).
"""

import unicodedata
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class UnicodeNormalizerStrategy(CleaningStrategy):
    """
    Standardizes typographic symbols (smart quotes, curly apostrophes, en/em dashes)
    and normalizes character representations via Unicode NFKC.
    """

    def applies(self, doc_type: str) -> bool:
        return True  # Applies universally to all document formats

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        original_len = len(text)

        # 1. Typography cleanup
        replacements = {
            # Double curly quotes
            "“": '"',
            "”": '"',
            "„": '"',
            "‟": '"',
            # Single curly quotes / apostrophes
            "‘": "'",
            "’": "'",
            "‚": "'",
            "‛": "'",
            "′": "'",
            "`": "'",
            # Dashes
            "—": "-",  # em dash
            "–": "-",  # en dash
            "−": "-",  # minus sign
            "⎯": "-",  # horizontal bar
            # Spaces
            "\xa0": " ",      # non-breaking space
            "\u2007": " ",    # figure space
            "\u2008": " ",    # punctuation space
            "\u2009": " ",    # thin space
            "\u200a": " ",    # hair space
            "\u202f": " ",    # narrow no-break space
            # Zero-width spaces and control characters (remove)
            "\u200b": "",     # zero-width space
            "\u200c": "",     # zero-width non-joiner
            "\u200d": "",     # zero-width joiner
            "\u200e": "",     # left-to-right mark
            "\u200f": "",     # right-to-left mark
            "\ufeff": "",     # byte order mark (BOM)
        }

        cleaned = text
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)

        # 2. Consistently normalize via Unicode NFKC
        cleaned = unicodedata.normalize("NFKC", cleaned)

        # Calculate character reduction (purely from Unicode transformations)
        diff = original_len - len(cleaned)
        if diff > 0:
            context["whitespace_reductions"] = context.get("whitespace_reductions", 0) + diff

        return cleaned, context
