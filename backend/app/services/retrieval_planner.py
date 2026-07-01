import logging
import re
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    FACT_LOOKUP = "fact_lookup"
    TIMELINE_SEARCH = "timeline_search"
    DEFINITION_LOOKUP = "definition_lookup"
    RESEARCH = "research"


class DynamicRetrievalPlanner:
    """
    Analyzes user queries to determine the optimal vector search parameters
    and neighborhood chunk expansions.
    """

    def plan_strategy(self, query: str) -> Dict[str, Any]:
        """
        Detects query keyword mappings to select target top_k counts and threshold parameters.
        """
        q = query.lower()
        
        # 1. Timeline Search: questions asking about chronological orders
        if any(w in q for w in ["timeline", "date", "when", "after", "before", "history", "filed"]):
            logger.info("DynamicRetrievalPlanner: Selected TIMELINE_SEARCH strategy.")
            return {
                "strategy": RetrievalStrategy.TIMELINE_SEARCH.value,
                "top_k": 8,
                "threshold": 0.0,
                "neighbor_limit": 2, # fetch adjacent paragraph contexts
            }
            
        # 2. Definition / Clause Lookup: questions asking about sections
        elif any(w in q for w in ["define", "definition", "clause", "section", "article", "rule"]):
            logger.info("DynamicRetrievalPlanner: Selected DEFINITION_LOOKUP strategy.")
            return {
                "strategy": RetrievalStrategy.DEFINITION_LOOKUP.value,
                "top_k": 3,
                "threshold": 0.1,
                "section_matching": True,
            }
            
        # 3. Broad Legal Research
        elif any(w in q for w in ["summarize", "research", "outline", "explain", "arguments", "findings"]):
            logger.info("DynamicRetrievalPlanner: Selected RESEARCH strategy.")
            return {
                "strategy": RetrievalStrategy.RESEARCH.value,
                "top_k": 10,
                "threshold": 0.05,
                "multi_document": True,
            }
            
        # 4. Standard Fact Lookup
        else:
            logger.info("DynamicRetrievalPlanner: Selected FACT_LOOKUP strategy.")
            return {
                "strategy": RetrievalStrategy.FACT_LOOKUP.value,
                "top_k": 3,
                "threshold": 0.1,
            }
        
