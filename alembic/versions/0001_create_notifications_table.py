"""create notifications table

Revision ID: 0001
Revises:
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",

        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),

        sa.Column("source_service", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),

        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500)),
        sa.Column("body", sa.Text, nullable=False),

        sa.Column("priority", sa.Integer, default=3),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),

        sa.Column("retry_count", sa.Integer, default=0),
        sa.Column("max_retries", sa.Integer, default=3),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),

        sa.Column("external_id", sa.String(255)),
        sa.Column("metadata", JSONB),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )

    # idempotency unique constraint
    op.create_unique_constraint(
        "uq_notifications_idempotency_key",
        "notifications",
        ["idempotency_key"],
    )

    # index for worker queries
    op.create_index(
        "ix_notifications_worker",
        "notifications",
        ["status", "priority", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_worker", table_name="notifications")
    op.drop_constraint("uq_notifications_idempotency_key", "notifications")
    op.drop_table("notifications")