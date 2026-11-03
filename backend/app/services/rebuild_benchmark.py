"""Rebuilds every USDA dish from its ingredients and compares the result with USDA's own value.

This checks the data joins and the arithmetic. It does not check real-world accuracy, because USDA
derived its published values from these same recipes. Each variant answers a different question:

- `plain` sums raw ingredients, reproducing the feasibility measurement in the architecture plan.
- `moisture_adjusted` divides by the cooked weight USDA states, the calculation the product uses.
- `fully_recursive` also ignores published values on nested ingredients, which tests the recursion.

The retention ratios compare published with rebuilt values, split by whether USDA applied a nutrient
retention factor to any ingredient. A ratio below 1 means cooking losses the rebuild does not model.
"""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Nutrient
from app.domain.nutrition.composition import (
    WATER_KEY,
    ComponentNode,
    NutrientBreakdown,
    nutrient_breakdown,
)
from app.domain.nutrition.rebuild import (
    RebuildStats,
    median_or_none,
    summarize_errors,
    without_nested_values,
)
from app.repositories.composition import load_composition, load_facts

# The six nutrients in the plan's table, then two that check the moisture handling directly.
BENCHMARK_NUTRIENTS = (
    "sodium",
    "protein",
    "total_fat",
    "saturated_fat",
    "vitamin_c",
    "fiber",
    "energy",
    "water",
)
_MIN_INGREDIENTS = 3

_DISHES_SQL = text(
    """
    SELECT r.dish_id, r.moisture_change_pct
    FROM recipe r
    JOIN recipe_component rc ON rc.recipe_id = r.id
    WHERE r.is_default AND r.moisture_change_pct IS NOT NULL
    GROUP BY r.id
    HAVING count(*) >= :min_ingredients
    ORDER BY r.dish_id
    """
)


@dataclass(frozen=True, slots=True)
class NutrientRebuild:
    nutrient_key: str
    plain: RebuildStats
    moisture_adjusted: RebuildStats
    fully_recursive: RebuildStats
    retention_ratio_with_factor: float | None
    retention_ratio_without_factor: float | None


@dataclass(slots=True)
class _Collected:
    plain: list[float]
    moisture_adjusted: list[float]
    fully_recursive: list[float]
    ratio_with_factor: list[float]
    ratio_without_factor: list[float]


def _has_retention_factor(components: tuple[ComponentNode, ...]) -> bool:
    return any(node.retention_code is not None for node in components)


def _record_error(errors: list[float], breakdown: NutrientBreakdown) -> None:
    if breakdown.rebuild_error is not None:
        errors.append(breakdown.rebuild_error)


def run_rebuild_benchmark(session: Session) -> list[NutrientRebuild]:
    nutrient_ids = {
        row[0]: row[1]
        for row in session.execute(
            select(Nutrient.key, Nutrient.id).where(Nutrient.key.in_(BENCHMARK_NUTRIENTS))
        )
    }
    collected = {key: _Collected([], [], [], [], []) for key in BENCHMARK_NUTRIENTS}
    wanted = list(nutrient_ids.values())

    for dish_id, moisture in session.execute(_DISHES_SQL, {"min_ingredients": _MIN_INGREDIENTS}):
        moisture_change = float(moisture)
        components = load_composition(session, dish_id, wanted)
        leaves_only = without_nested_values(components)
        facts = load_facts(session, [dish_id], wanted).get(dish_id, {})
        with_factor = _has_retention_factor(components)

        for key, nutrient_id in nutrient_ids.items():
            fact = facts.get(nutrient_id)
            if fact is None or fact.estimated:
                continue
            published = fact.amount_per_100g
            is_water = key == WATER_KEY
            results = collected[key]

            _record_error(results.plain, nutrient_breakdown(components, nutrient_id, published))
            adjusted = nutrient_breakdown(
                components, nutrient_id, published, moisture_change, is_water
            )
            _record_error(results.moisture_adjusted, adjusted)
            _record_error(
                results.fully_recursive,
                nutrient_breakdown(leaves_only, nutrient_id, published, moisture_change, is_water),
            )
            calculated = adjusted.calculated_per_100g
            if calculated and published and not adjusted.is_lower_bound:
                ratios = results.ratio_with_factor if with_factor else results.ratio_without_factor
                ratios.append(published / calculated)

    return [
        NutrientRebuild(
            nutrient_key=key,
            plain=summarize_errors(results.plain),
            moisture_adjusted=summarize_errors(results.moisture_adjusted),
            fully_recursive=summarize_errors(results.fully_recursive),
            retention_ratio_with_factor=median_or_none(results.ratio_with_factor),
            retention_ratio_without_factor=median_or_none(results.ratio_without_factor),
        )
        for key, results in collected.items()
    ]
