"""phase51_processing_jobs

Revision ID: f1a2b3c4d5e6
Revises: e5f6a1b2c3d4
Create Date: 2026-06-30

Adds two tables for Phase 5.1 — Background Processing Infrastructure:
  - processing_jobs: tracks each background processing task
  - processing_job_logs: chronological event log per job
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5f6a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ────────────────────────────────────────────────────────────────
    job_status_enum = sa.Enum(
        "pending", "queued", "starting", "running", "completed", "failed", "cancelled",
        name="jobstatus",
    )
    job_type_enum = sa.Enum(
        "ocr", "text_extraction", "cleaning", "chunking",
        "embeddings", "timeline", "summary", "analytics",
        name="jobtype",
    )
    job_priority_enum = sa.Enum(
        "low", "normal", "high", "urgent",
        name="jobpriority",
    )
    job_log_event_type_enum = sa.Enum(
        "created", "queued", "started", "progress",
        "retry", "cancelled", "completed", "failed", "info",
        name="joblogenventtype",
    )

    # ── processing_jobs ───────────────────────────────────────────────────────
    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_type", job_type_enum, nullable=False),
        sa.Column("status", job_status_enum, nullable=False, server_default="pending"),
        sa.Column("priority", job_priority_enum, nullable=False, server_default="normal"),
        # Progress
        sa.Column("progress_percentage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step", sa.String(100), nullable=True),
        # Retry
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        # Error info
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Indexes for common query patterns
    op.create_index("ix_processing_jobs_user_id", "processing_jobs", ["user_id"])
    op.create_index("ix_processing_jobs_document_id", "processing_jobs", ["document_id"])
    op.create_index("ix_processing_jobs_case_id", "processing_jobs", ["case_id"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index("ix_processing_jobs_job_type", "processing_jobs", ["job_type"])
    # Composite index to efficiently check for duplicate active jobs
    op.create_index(
        "ix_processing_jobs_document_type_status",
        "processing_jobs",
        ["document_id", "job_type", "status"],
    )

    # ── processing_job_logs ───────────────────────────────────────────────────
    op.create_table(
        "processing_job_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", job_log_event_type_enum, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("ix_processing_job_logs_job_id", "processing_job_logs", ["job_id"])
    op.create_index("ix_processing_job_logs_created_at", "processing_job_logs", ["created_at"])


def downgrade() -> None:
    # Drop tables in reverse order (child before parent)
    op.drop_index("ix_processing_job_logs_created_at", table_name="processing_job_logs")
    op.drop_index("ix_processing_job_logs_job_id", table_name="processing_job_logs")
    op.drop_table("processing_job_logs")

    op.drop_index("ix_processing_jobs_document_type_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_job_type", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_case_id", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_document_id", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_user_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")

    # Drop custom enum types
    sa.Enum(name="joblogenventtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="jobpriority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="jobtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
