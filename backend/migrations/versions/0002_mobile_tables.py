"""add mobile device / pairing / session tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05

Mobile companion support (app/mobile/auth.py models) shipped without a
migration — these tables were only ever created by tests via
Base.metadata.create_all, so a fresh production database was missing them.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permissions", JSONB(), nullable=False),
        sa.Column("device_metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mobile_devices")),
    )
    op.create_index(
        op.f("ix_mobile_devices_device_id"),
        "mobile_devices",
        ["device_id"],
        unique=True,
    )

    op.create_table(
        "pairing_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("qr_code_data", sa.Text(), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pairing_sessions")),
    )
    op.create_index(
        op.f("ix_pairing_sessions_session_token"),
        "pairing_sessions",
        ["session_token"],
        unique=True,
    )

    op.create_table(
        "mobile_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mobile_sessions")),
    )
    op.create_index(
        op.f("ix_mobile_sessions_session_token"),
        "mobile_sessions",
        ["session_token"],
        unique=True,
    )
    op.create_index(
        op.f("ix_mobile_sessions_device_id"),
        "mobile_sessions",
        ["device_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mobile_sessions_device_id"), table_name="mobile_sessions")
    op.drop_index(op.f("ix_mobile_sessions_session_token"), table_name="mobile_sessions")
    op.drop_table("mobile_sessions")
    op.drop_index(op.f("ix_pairing_sessions_session_token"), table_name="pairing_sessions")
    op.drop_table("pairing_sessions")
    op.drop_index(op.f("ix_mobile_devices_device_id"), table_name="mobile_devices")
    op.drop_table("mobile_devices")
