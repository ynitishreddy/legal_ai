import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class GuardrailsEngine:
    """
    Defends RAG pipelines against prompt injection, context poisoning,
    and system instructions leaks.
    """

    def check_safety(self, query: str) -> Dict[str, Any]:
        """
        Scans queries for threat signatures.
        """
        q = query.lower()
        
        # 1. System Prompt Leakage Protection
        leakage_patterns = [
            "ignore previous instructions",
            "system instructions",
            "you are a",
            "system prompt",
            "leak the prompt",
            "show instructions",
        ]
        if any(p in q for p in leakage_patterns):
            logger.warning("GuardrailsEngine: Intercepted potential system prompt leakage attempt.")
            return {
                "safe": False,
                "reason": "Security Alert: System instruction queries are blocked.",
                "code": "prompt_leakage",
            }

        # 2. Command Injection Protection
        injection_patterns = [
            "instead, do",
            "overwrite instructions",
            "delete all",
            "drop table",
        ]
        if any(p in q for p in leakage_patterns or p in q for p in injection_patterns):
            logger.warning("GuardrailsEngine: Intercepted command injection query.")
            return {
                "safe": False,
                "reason": "Security Alert: Query contains forbidden instruction patterns.",
                "code": "prompt_injection",
            }

        return {"safe": True, "reason": "Query is safe."}
