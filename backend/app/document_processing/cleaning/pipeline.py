"""
app.document_processing.cleaning.pipeline — Main cleaning pipeline orchestrator (Phase 5.3).
"""

import logging
from typing import Dict, Any, Tuple

from app.document_processing.cleaning.cleaner import TextCleanerOrchestrator
from app.document_processing.cleaning.strategies.unicode import UnicodeNormalizerStrategy
from app.document_processing.cleaning.strategies.whitespace import WhitespaceCleanupStrategy
from app.document_processing.cleaning.strategies.ocr_cleanup import OcrCleanupStrategy
from app.document_processing.cleaning.strategies.headers import HeaderRemovalStrategy
from app.document_processing.cleaning.strategies.footers import FooterRemovalStrategy
from app.document_processing.cleaning.strategies.page_numbers import PageNumberRemovalStrategy
from app.document_processing.cleaning.strategies.hyphenation import HyphenationRepairStrategy
from app.document_processing.cleaning.strategies.line_wrapping import LineWrappingRepairStrategy
from app.document_processing.cleaning.strategies.bullets import BulletNormalizationStrategy
from app.document_processing.cleaning.strategies.tables import TableFlatteningStrategy
from app.document_processing.cleaning.strategies.preservation import CitationPreservationStrategy
from app.document_processing.cleaning.validators import validate_cleaned_text

logger = logging.getLogger(__name__)


class DocumentTextCleaningPipeline:
    """
    Orchestrates the execution of all text cleaning strategies.
    Ensures that Unicode, whitespaces, page headers/footers, OCR glitches,
    and line wrapping are repaired, followed by full verification.
    """

    PIPELINE_VERSION = "1.0.0"

    def __init__(self) -> None:
        # Define strategies in their specific pipeline execution order
        self.preservation_strategy = CitationPreservationStrategy()
        
        self.strategies = [
            UnicodeNormalizerStrategy(),       # 1. Normalize unicode shapes/quotes/dashes
            self.preservation_strategy,        # 2. Count citations before changes (guard)
            OcrCleanupStrategy(),              # 3. Strip duplicate commas/garbage borders
            HeaderRemovalStrategy(),           # 4. Remove repeating headers across pages
            FooterRemovalStrategy(),           # 5. Remove repeating footers across pages
            PageNumberRemovalStrategy(),       # 6. Remove page number patterns from margins
            HyphenationRepairStrategy(),       # 7. Merge words hyphen-broken across lines
            LineWrappingRepairStrategy(),      # 8. Merge wrapped lines into paragraphs
            BulletNormalizationStrategy(),     # 9. Standardize lists and bullets
            TableFlatteningStrategy(),         # 10. Flatten ASCII/pipe tables
        ]
        self.orchestrator = TextCleanerOrchestrator(self.strategies)

    def clean_text(self, text: str, doc_category: str) -> Tuple[str, Dict[str, Any]]:
        """
        Executes cleaning pipeline on the input text.
        Returns:
            Tuple of (cleaned_text, cleaning_report_dictionary)
        """
        logger.info("Starting cleaning pipeline for doc_category: %s", doc_category)
        
        # 1. Clean the text using the orchestrator
        cleaned_text, report = self.orchestrator.clean_document(text, doc_category)

        # 2. Run post-processing verification checks
        report = self.preservation_strategy.post_pipeline_verify(text, cleaned_text, report)

        # 3. Validate overall output integrity
        try:
            validate_cleaned_text(text, cleaned_text)
        except Exception as exc:
            logger.error("Cleaning validation failed: %s", exc)
            report["warnings"].append(f"Validation failed: {exc}")
            raise

        # 4. Add global pipeline metadata
        report["version"] = self.PIPELINE_VERSION

        return cleaned_text, report
