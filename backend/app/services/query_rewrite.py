import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class QueryRewriteService:
    """
    Rewrites user follow-up queries using prior memory context.
    Resolves pronouns, timeline references, and removes conversational noise.
    """

    def resolve_followup(self, current_query: str, history_turns: List[Dict[str, Any]]) -> str:
        """
        Heuristically resolves coreference pronouns using the last user question topic.
        """
        trimmed = current_query.strip()
        
        # Heuristics for direct pronoun reference resolutions
        lower_query = trimmed.lower()
        
        # Find last user question
        last_user_query = ""
        for turn in reversed(history_turns):
            if turn["role"] == "user":
                last_user_query = turn["content"]
                break

        if not last_user_query:
            return trimmed

        # Resolve 'it', 'this', 'that', 'she', 'he', 'they', 'them'
        pronouns_to_resolve = ["who signed it?", "who filed it?", "who issued it?", "when was it signed?", "when was it filed?"]
        
        resolved = trimmed
        
        # 1. Subject Resolution
        subject_matches = re.findall(r"\b(FIR|complaint|agreement|contract|order|petition|lease|affidavit)\b", last_user_query, re.IGNORECASE)
        subject = subject_matches[0] if subject_matches else "document"

        if re.search(r"\b(it|this|that)\b", lower_query):
            resolved = re.sub(r"\b(it|this|that)\b", f"the {subject}", trimmed, flags=re.IGNORECASE)

        # 2. Entity Coreference Heuristic
        entity_matches = re.findall(r"\b([A-Z][a-zA-Z\s]+(?:Court|State|Union|Ltd|Corp|Inc|Partners))\b", last_user_query)
        if entity_matches:
            target_entity = entity_matches[0]
            if re.search(r"\b(they|them|he|she)\b", lower_query):
                resolved = re.sub(r"\b(they|them|he|she)\b", target_entity, resolved, flags=re.IGNORECASE)

        # 3. Clean up leading conversational phrases
        resolved = re.sub(r"^(ok|okay|so|then|well|can you tell me|please tell me|what about|how about)\s+", "", resolved, flags=re.IGNORECASE)

        return resolved

    def rewrite_query(self, query: str, history_turns: List[Dict[str, Any]]) -> str:
        """
        Wipes noise and transforms conversational queries into standalone Qdrant parameters.
        """
        # Resolve coreferences first
        resolved = self.resolve_followup(query, history_turns)
        
        # Remove trailing question marks or filler tokens
        cleaned = re.sub(r"[?.]+$", "", resolved).strip()
        
        # Lowercase duplicate detection
        if cleaned.lower() in [turn["content"].lower() for turn in history_turns if turn["role"] == "user"]:
            logger.info("QueryRewriteService: Duplicate query detected: %s", cleaned)
            
        return cleaned
