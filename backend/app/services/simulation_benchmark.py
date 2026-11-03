"""Tests simulated swaps against swaps USDA itself publishes.

USDA lists many pairs of dishes whose recipes differ by one ingredient, such as the same rice made
with butter or with oil. Simulating that swap on one dish should reach the other dish's published
value. This shows how far a simulated value can be trusted, and whether a recipe's rebuild error
predicts it, which is what the "approximate" label depends on.

Like the rebuild benchmark, this checks the arithmetic against USDA's own figures. It does not check
real-world accuracy, because USDA derived both published values from recipes.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Nutrient
from app.domain.nutrition.composition import WATER_KEY, ComponentNode, nutrient_breakdown
from app.domain.nutrition.simulation import (
    ReplaceEdit,
    ReplacementFood,
    apply_edits,
    published_after_edits,
)
from app.repositories.composition import load_composition, load_facts, load_food_nodes
from app.services.rebuild_benchmark import BENCHMARK_NUTRIENTS

WITHIN = 0.10
# Rebuild-error lines to compare. The product uses one, and the others show why.
ERROR_LINES = (0.05, 0.10, 0.20, 0.50)
# Below this, a value is so small that a percent error says nothing useful.
_MIN_PUBLISHED_SHARE_OF_LARGEST = 0.001

_RECIPES_SQL = text(
    """
    SELECT r.dish_id, r.moisture_change_pct, rc.id, rc.component_food_id, rc.weight_g
    FROM recipe r
    JOIN recipe_component rc ON rc.recipe_id = r.id
    WHERE r.is_default AND r.moisture_change_pct IS NOT NULL AND rc.weight_g IS NOT NULL
    ORDER BY r.dish_id, rc.position
    """
)


@dataclass(frozen=True, slots=True)
class SwapPair:
    dish_id: int
    other_dish_id: int
    component_id: int
    from_food_id: int
    to_food_id: int
    ratio: float


@dataclass(frozen=True, slots=True)
class BucketResult:
    """Simulated values whose recipe rebuilds within, or beyond, one error line."""

    within_line_count: int
    within_line_close: float | None
    beyond_line_count: int
    beyond_line_close: float | None


@dataclass(frozen=True, slots=True)
class SwapBenchmark:
    nutrient_key: str
    pairs: int
    # Share of simulated values within 10% of the other dish's published value.
    close: float | None
    median_error: float | None
    by_line: dict[str, BucketResult]


def find_swap_pairs(session: Session) -> list[SwapPair]:
    """Finds dishes whose recipes match except for one ingredient, at the same moisture change."""
    recipes: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    moisture_of: dict[int, float] = {}
    for dish_id, moisture, component_id, food_id, weight in session.execute(_RECIPES_SQL):
        recipes[dish_id].append((component_id, food_id, float(weight)))
        moisture_of[dish_id] = float(moisture)

    by_shared: dict[tuple[object, ...], list[tuple[int, int, int, float]]] = defaultdict(list)
    for dish_id, components in recipes.items():
        if len(components) < 2:
            continue
        for component_id, food_id, weight in components:
            shared = sorted((food, round(w, 3)) for c, food, w in components if c != component_id)
            key = (moisture_of[dish_id], tuple(shared))
            by_shared[key].append((dish_id, component_id, food_id, weight))

    pairs: list[SwapPair] = []
    for members in by_shared.values():
        for dish_id, component_id, from_food, weight in members:
            for other_dish, _, to_food, other_weight in members:
                if other_dish != dish_id and to_food != from_food:
                    pairs.append(
                        SwapPair(
                            dish_id,
                            other_dish,
                            component_id,
                            from_food,
                            to_food,
                            other_weight / weight,
                        )
                    )
    return pairs


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _close_share(errors: Sequence[float]) -> float | None:
    return sum(error <= WITHIN for error in errors) / len(errors) if errors else None


def run_simulation_benchmark(session: Session) -> list[SwapBenchmark]:
    nutrient_ids = {
        row[0]: row[1]
        for row in session.execute(
            select(Nutrient.key, Nutrient.id).where(Nutrient.key.in_(BENCHMARK_NUTRIENTS))
        )
    }
    wanted = list(nutrient_ids.values())
    pairs = find_swap_pairs(session)

    errors: dict[str, list[tuple[float, float | None]]] = {key: [] for key in nutrient_ids}
    trees: dict[int, tuple[ComponentNode, ...]] = {}
    moistures: dict[int, float] = {
        row[0]: float(row[1])
        for row in session.execute(
            text(
                "SELECT dish_id, moisture_change_pct FROM recipe "
                "WHERE is_default AND moisture_change_pct IS NOT NULL"
            )
        )
    }
    dish_ids = {p.dish_id for p in pairs} | {p.other_dish_id for p in pairs}
    facts = load_facts(session, dish_ids, wanted)
    nodes = load_food_nodes(session, {p.to_food_id for p in pairs}, wanted)

    for pair in pairs:
        components = trees.get(pair.dish_id)
        if components is None:
            components = load_composition(session, pair.dish_id, wanted)
            trees[pair.dish_id] = components
        moisture = moistures[pair.dish_id]
        edit = ReplaceEdit(pair.component_id, (ReplacementFood(pair.to_food_id, pair.ratio),))
        final = apply_edits(components, [edit], nodes).components

        for key, nutrient_id in nutrient_ids.items():
            own = facts.get(pair.dish_id, {}).get(nutrient_id)
            other = facts.get(pair.other_dish_id, {}).get(nutrient_id)
            if own is None or other is None or own.estimated or other.estimated:
                continue
            published = other.amount_per_100g
            if published <= 0:
                continue
            is_water = key == WATER_KEY
            before = nutrient_breakdown(
                components, nutrient_id, own.amount_per_100g, moisture, is_water
            )
            after = nutrient_breakdown(final, nutrient_id, None, moisture, is_water)
            result = published_after_edits(before, after, moisture, is_water)
            if result.amount_per_100g is None:
                continue
            errors[key].append(
                (abs(result.amount_per_100g - published) / published, before.rebuild_error)
            )

    results = []
    for key, rows in errors.items():
        by_line = {}
        for line in ERROR_LINES:
            within = [e for e, rebuild in rows if rebuild is not None and rebuild <= line]
            beyond = [e for e, rebuild in rows if rebuild is None or rebuild > line]
            by_line[f"{line:.2f}"] = BucketResult(
                len(within), _close_share(within), len(beyond), _close_share(beyond)
            )
        results.append(
            SwapBenchmark(
                nutrient_key=key,
                pairs=len(rows),
                close=_close_share([e for e, _ in rows]),
                median_error=_median([e for e, _ in rows]),
                by_line=by_line,
            )
        )
    return results
