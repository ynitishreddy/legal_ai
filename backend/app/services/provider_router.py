import logging
from typing import Dict, Any, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ProviderRoutingEngine:
    """
    Intelligently routes legal RAG queries to the optimal model provider
    based on query complexity and failover states.
    """
    def __init__(self) -> None:
        self.settings = get_settings()

    def select_route(self, query: str, config_override: Optional[str] = None) -> Dict[str, str]:
        """
        Returns targeted {provider, model} dict.
        """
        # If user explicitly requests a provider, respect the override
        if config_override and config_override != "auto":
            p = config_override.lower()
            if p == "openai":
                return {"provider": "openai", "model": self.settings.openai_model}
            elif p == "gemini":
                return {"provider": "gemini", "model": self.settings.gemini_model}
            elif p == "ollama":
                return {"provider": "ollama", "model": self.settings.ollama_model}
            return {"provider": "mock", "model": "mock-model"}

        # If default settings enforce mock provider, return mock
        if self.settings.default_llm_provider == "mock":
            return {"provider": "mock", "model": "mock-model"}

        # Custom Heuristic Routing logic
        q = query.lower()
        
        # 1. Complex analysis -> OpenAI GPT-4
        if any(w in q for w in ["infringement", "breach", "liability", "reasoning", "assess", "compliance"]):
            logger.info("ProviderRoutingEngine: Routed to OpenAI GPT-4 for complex analysis.")
            if self.settings.openai_api_key:
                return {"provider": "openai", "model": "gpt-4"}
            
        # 2. Simple lookup/lookup lists -> Gemini Flash
        if len(query) < 50 or any(w in q for w in ["when", "who", "list", "where", "date"]):
            logger.info("ProviderRoutingEngine: Routed to Gemini Flash for fast lookup.")
            if self.settings.gemini_api_key:
                return {"provider": "gemini", "model": "gemini-1.5-flash"}

        # Default fallback provider
        default_p = self.settings.default_llm_provider
        if default_p == "openai" and self.settings.openai_api_key:
            return {"provider": "openai", "model": self.settings.openai_model}
        elif default_p == "gemini" and self.settings.gemini_api_key:
            return {"provider": "gemini", "model": self.settings.gemini_model}
        elif default_p == "ollama":
            return {"provider": "ollama", "model": self.settings.ollama_model}
            
        logger.warning("ProviderRoutingEngine: Targeted provider unavailable. Falling back to mock adapter.")
        return {"provider": "mock", "model": "mock-model"}
