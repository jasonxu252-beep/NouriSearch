"""Add ingredient roles, how well a swap fits, and diet classifications

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'added_sugar_source', 'artificial_color', 'preserved'"
_DIET_KINDS = "'meat_or_fish', 'animal_derived'"
_CONSTRAINT = "ck_food_classification_foodclassificationkind"


def upgrade() -> None:
    op.create_table(
        "food_role",
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("is_offered", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["food_id"], ["food.id"], name=op.f("fk_food_role_food_id_food"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["ingredient_role.id"],
            name=op.f("fk_food_role_role_id_ingredient_role"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_food_role_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("food_id", "role_id", "source_id", name=op.f("pk_food_role")),
    )
    op.create_index(op.f("ix_food_role_role_id"), "food_role", ["role_id"])
    op.create_index(op.f("ix_food_role_source_id"), "food_role", ["source_id"])

    op.add_column("substitution_option", sa.Column("culinary_fit", sa.SmallInteger()))
    op.create_check_constraint(
        op.f("ck_substitution_option_culinary_fit_in_range"),
        "substitution_option",
        "culinary_fit IS NULL OR culinary_fit BETWEEN 1 AND 5",
    )

    op.drop_constraint(op.f(_CONSTRAINT), "food_classification", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT), "food_classification", f"classification IN ({_KINDS}, {_DIET_KINDS})"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM food_classification WHERE classification IN ({_DIET_KINDS})")
    op.drop_constraint(op.f(_CONSTRAINT), "food_classification", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT), "food_classification", f"classification IN ({_KINDS})"
    )
    op.drop_constraint(
        op.f("ck_substitution_option_culinary_fit_in_range"), "substitution_option", type_="check"
    )
    op.drop_column("substitution_option", "culinary_fit")
    op.drop_index(op.f("ix_food_role_source_id"), table_name="food_role")
    op.drop_index(op.f("ix_food_role_role_id"), table_name="food_role")
    op.drop_table("food_role")
