"""phase53_text_cleaning

Revision ID: 477feaaf479a
Revises: a2b3c4d5e6f7
Create Date: 2026-06-30 19:20:09.522512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '477feaaf479a'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_texts', sa.Column('cleaned_text', sa.Text(), nullable=True))
    op.add_column('document_texts', sa.Column('cleaning_version', sa.String(length=20), nullable=True))
    op.add_column('document_texts', sa.Column('cleaning_report_json', sa.Text(), nullable=True))
    op.add_column('document_texts', sa.Column('cleaning_processing_time', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('document_texts', 'cleaning_processing_time')
    op.drop_column('document_texts', 'cleaning_report_json')
    op.drop_column('document_texts', 'cleaning_version')
    op.drop_column('document_texts', 'cleaned_text')

