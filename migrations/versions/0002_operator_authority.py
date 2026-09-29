"""Record asymmetric operator authority key identity.

Revision ID: 0002_operator_authority
Revises: 0001_production_persistence
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_operator_authority"
down_revision: str | None = "0001_production_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable key identities for HMAC-compatible authority ledgers."""
    op.execute(
        """
        ALTER TABLE approval_consumption ADD COLUMN authority_key_id TEXT;
        ALTER TABLE action_approval_consumption ADD COLUMN authority_key_id TEXT;
        ALTER TABLE tool_action_reconciliation_consumption
            ADD COLUMN authority_key_id TEXT;
        """
    )


def downgrade() -> None:
    """Remove asymmetric authority key identities."""
    op.execute(
        """
        ALTER TABLE tool_action_reconciliation_consumption
            DROP COLUMN authority_key_id;
        ALTER TABLE action_approval_consumption DROP COLUMN authority_key_id;
        ALTER TABLE approval_consumption DROP COLUMN authority_key_id;
        """
    )
