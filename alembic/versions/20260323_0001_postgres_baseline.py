"""Create PostgreSQL baseline schema for genset."""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.date(value text)
        RETURNS date
        LANGUAGE sql
        IMMUTABLE
        RETURNS NULL ON NULL INPUT
        AS $$
            SELECT CAST(value AS date)
        $$;
        """
    )

    op.create_table(
        "generators",
        sa.Column("generator_id", sa.Text(), primary_key=True),
        sa.Column("capacity_kva", sa.Integer(), nullable=False),
        sa.Column("identification", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True, server_default=sa.text("'Active'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("inventory_type", sa.Text(), nullable=True, server_default=sa.text("'retailer'")),
        sa.Column("rental_vendor_id", sa.Text(), nullable=True),
    )

    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.Text(), primary_key=True),
        sa.Column("vendor_name", sa.Text(), nullable=False),
        sa.Column("vendor_place", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
    )

    op.create_table(
        "rental_vendors",
        sa.Column("rental_vendor_id", sa.Text(), primary_key=True),
        sa.Column("vendor_name", sa.Text(), nullable=False),
        sa.Column("vendor_place", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
    )

    op.create_table(
        "bookings",
        sa.Column("booking_id", sa.Text(), primary_key=True),
        sa.Column("vendor_id", sa.Text(), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True, server_default=sa.text("'Confirmed'")),
    )

    op.create_table(
        "booking_items",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("booking_id", sa.Text(), sa.ForeignKey("bookings.booking_id"), nullable=False),
        sa.Column("generator_id", sa.Text(), sa.ForeignKey("generators.generator_id"), nullable=False),
        sa.Column("start_dt", sa.Text(), nullable=False),
        sa.Column("end_dt", sa.Text(), nullable=False),
        sa.Column("item_status", sa.Text(), nullable=True, server_default=sa.text("'Confirmed'")),
        sa.Column("remarks", sa.Text(), nullable=True),
    )

    op.create_table(
        "booking_history",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("booking_id", sa.Text(), nullable=True),
        sa.Column("vendor_id", sa.Text(), nullable=True),
        sa.Column("user", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_login", sa.Text(), nullable=True),
    )

    op.create_table(
        "user_permission_overrides",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_key", sa.Text(), nullable=False),
        sa.Column("is_allowed", sa.Integer(), nullable=False),
        sa.CheckConstraint("is_allowed IN (0, 1)", name="ck_user_permission_overrides_is_allowed"),
        sa.PrimaryKeyConstraint("user_id", "capability_key"),
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("last_seen", sa.BigInteger(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )

    op.create_table(
        "booking_id_seq",
        sa.Column("booking_date", sa.Text(), primary_key=True),
        sa.Column("next_val", sa.Integer(), nullable=False),
    )

    op.create_table(
        "vendor_id_seq",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_val", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_vendor_id_seq_single_row"),
    )

    op.create_table(
        "rental_vendor_id_seq",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_val", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_rental_vendor_id_seq_single_row"),
    )

    op.create_index("idx_booking_items_generator", "booking_items", ["generator_id", "item_status"])
    op.create_index("idx_booking_items_booking", "booking_items", ["booking_id"])
    op.create_index("idx_booking_history_time", "booking_history", ["event_time"])
    op.create_index("idx_booking_history_booking", "booking_history", ["booking_id"])
    op.create_index("idx_booking_history_vendor", "booking_history", ["vendor_id"])
    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])
    op.create_index("idx_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("idx_user_permission_overrides_user_id", "user_permission_overrides", ["user_id"])
    op.create_index("idx_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])
    op.create_index("idx_generators_inventory_type", "generators", ["inventory_type", "generator_id"])
    op.create_index(
        "idx_generators_inventory_rental_vendor",
        "generators",
        ["inventory_type", "rental_vendor_id", "generator_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_generators_inventory_rental_vendor", table_name="generators")
    op.drop_index("idx_generators_inventory_type", table_name="generators")
    op.drop_index("idx_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("idx_user_permission_overrides_user_id", table_name="user_permission_overrides")
    op.drop_index("idx_sessions_expires_at", table_name="sessions")
    op.drop_index("idx_sessions_user_id", table_name="sessions")
    op.drop_index("idx_booking_history_vendor", table_name="booking_history")
    op.drop_index("idx_booking_history_booking", table_name="booking_history")
    op.drop_index("idx_booking_history_time", table_name="booking_history")
    op.drop_index("idx_booking_items_booking", table_name="booking_items")
    op.drop_index("idx_booking_items_generator", table_name="booking_items")

    op.drop_table("rental_vendor_id_seq")
    op.drop_table("vendor_id_seq")
    op.drop_table("booking_id_seq")
    op.drop_table("revoked_tokens")
    op.drop_table("sessions")
    op.drop_table("user_permission_overrides")
    op.drop_table("users")
    op.drop_table("booking_history")
    op.drop_table("booking_items")
    op.drop_table("bookings")
    op.drop_table("rental_vendors")
    op.drop_table("vendors")
    op.drop_table("generators")

    op.execute("DROP FUNCTION IF EXISTS public.date(text)")
