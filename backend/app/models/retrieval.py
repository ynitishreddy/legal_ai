import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models import utcnow


class RetrievalLog(Base):
    """
    Persists query logs and semantic retrieval metrics for audit trail and quality analysis.
    """
    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    retrieved_documents_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    top_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    chunks_returned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
