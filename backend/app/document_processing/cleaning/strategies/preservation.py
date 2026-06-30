"""
app.document_processing.cleaning.strategies.preservation — Citation preservation guard strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class CitationPreservationStrategy(CleaningStrategy):
    """
    Performs validation checks to ensure legal citations (e.g., SCC, AIR, IPC, USC)
    are preserved intact throughout the text processing.
    Adds warning flags to the cleaning report context if citation mismatches are found.
    """

    # Major citation regex patterns
    CITATION_PATTERNS = [
        r"\b\d+\s+SCC\s+\d+\b",                       # e.g., 2023 SCC Online 245
        r"\bAIR\s+\d+\s+SC\s+\d+\b",                 # e.g., AIR 2020 SC 25
        r"\bSection\s+\d+\s+[A-Z]+\b",               # e.g., Section 302 IPC
        r"\bArticle\s+\d+\b",                        # e.g., Article 21
        r"\bOrder\s+[A-Z|v|V|i|I|x|X]+\s+Rule\s+\d+\b" # e.g., Order VII Rule 11
    ]

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        # Count citations in the input text
        original_counts = self._count_citations(text)
        
        # We don't modify the text in this strategy - it is a verification guard strategy
        # placed at the end of the pipeline. We verify that counts are matching.
        context["citation_counts_before"] = original_counts
        return text, context

    def _count_citations(self, text: str) -> int:
        if not text:
            return 0
        
        total_matches = 0
        for pattern in self.CITATION_PATTERNS:
            total_matches += len(re.findall(pattern, text, re.IGNORECASE))
        return total_matches

    def post_pipeline_verify(self, original_text: str, cleaned_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs post-processing checks on citations and paragraph integrity.
        """
        before_count = context.get("citation_counts_before", 0)
        after_count = self._count_citations(cleaned_text)

        if before_count != after_count:
            warning_msg = f"Citation count discrepancy detected: {before_count} before cleaning, {after_count} after."
            context["warnings"].append(warning_msg)
            
        return context
