"""Nutrient arithmetic over a dish's composition. Pure: no database, no network.

Missing data is the central concern. An ingredient with no value contributes unknown, not zero,
and a total that omits anything is reported as a lower bound.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.domain.enums import ValueKind


@dataclass(frozen=True, slots=True)
class NutrientFact:
    amount_per_100g: float
    source_id: int
    value_kind: ValueKind
    # True when the value is borrowed from a similar food through a nutrient proxy.
    estimated: bool = False


@dataclass(frozen=True, slots=True)
class ComponentNode:
    """One ingredient in a recipe, with its own ingredients when it has a recipe too."""

    component_id: int
    food_id: int
    name: str
    weight_g: float | None
    facts: Mapping[int, NutrientFact]
    children: tuple["ComponentNode", ...] = ()


class ContributionStatus(StrEnum):
    # The ingredient has its own value for this nutrient.
    KNOWN = "known"
    # It has no value of its own, and its full recipe supplied one.
    CALCULATED = "calculated"
    # Its recipe supplied part of a value, so the amount is a lower bound.
    PARTIAL = "partial"
    NO_DATA = "no_data"
    NO_QUANTITY = "no_quantity"


COUNTED_STATUSES = frozenset(
    {ContributionStatus.KNOWN, ContributionStatus.CALCULATED, ContributionStatus.PARTIAL}
)


@dataclass(frozen=True, slots=True)
class Contribution:
    component: ComponentNode
    status: ContributionStatus
    amount: float | None
    share: float | None
    source_ids: frozenset[int]
    estimated: bool


@dataclass(frozen=True, slots=True)
class NutrientBreakdown:
    nutrient_id: int
    contributions: tuple[Contribution, ...]
    known_total: float
    recipe_weight_g: float | None
    calculated_per_100g: float | None
    published_per_100g: float | None
    is_lower_bound: bool

    @property
    def per_100g(self) -> float | None:
        """The value to display: a published figure wins over one rebuilt from ingredients."""
        if self.published_per_100g is not None:
            return self.published_per_100g
        return self.calculated_per_100g

    @property
    def rebuild_error(self) -> float | None:
        """How far the rebuilt value is from the published one, as a fraction of published."""
        if (
            self.published_per_100g is None
            or self.published_per_100g == 0
            or self.calculated_per_100g is None
            or self.is_lower_bound
        ):
            return None
        return abs(self.calculated_per_100g - self.published_per_100g) / self.published_per_100g

    @property
    def missing_names(self) -> tuple[str, ...]:
        return tuple(
            c.component.name
            for c in self.contributions
            if c.status in (ContributionStatus.NO_DATA, ContributionStatus.PARTIAL)
        )

    @property
    def unquantified_names(self) -> tuple[str, ...]:
        return tuple(
            c.component.name
            for c in self.contributions
            if c.status is ContributionStatus.NO_QUANTITY
        )


def _contribution(node: ComponentNode, nutrient_id: int) -> Contribution:
    if node.weight_g is None:
        return Contribution(node, ContributionStatus.NO_QUANTITY, None, None, frozenset(), False)

    fact = node.facts.get(nutrient_id)
    if fact is not None:
        return Contribution(
            node,
            ContributionStatus.KNOWN,
            node.weight_g * fact.amount_per_100g / 100,
            None,
            frozenset({fact.source_id}),
            fact.estimated,
        )

    if not node.children:
        return Contribution(node, ContributionStatus.NO_DATA, None, None, frozenset(), False)

    children = [_contribution(child, nutrient_id) for child in node.children]
    weights = [child.weight_g for child in node.children]
    if any(w is None for w in weights):
        return Contribution(node, ContributionStatus.NO_DATA, None, None, frozenset(), False)

    recipe_weight = sum(w for w in weights if w is not None)
    counted = [c for c in children if c.status in COUNTED_STATUSES and c.amount is not None]
    if not counted or recipe_weight <= 0:
        return Contribution(node, ContributionStatus.NO_DATA, None, None, frozenset(), False)

    scale = node.weight_g / recipe_weight
    complete = all(
        c.status in (ContributionStatus.KNOWN, ContributionStatus.CALCULATED) for c in children
    )
    return Contribution(
        node,
        ContributionStatus.CALCULATED if complete else ContributionStatus.PARTIAL,
        sum(c.amount for c in counted if c.amount is not None) * scale,
        None,
        frozenset().union(*(c.source_ids for c in counted)),
        any(c.estimated for c in counted),
    )


def nutrient_breakdown(
    components: Sequence[ComponentNode],
    nutrient_id: int,
    published_per_100g: float | None = None,
) -> NutrientBreakdown:
    """Attributes a nutrient to each ingredient, largest contributor first."""
    raw = [_contribution(node, nutrient_id) for node in components]
    known_total = sum(c.amount for c in raw if c.amount is not None)

    with_shares = [
        Contribution(
            c.component,
            c.status,
            c.amount,
            (c.amount / known_total) if c.amount is not None and known_total > 0 else None,
            c.source_ids,
            c.estimated,
        )
        for c in raw
    ]
    # Known amounts first, largest to smallest. Unknowns keep their recipe order at the end.
    ordered = sorted(
        with_shares,
        key=lambda c: (c.amount is None, -(c.amount or 0.0)),
    )

    weights = [node.weight_g for node in components]
    recipe_weight = sum(w for w in weights if w is not None) if weights and all(weights) else None
    is_lower_bound = any(c.status not in _COMPLETE_STATUSES for c in raw)
    calculated = (
        known_total / recipe_weight * 100
        if recipe_weight and any(c.amount is not None for c in raw)
        else None
    )
    return NutrientBreakdown(
        nutrient_id=nutrient_id,
        contributions=tuple(ordered),
        known_total=known_total,
        recipe_weight_g=recipe_weight,
        calculated_per_100g=calculated,
        published_per_100g=published_per_100g,
        is_lower_bound=is_lower_bound,
    )


_COMPLETE_STATUSES = frozenset({ContributionStatus.KNOWN, ContributionStatus.CALCULATED})


def adjusted_per_100g(
    published_per_100g: float,
    original_weight_g: float,
    new_weight_g: float,
    amount_delta: float,
) -> float:
    """Applies an ingredient edit as a change to the published value.

    Working from the published figure keeps the source's cooking and moisture adjustments, which a
    plain sum of raw ingredients would lose. The result cannot go below zero.
    """
    if original_weight_g <= 0 or new_weight_g <= 0:
        raise ValueError("Recipe weights must be positive.")
    total = published_per_100g * original_weight_g / 100 + amount_delta
    return max(total, 0.0) / new_weight_g * 100
