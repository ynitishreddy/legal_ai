"""
app.document_processing.cleaning.strategies.bullets — Bullet & list list normalization strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple
from app.document_processing.cleaning.cleaner import CleaningStrategy


class BulletNormalizationStrategy(CleaningStrategy):
    """
    Standardizes loose list bullet points (-, *, o) to standard bullet characters (•),
    and normalizes spacing after alphanumeric list headers (like (a), (1), I.)
    while maintaining list hierarchies.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        lines = text.split("\n")
        normalized_lines = []
        bullets_normalized_count = 0

        # Regex matching hyphen or asterisk bullets at line start, preserving leading indentation
        # E.g. "  - Item text" -> "  • Item text"
        # E.g. "* Item text" -> "• Item text"
        bullet_pattern = re.compile(r"^(\s*)([-*o])\s+(.+)$")

        # Numbered list pattern matching indicators like "(a)   text" or "1.   text"
        numbered_pattern = re.compile(r"^(\s*)(\(\s*[a-zA-Z0-9]+\s*\)|[a-zA-Z0-9]+\s*[\.\)])\s{2,}(.+)$")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                normalized_lines.append(line)
                continue

            # 1. Normalize bullet characters
            bullet_match = bullet_pattern.match(line)
            if bullet_match:
                indent = bullet_match.group(1)
                content = bullet_match.group(3)
                normalized_lines.append(f"{indent}• {content}")
                bullets_normalized_count += 1
                continue

            # 2. Normalize spaces after numbered headers
            numbered_match = numbered_pattern.match(line)
            if numbered_match:
                indent = numbered_match.group(1)
                marker = numbered_match.group(2)
                content = numbered_match.group(3)
                # Ensure exactly 1 space between list marker and body
                normalized_lines.append(f"{indent}{marker.strip()} {content.strip()}")
                bullets_normalized_count += 1
                continue

            normalized_lines.append(line)

        context["bullets_normalized"] = context.get("bullets_normalized", 0) + bullets_normalized_count
        return "\n".join(normalized_lines), context
