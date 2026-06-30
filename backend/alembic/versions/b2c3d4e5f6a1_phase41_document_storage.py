"""phase41_document_storage

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-06-29

Adds Phase 4.1 Document Storage fields:
  - New UploadStatus enum type
  - New ProcessingStatus enum type
  - Columns: original_filename, stored_filename, storage_path, file_extension,
             checksum, upload_status, processing_status
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create enum types
    op.execute("CREATE TYPE uploadstatus AS ENUM ('uploading', 'completed', 'failed')")
    op.execute("CREATE TYPE processingstatus AS ENUM ('pending', 'not_started')")

    # 2. Add columns
    op.add_column("documents", sa.Column("original_filename", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("stored_filename", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("storage_path", sa.String(500), nullable=True))
    op.add_column("documents", sa.Column("file_extension", sa.String(10), nullable=True))
    op.add_column("documents", sa.Column("checksum", sa.String(64), nullable=True))
    
    op.add_column(
        "documents",
        sa.Column(
            "upload_status",
            sa.Enum("uploading", "completed", "failed", name="uploadstatus"),
            nullable=False,
            server_default="completed",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "processing_status",
            sa.Enum("pending", "not_started", name="processingstatus"),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "processing_status")
    op.drop_column("documents", "upload_status")
    op.drop_column("documents", "checksum")
    op.drop_column("documents", "file_extension")
    op.drop_column("documents", "storage_path")
    op.drop_column("documents", "stored_filename")
    op.drop_column("documents", "original_filename")

    op.execute("DROP TYPE IF EXISTS uploadstatus")
    op.execute("DROP TYPE IF EXISTS processingstatus")
