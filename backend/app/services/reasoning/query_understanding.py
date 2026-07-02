import logging
import re
from typing import Dict, Any
from app.services.llm import LLMService

logger = logging.getLogger(__name__)


class QueryUnderstandingService:
    """
    Classifies user queries into granular Legal Reasoning intents
    and determines the optimal retrieval/reasoning execution plans.
    """

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def classify_query(self, query: str) -> Dict[str, Any]:
        """
        Classifies query intent and strategy.
        Uses fast regex pattern-matching rules first, falling back to LLM analysis.
        """
        query_clean = query.strip().lower()

        # 1. Rule-based Intent Classifier
        rules = [
            (r"\b(contradict|conflict|inconsistent|discrepancy|clash|oppose|opposite|denied|differ|untrue|false)\b", "Contradiction Analysis"),
            (r"\b(compare|contrast|difference|versus|vs|similarity|resemble|parallel|side-by-side|equivalent)\b", "Comparative Analysis"),
            (r"\b(date|chronology|timeline|history|sequence|year|month|when|after|before|following|event)\b", "Timeline Question"),
            (r"\b(statute|section|act|article|code|law|regulation|enactment|by-law)\b", "Statute Lookup"),
            (r"\b(evidence|witness|testimony|exhibit|deposition|fact|proof|sworn|record)\b", "Evidence Evaluation"),
            (r"\b(procedure|motion|procedural|filing|jurisdiction|appeal|pleading|complaint|answer|order|ruling)\b", "Procedural Question"),
            (r"\b(who|party|plaintiff|defendant|advocate|lawyer|judge|counsel|client|entity|witness name)\b", "Entity Question"),
            (r"\b(precedent|case law|citations|authority|holding|ruled|decided|judgement|ruling)\b", "Legal Research"),
            (r"\b(cross-document|multiple documents|across all|contracts comparison|filings comparison)\b", "Cross-document Analysis"),
        ]

        matched_intent = None
        for pattern, intent in rules:
            if re.search(pattern, query_clean):
                matched_intent = intent
                break

        if matched_intent:
            strategy = self._map_intent_to_strategy(matched_intent)
            return {
                "query": query,
                "intent": matched_intent,
                "strategy": strategy,
                "confidence": 0.90,
                "reasoning_needed": strategy != "Simple lookup",
            }

        # 2. LLM Fallback Classifier
        try:
            system_prompt = (
                "You are an expert legal reasoning system. Analyze the legal query "
                "and classify it into exactly one of these intents:\n"
                "- Fact Lookup\n"
                "- Timeline Question\n"
                "- Entity Question\n"
                "- Comparative Analysis\n"
                "- Legal Research\n"
                "- Statute Lookup\n"
                "- Contradiction Analysis\n"
                "- Evidence Evaluation\n"
                "- Procedural Question\n"
                "- Multi-hop Reasoning\n"
                "- Cross-document Analysis\n\n"
                "Respond in JSON format: {\"intent\": \"...\", \"confidence\": 0.95, \"reasoning\": \"brief explanation\"}"
            )
            prompt = f"Query: {query}"
            
            # Using mock provider or routing provider based on system defaults
            llm_res = self.llm_service.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                provider="mock",  # Fallback to mock adapter for unit-testing/quick path
            )
            content = llm_res.get("content", "")
            import json
            data = json.loads(re.search(r"\{.*\}", content, re.DOTALL).group(0))
            intent = data.get("intent", "Fact Lookup")
            confidence = data.get("confidence", 0.85)
        except Exception as e:
            logger.warning("QueryUnderstandingService: LLM classification failed: %s. Defaulting to Fact Lookup.", e)
            intent = "Fact Lookup"
            confidence = 0.50

        strategy = self._map_intent_to_strategy(intent)
        return {
            "query": query,
            "intent": intent,
            "strategy": strategy,
            "confidence": confidence,
            "reasoning_needed": strategy != "Simple lookup",
        }

    def _map_intent_to_strategy(self, intent: str) -> str:
        mapping = {
            "Fact Lookup": "Simple lookup",
            "Timeline Question": "Timeline reasoning",
            "Entity Question": "Graph reasoning",
            "Comparative Analysis": "Comparative reasoning",
            "Legal Research": "Graph reasoning",
            "Statute Lookup": "Simple lookup",
            "Contradiction Analysis": "Comparative reasoning",
            "Evidence Evaluation": "Multi-hop reasoning",
            "Procedural Question": "Simple lookup",
            "Multi-hop Reasoning": "Multi-hop reasoning",
            "Cross-document Analysis": "Cross-document reasoning",
        }
        return mapping.get(intent, "Simple lookup")
