"""
app.document_processing.cleaning.strategies.hyphenation — Hyphenation repair strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class HyphenationRepairStrategy(CleaningStrategy):
    """
    Re-merges words that were broken across a line break with a hyphen.
    Preserves legitimate hyphens (e.g. self-esteem, pre-defined).
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        # Heuristic list of prefixes that should keep their hyphen when merged
        hyphen_prefixes = {
            "self", "pre", "co", "anti", "non", "ex", "post",
            "semi", "vice", "sub", "pro", "re", "multi", "ultra",
            "cross", "quasi", "all", "de"
        }

        pattern = r"(\b[a-zA-Z]+)-\s*\n\s*([a-zA-Z]+)"
        repairs = 0

        def replace_hyphen(match: re.Match) -> str:
            nonlocal repairs
            part1 = match.group(1)
            part2 = match.group(2)
            
            repairs += 1
            if part1.lower() in hyphen_prefixes:
                return f"{part1}-{part2}"
            else:
                return f"{part1}{part2}"

        cleaned = re.sub(pattern, replace_hyphen, text)
        context["hyphen_repairs"] = context.get("hyphen_repairs", 0) + repairs

        return cleaned, context
