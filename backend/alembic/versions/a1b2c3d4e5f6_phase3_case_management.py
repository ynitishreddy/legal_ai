"""phase3_case_management

Revision ID: a1b2c3d4e5f6
Revises: 541b7943d5ce
Create Date: 2026-06-29

Adds Phase 3 Case Management fields:
  - New CasePriority enum type
  - New CaseStatus values: open, on_hold
  - New columns: jurisdiction, judge_name, opposing_party, client_name,
                 priority, tags, notes, archived
  - Indexes on (owner_id, archived) and title
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "541b7943d5ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Add new CaseStatus enum values ────────────────────────────────────
    # PostgreSQL requires committing the ALTER TYPE before using new values
    op.execute("ALTER TYPE casestatus ADD VALUE IF NOT EXISTS 'open'")
    op.execute("ALTER TYPE casestatus ADD VALUE IF NOT EXISTS 'on_hold'")

    # ── 2. Create CasePriority enum ──────────────────────────────────────────
    casepriority = sa.Enum("low", "medium", "high", "urgent", name="casepriority")
    casepriority.create(op.get_bind(), checkfirst=True)

    # ── 3. Add new columns to cases table ────────────────────────────────────
    op.add_column("cases", sa.Column("jurisdiction", sa.String(255), nullable=True))
    op.add_column("cases", sa.Column("judge_name", sa.String(255), nullable=True))
    op.add_column("cases", sa.Column("opposing_party", sa.String(255), nullable=True))
    op.add_column("cases", sa.Column("client_name", sa.String(255), nullable=True))
    op.add_column(
        "cases",
        sa.Column(
            "priority",
            sa.Enum("low", "medium", "high", "urgent", name="casepriority"),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column("cases", sa.Column("tags", sa.Text, nullable=True))
    op.add_column("cases", sa.Column("notes", sa.Text, nullable=True))
    op.add_column(
        "cases",
        sa.Column("archived", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 4. Add indexes ────────────────────────────────────────────────────────
    op.create_index("ix_cases_title", "cases", ["title"])
    op.create_index("ix_cases_owner_archived", "cases", ["owner_id", "archived"])


def downgrade() -> None:
    op.drop_index("ix_cases_owner_archived", table_name="cases")
    op.drop_index("ix_cases_title", table_name="cases")

    op.drop_column("cases", "archived")
    op.drop_column("cases", "notes")
    op.drop_column("cases", "tags")
    op.drop_column("cases", "priority")
    op.drop_column("cases", "client_name")
    op.drop_column("cases", "opposing_party")
    op.drop_column("cases", "judge_name")
    op.drop_column("cases", "jurisdiction")

    op.execute("DROP TYPE IF EXISTS casepriority")
    # Note: PostgreSQL does not support removing enum values; downgrade leaves
    # 'open' and 'on_hold' in casestatus but they simply won't be used.
