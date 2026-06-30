"""phase43_metadata_organization

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-06-29

Adds Phase 4.3 Document Metadata and Organization fields:
  - New DocumentCategory enum type
  - Columns: document_category, user_tags, description, last_accessed_at
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create enum type
    op.execute("CREATE TYPE documentcategory AS ENUM ('pdf', 'word', 'text', 'image', 'other')")

    # 2. Add columns
    op.add_column(
        "documents",
        sa.Column(
            "document_category",
            sa.Enum("pdf", "word", "text", "image", "other", name="documentcategory"),
            nullable=False,
            server_default="other",
        ),
    )
    op.add_column("documents", sa.Column("user_tags", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "last_accessed_at")
    op.drop_column("documents", "description")
    op.drop_column("documents", "user_tags")
    op.drop_column("documents", "document_category")

    op.execute("DROP TYPE IF EXISTS documentcategory")
