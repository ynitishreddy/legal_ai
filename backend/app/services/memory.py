import json
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import ChatMessage, ChatRole

logger = logging.getLogger(__name__)


class ConversationMemoryService:
    """
    Manages conversational memory, tracks referenced entities and documents,
    and summarizes long chats to stay within model token bounds.
    """
    def __init__(self, db: Session, turn_limit: int = 5) -> None:
        self.db = db
        self.turn_limit = turn_limit

    def get_conversation_context(self, session_id: UUID) -> Dict[str, Any]:
        """
        Gathers memory components: summary, referenced docs, referenced entities,
        and recent messages list.
        """
        messages = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(self.turn_limit * 2)
            .all()
        )
        # Reverse to get chronological order
        messages.reverse()

        referenced_docs = []
        referenced_entities = set()
        recent_turns = []

        for msg in messages:
            recent_turns.append({
                "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "content": msg.content,
            })
            
            # Extract citations if assistant
            if msg.role == ChatRole.ASSISTANT and msg.citations_json:
                try:
                    cits = json.loads(msg.citations_json)
                    for c in cits:
                        referenced_docs.append({
                            "document_id": c.get("document_id"),
                            "document_name": c.get("document_name"),
                            "page_number": c.get("page_number"),
                        })
                except Exception:
                    pass

            # Primitive regex heuristic to extract potential legal entities (e.g., 'Court', 'High Court', 'FIR')
            import re
            found_entities = re.findall(
                r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Court|State|Union|Ltd|Corp|Inc))\b",
                msg.content
            )
            for entity in found_entities:
                referenced_entities.add(entity.strip())

        # Deduplicate docs list by name
        seen_docs = set()
        dedup_docs = []
        for d in referenced_docs:
            if d["document_name"] not in seen_docs:
                seen_docs.add(d["document_name"])
                dedup_docs.append(d)

        # Generate summary heuristic if count > threshold
        summary = ""
        total_msgs = self.db.query(ChatMessage).filter(ChatMessage.session_id == session_id).count()
        if total_msgs > self.turn_limit * 2:
            summary = self.generate_conversation_summary(messages)

        return {
            "session_id": str(session_id),
            "summary": summary,
            "referenced_documents": dedup_docs,
            "referenced_entities": list(referenced_entities),
            "recent_turns": recent_turns,
            "turn_count": total_msgs // 2,
        }

    def generate_conversation_summary(self, messages: List[ChatMessage]) -> str:
        """Heuristic summary builder describing past conversation turns."""
        user_queries = [m.content for m in messages if m.role == ChatRole.USER]
        if not user_queries:
            return ""
        
        topics = ", ".join([q[:30] + "..." if len(q) > 30 else q for q in user_queries[:3]])
        return f"Discussion centered around legal queries concerning: {topics}."
