"""create notifications table

Revision ID: 0001
Revises:
Create Date: 2026-03-19

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",

        # identity
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),

        # source — 1=order, 2=payment, 3=shipping
        sa.Column("source_service", sa.Integer, nullable=False),

        # event — 1=order.created, 2=order.cancelled, 3=payment.confirmed,
        #         4=payment.failed, 5=payment.otp, 6=shipment.dispatched,
        #         7=shipment.delivered, 8=shipment.delayed
        sa.Column("event_type", sa.Integer, nullable=False),

        # channel — 1=email, 2=sms, 3=push
        sa.Column("channel", sa.Integer, nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),

        # priority — 1=critical, 2=high, 3=medium, 4=low
        sa.Column("priority", sa.Integer, nullable=False, default=3),

        # status — 1=pending, 2=queued, 3=sent, 4=failed, 5=retrying
        sa.Column("status", sa.Integer, nullable=False, default=1),

        # error — 1=timeout, 2=provider_down, 3=rate_limited,
        #         4=invalid_recipient, 5=invalid_token, 6=unknown
        sa.Column("error_code", sa.Integer, nullable=True),

        sa.Column("retry_count", sa.Integer, default=0),
        sa.Column("next_retry_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),

        # channel specific content (subject/body for email, body for sms, title/body for push)
        sa.Column("content", JSONB, nullable=False),

        # timestamps
        sa.Column("ctime", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stime", sa.DateTime(timezone=True), nullable=True),
    )

    # idempotency
    op.create_unique_constraint(
        "uq_notifications_idempotency_key",
        "notifications",
        ["idempotency_key"],
    )

    # worker query index — fetch by status + priority + next_retry_time
    op.create_index(
        "ix_notifications_worker",
        "notifications",
        ["status", "priority", "next_retry_time"],
    )

    # analytics indexes
    op.create_index("ix_notifications_channel", "notifications", ["channel"])
    op.create_index("ix_notifications_event_type", "notifications", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_notifications_event_type", table_name="notifications")
    op.drop_index("ix_notifications_channel", table_name="notifications")
    op.drop_index("ix_notifications_worker", table_name="notifications")
    op.drop_constraint("uq_notifications_idempotency_key", "notifications")
    op.drop_table("notifications")