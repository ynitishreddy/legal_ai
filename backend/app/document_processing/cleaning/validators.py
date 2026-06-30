"""
app.document_processing.cleaning.validators — Text validation routines for cleaning pipeline (Phase 5.3).
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CleaningValidationError(Exception):
    """Exception raised when cleaned text fails validation requirements."""
    pass


def validate_cleaned_text(original_text: str, cleaned_text: str) -> None:
    """
    Performs validation checks on the output of the text cleaning pipeline.
    Raises CleaningValidationError if any rule is violated.
    """
    if not cleaned_text:
        raise CleaningValidationError("Cleaned text is empty.")

    # 1. Minimum text length check (if original text is not empty)
    if original_text.strip() and len(cleaned_text.strip()) < 5:
        raise CleaningValidationError(
            f"Cleaned text is too short ({len(cleaned_text)} chars) compared to original ({len(original_text)} chars)."
        )

    # 2. Extreme character deletion check (e.g. if > 80% of text was deleted)
    # This guards against buggy rules wiping out entire pages
    orig_len = len(original_text.strip())
    clean_len = len(cleaned_text.strip())
    if orig_len > 100:
        ratio = clean_len / orig_len
        if ratio < 0.2:  # More than 80% deleted
            raise CleaningValidationError(
                f"Severe text loss detected. Output retained only {ratio*100:.1f}% of input characters."
            )

    # 3. Unicode validity check (ensure it can be encoded back to UTF-8 without errors)
    try:
        cleaned_text.encode("utf-8")
    except UnicodeEncodeError as err:
        raise CleaningValidationError(f"Unicode encoding validation failed: {err}") from err

    # 4. Paragraph integrity check
    # Ensure paragraph separators (double newlines) exist in the cleaned text if they existed in the original
    orig_paragraphs = original_text.count("\n\n")
    clean_paragraphs = cleaned_text.count("\n\n")
    
    if orig_paragraphs > 2 and clean_paragraphs == 0:
        raise CleaningValidationError(
            "Paragraph structure corrupted: input has paragraph breaks, but output has none."
        )

    logger.info("Validation passed successfully: text length %d, UTF-8 OK.", len(cleaned_text))
