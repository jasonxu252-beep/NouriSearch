"""Measures how closely dishes rebuild from their ingredients. Pure: no database, no network."""

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from app.domain.nutrition.composition import ComponentNode


@dataclass(frozen=True, slots=True)
class RebuildStats:
    dishes: int
    median_error: float | None
    within_10_percent: float | None
    within_25_percent: float | None


def summarize_errors(errors: Sequence[float]) -> RebuildStats:
    """Errors are fractions of the published value, so 0.1 means 10% away."""
    if not errors:
        return RebuildStats(0, None, None, None)
    count = len(errors)
    return RebuildStats(
        dishes=count,
        median_error=statistics.median(errors),
        within_10_percent=sum(error <= 0.10 for error in errors) / count,
        within_25_percent=sum(error <= 0.25 for error in errors) / count,
    )


def median_or_none(values: Iterable[float]) -> float | None:
    items = list(values)
    return statistics.median(items) if items else None


def without_nested_values(components: Sequence[ComponentNode]) -> tuple[ComponentNode, ...]:
    """Removes the value from every ingredient that has a recipe.

    A nested ingredient's published value normally wins over its recipe. Removing it forces the sum
    down to the leaf ingredients, which tests the recursion itself against USDA's numbers.
    """
    return tuple(
        replace(
            node,
            facts={} if node.children else node.facts,
            children=without_nested_values(node.children),
        )
        for node in components
    )
