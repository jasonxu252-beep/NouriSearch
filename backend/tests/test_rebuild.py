"""The arithmetic behind the rebuild benchmark."""

import pytest

from app.domain.enums import ValueKind
from app.domain.nutrition.composition import ComponentNode, NutrientFact
from app.domain.nutrition.rebuild import (
    median_or_none,
    summarize_errors,
    without_nested_values,
)


def test_summary_of_errors() -> None:
    stats = summarize_errors([0.01, 0.05, 0.10, 0.20, 0.50])
    assert stats.dishes == 5
    assert stats.median_error == 0.10
    assert stats.within_10_percent == pytest.approx(0.6)
    assert stats.within_25_percent == pytest.approx(0.8)


def test_no_errors_means_no_figures_rather_than_perfect_ones() -> None:
    stats = summarize_errors([])
    assert stats.dishes == 0
    assert stats.median_error is None
    assert stats.within_10_percent is None


def test_median_of_nothing_is_none() -> None:
    assert median_or_none([]) is None
    assert median_or_none([1.0, 3.0]) == 2.0


def test_values_are_removed_only_from_ingredients_with_their_own_recipe() -> None:
    fact = {1: NutrientFact(100.0, 1, ValueKind.ANALYTICAL)}
    leaf = ComponentNode(1, 1, "Salt", 1.0, fact)
    nested = ComponentNode(2, 2, "Sauce", 10.0, fact, (leaf,))
    deep = ComponentNode(3, 3, "Stew", 10.0, fact, (nested,))

    stripped = without_nested_values((leaf, deep))

    assert stripped[0].facts == fact
    assert stripped[1].facts == {}
    assert stripped[1].children[0].facts == {}
    assert stripped[1].children[0].children[0].facts == fact
