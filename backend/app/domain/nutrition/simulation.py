"""What happens to a published value when ingredients leave a recipe. Pure: no database, no network.

Milestone 4 needs removal for the ingredient checkboxes. Milestone 5 adds replace, scale, and add.
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.domain.enums import NutrientStatus
from app.domain.nutrition.composition import (
    ContributionStatus,
    NutrientBreakdown,
    adjusted_per_100g,
    cooked_weight,
)

# A rebuild further than this from the published value means the recipe does not fully explain it,
# so an edit to that recipe is shown as approximate. Ten percent is a starting point, the line the
# rebuild benchmark reports, and milestone 5 tests it against hand-computed fixtures.
APPROXIMATE_ABOVE_REBUILD_ERROR = 0.10

_COUNTABLE = (ContributionStatus.KNOWN, ContributionStatus.CALCULATED)


@dataclass(frozen=True, slots=True)
class SimulatedValue:
    status: NutrientStatus
    amount_per_100g: float | None
    approximate: bool
    source_ids: frozenset[int]
    gaps: tuple[str, ...]


def published_without(
    breakdown: NutrientBreakdown,
    excluded_component_ids: Collection[int],
    moisture_change_pct: float = 0.0,
    is_water: bool = False,
) -> SimulatedValue:
    """Subtracts excluded ingredients from a published value, keeping USDA's cooking adjustments.

    Nothing can be subtracted without knowing how much an ingredient held. If an excluded ingredient
    has no value or no stated weight, the new value is unknown and the ingredient is named.
    """
    published = breakdown.published_per_100g
    if published is None:
        raise ValueError("This calculation needs a published value.")

    removed = [
        c for c in breakdown.contributions if c.component.component_id in excluded_component_ids
    ]
    unknown = tuple(
        c.component.name for c in removed if c.status not in _COUNTABLE or c.amount is None
    )
    raw_weight = breakdown.recipe_weight_g
    if unknown or raw_weight is None:
        return SimulatedValue(NutrientStatus.UNKNOWN, None, False, frozenset(), unknown)

    new_weight = raw_weight - sum(c.component.weight_g or 0.0 for c in removed)
    amount_delta = -sum(c.amount or 0.0 for c in removed)
    if is_water:
        # A smaller batch also loses or gains proportionally less water while it cooks.
        amount_delta += moisture_change_pct / 100 * (new_weight - raw_weight)

    total = published * cooked_weight(raw_weight, moisture_change_pct) / 100 + amount_delta
    error = breakdown.rebuild_error
    changed = any(c.amount for c in removed)
    return SimulatedValue(
        NutrientStatus.CALCULATED,
        adjusted_per_100g(published, raw_weight, new_weight, amount_delta, moisture_change_pct),
        # Subtracting more than the published value holds means the recipe and value disagree.
        approximate=total < 0
        or (changed and (error is None or error > APPROXIMATE_ABOVE_REBUILD_ERROR)),
        source_ids=frozenset(s for c in breakdown.contributions for s in c.source_ids),
        gaps=(),
    )
