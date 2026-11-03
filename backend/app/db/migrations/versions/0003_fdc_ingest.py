"""Columns and indexes the USDA ingest and baseline search need

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTERNAL_SYSTEMS = "'fdc', 'ndb_number', 'fndds_code', 'wikidata', 'barcode'"


def upgrade() -> None:
    op.add_column(
        "food",
        sa.Column("classification_source_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "food",
        sa.Column("is_discoverable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_food_classification_source_id_source"),
        "food",
        "source",
        ["classification_source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_food_classification_source_id"),
        "food",
        ["classification_source_id"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_food_classification_is_cited"),
        "food",
        "processing_level = 'unknown' OR classification_source_id IS NOT NULL",
    )

    op.add_column(
        "food_portion",
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )

    op.create_index(
        "ix_food_alias_normalized_name_trgm",
        "food_alias",
        ["normalized_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )

    op.add_column(
        "recipe",
        sa.Column("moisture_change_pct", sa.Numeric(14, 5, asdecimal=False), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_recipe_moisture_change_leaves_weight"),
        "recipe",
        "moisture_change_pct IS NULL OR moisture_change_pct > -100",
    )
    op.create_index("uq_recipe_identity", "recipe", ["dish_id", "source_id", "label"], unique=True)

    op.add_column(
        "recipe_component",
        sa.Column("retention_code", sa.SmallInteger(), nullable=True),
    )

    op.drop_constraint(
        op.f("ck_food_external_ref_externalsystem"), "food_external_ref", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_food_external_ref_externalsystem"),
        "food_external_ref",
        f"system IN ({_EXTERNAL_SYSTEMS}, 'foundation_ndb')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM food_external_ref WHERE system = 'foundation_ndb'")
    op.drop_constraint(
        op.f("ck_food_external_ref_externalsystem"), "food_external_ref", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_food_external_ref_externalsystem"),
        "food_external_ref",
        f"system IN ({_EXTERNAL_SYSTEMS})",
    )

    op.drop_column("recipe_component", "retention_code")

    op.drop_index("uq_recipe_identity", table_name="recipe")
    op.drop_constraint(op.f("ck_recipe_moisture_change_leaves_weight"), "recipe", type_="check")
    op.drop_column("recipe", "moisture_change_pct")

    op.drop_index(
        "ix_food_alias_normalized_name_trgm",
        table_name="food_alias",
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )

    op.drop_column("food_portion", "position")

    op.drop_constraint(op.f("ck_food_classification_is_cited"), "food", type_="check")
    op.drop_index(op.f("ix_food_classification_source_id"), table_name="food")
    op.drop_constraint(op.f("fk_food_classification_source_id_source"), "food", type_="foreignkey")
    op.drop_column("food", "is_discoverable")
    op.drop_column("food", "classification_source_id")
