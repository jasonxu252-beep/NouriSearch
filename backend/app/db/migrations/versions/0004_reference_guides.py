"""Allow reference values that are label guides, such as the FDA's 2,000 calories

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'dv', 'rda', 'ai', 'ul', 'cdrr'"
_CONSTRAINT = "ck_nutrient_reference_value_referencekind"


def upgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "nutrient_reference_value", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT), "nutrient_reference_value", f"kind IN ({_KINDS}, 'label_guide')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM nutrient_reference_value WHERE kind = 'label_guide'")
    op.drop_constraint(op.f(_CONSTRAINT), "nutrient_reference_value", type_="check")
    op.create_check_constraint(op.f(_CONSTRAINT), "nutrient_reference_value", f"kind IN ({_KINDS})")
