import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.reasoning import ResearchSession, ResearchNote

logger = logging.getLogger(__name__)


class ResearchWorkflowEngine:
    """
    Handles persistence and CRUD operations for saved research sessions,
    notes editing, evidence bookmarks, and search log continuation.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(
        self, user_id: uuid.UUID, title: str, case_id: Optional[uuid.UUID] = None
    ) -> ResearchSession:
        session = ResearchSession(
            user_id=user_id,
            case_id=case_id,
            title=title,
            bookmarks_json=json.dumps([]),
            search_history_json=json.dumps([]),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> Optional[ResearchSession]:
        return (
            self.db.query(ResearchSession)
            .filter(and_(ResearchSession.id == session_id, ResearchSession.user_id == user_id))
            .first()
        )

    def list_sessions(self, user_id: uuid.UUID, case_id: Optional[uuid.UUID] = None) -> List[ResearchSession]:
        query = self.db.query(ResearchSession).filter(ResearchSession.user_id == user_id)
        if case_id:
            query = query.filter(ResearchSession.case_id == case_id)
        return query.order_by(ResearchSession.updated_at.desc()).all()

    def delete_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        session = self.get_session(session_id, user_id)
        if not session:
            return False
        self.db.delete(session)
        self.db.commit()
        return True

    def add_note(self, session_id: uuid.UUID, title: str, content: str) -> ResearchNote:
        note = ResearchNote(
            session_id=session_id,
            title=title,
            content=content,
        )
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return note

    def add_bookmark(
        self, session_id: uuid.UUID, user_id: uuid.UUID, bookmark_item: Dict[str, Any]
    ) -> Optional[ResearchSession]:
        session = self.get_session(session_id, user_id)
        if not session:
            return None

        bookmarks = []
        if session.bookmarks_json:
            try:
                bookmarks = json.loads(session.bookmarks_json)
            except Exception:
                bookmarks = []

        # Add bookmark if unique
        bookmark_id = bookmark_item.get("id")
        if not any(b.get("id") == bookmark_id for b in bookmarks):
            bookmarks.append(bookmark_item)
            session.bookmarks_json = json.dumps(bookmarks)
            self.db.commit()
            self.db.refresh(session)

        return session

    def add_search_query(
        self, session_id: uuid.UUID, user_id: uuid.UUID, query: str
    ) -> Optional[ResearchSession]:
        session = self.get_session(session_id, user_id)
        if not session:
            return None

        history = []
        if session.search_history_json:
            try:
                history = json.loads(session.search_history_json)
            except Exception:
                history = []

        if query not in history:
            history.append(query)
            session.search_history_json = json.dumps(history)
            self.db.commit()
            self.db.refresh(session)

        return session
