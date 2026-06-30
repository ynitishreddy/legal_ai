"""add_checksum_index

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-06-30
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "d4e5f6a1b2c3"
down_revision: Union[str, None] = "c3d4e5f6a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_documents_checksum", "documents", ["checksum"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_checksum", table_name="documents")
