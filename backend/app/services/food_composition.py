"""Everything the food detail page needs, in one response, so the page can respond instantly.

Ingredients, nutrients, who contributes what, and the marks for every serving all arrive together.
Switching a serving or a highlight then needs no further request. A simulation returns the same
shape with its changes applied, and writes nothing.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.enums import (
    FoodKind,
    NutrientMark,
    NutrientStatus,
    ProcessingLevel,
    ValueKind,
)
from app.domain.nutrition.composition import (
    WATER_KEY,
    ComponentNode,
    ContributionStatus,
    NutrientBreakdown,
    NutrientFact,
    cooked_weight,
    nutrient_breakdown,
)
from app.domain.nutrition.simulation import published_without
from app.domain.rules.engine import Conclusion, Rule, ServingFact, evaluate, nutrient_mark
from app.domain.rules.percent_daily_value import (
    HIGH_PERCENT_DAILY_VALUE,
    high_percent_daily_value,
)
from app.repositories.composition import load_composition, load_default_recipe, load_facts
from app.repositories.foods import (
    FoodImageRecord,
    IngredientAnnotation,
    NutrientRecord,
    PortionRecord,
    SourceRecord,
    load_food,
    load_food_images,
    load_ingredient_annotations,
    load_nutrient_catalog,
    load_portions,
    load_sources,
)
from app.services.foods import FoodNotFound, ResolvedValue, resolve_value

RULES: tuple[Rule, ...] = (high_percent_daily_value,)

PER_100G_KEY = "per-100g"


class InvalidEdit(ValueError):
    """An edit that cannot apply to this food, such as removing an ingredient it does not have."""


@dataclass(frozen=True, slots=True)
class Serving:
    key: str
    label: str
    grams: float
    is_household_measure: bool
    is_default: bool


@dataclass(frozen=True, slots=True)
class IngredientRow:
    component_id: int
    food_id: int
    name: str
    kind: FoodKind
    weight_g: float | None
    # Share of the raw recipe weight, which says nothing about any nutrient.
    weight_share: float | None
    has_own_recipe: bool
    excluded: bool
    considerations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContributionCell:
    nutrient_key: str
    component_id: int
    status: ContributionStatus
    amount: float | None
    share: float | None
    estimated: bool


@dataclass(frozen=True, slots=True)
class NutrientRow:
    key: str
    name: str
    unit: str
    category: str
    direction: str
    status: NutrientStatus
    amount_per_100g: float | None
    # The value before any edit, and how far the edit moved it. Null when nothing was edited.
    base_amount_per_100g: float | None
    delta_per_100g: float | None
    # The recipe does not fully explain the published value, so an edit is only an approximation.
    approximate: bool
    value_kind: ValueKind | None
    derivation: str | None
    daily_value: float | None
    daily_value_source_key: str | None
    source_keys: tuple[str, ...]
    missing_ingredients: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NutrientServingValue:
    key: str
    amount: float | None
    percent_daily_value: float | None
    mark: NutrientMark


@dataclass(frozen=True, slots=True)
class ServingEvaluation:
    serving_key: str
    nutrients: tuple[NutrientServingValue, ...]
    conclusions: tuple[Conclusion, ...]


@dataclass(frozen=True, slots=True)
class RecipeSummary:
    label: str
    moisture_change_pct: float
    raw_weight_g: float | None
    cooked_weight_g: float | None


@dataclass(frozen=True, slots=True)
class FoodComposition:
    id: int
    slug: str
    name: str
    description: str | None
    kind: FoodKind
    food_group_key: str | None
    food_group_name: str | None
    processing_level: ProcessingLevel
    processing_level_source_key: str | None
    source_key: str
    is_modified: bool
    high_percent_daily_value: float
    images: tuple[FoodImageRecord, ...]
    recipe: RecipeSummary | None
    servings: tuple[Serving, ...]
    ingredients: tuple[IngredientRow, ...]
    nutrients: tuple[NutrientRow, ...]
    contributions: tuple[ContributionCell, ...]
    evaluations: tuple[ServingEvaluation, ...]
    sources: tuple[SourceRecord, ...]


def build_servings(portions: Sequence[PortionRecord]) -> tuple[Serving, ...]:
    """The first household measure is the default, and 100 g is always offered.

    With no household measure, the page labels its values per 100 g rather than treating a
    placeholder like "Quantity not specified" as a serving someone would recognize.
    """
    default = next((i for i, p in enumerate(portions) if p.is_household_measure), None)
    servings = [
        Serving(f"portion-{i}", p.description, p.gram_weight, p.is_household_measure, i == default)
        for i, p in enumerate(portions)
    ]
    servings.append(Serving(PER_100G_KEY, "100 g", 100.0, False, default is None))
    return tuple(servings)


def _evaluate_serving(
    serving: Serving,
    catalog: Sequence[NutrientRecord],
    rows: Mapping[str, NutrientRow],
) -> ServingEvaluation:
    facts = [
        ServingFact(
            nutrient_key=nutrient.key,
            direction=nutrient.direction,
            status=rows[nutrient.key].status,
            amount_per_100g=rows[nutrient.key].amount_per_100g,
            unit=nutrient.unit,
            daily_value=nutrient.daily_value,
            daily_value_source_key=rows[nutrient.key].daily_value_source_key,
            value_source_keys=rows[nutrient.key].source_keys,
            missing=rows[nutrient.key].missing_ingredients,
            serving_key=serving.key,
            serving_label=serving.label,
            serving_g=serving.grams,
        )
        for nutrient in catalog
    ]
    conclusions = evaluate(facts, RULES)
    return ServingEvaluation(
        serving_key=serving.key,
        nutrients=tuple(
            NutrientServingValue(
                key=fact.nutrient_key,
                amount=fact.amount_per_serving,
                percent_daily_value=fact.percent_daily_value,
                mark=nutrient_mark(fact, conclusions),
            )
            for fact in facts
        ),
        conclusions=conclusions,
    )


def _ingredient_rows(
    components: Sequence[ComponentNode],
    excluded: Collection[int],
    annotations: Mapping[int, IngredientAnnotation],
) -> tuple[IngredientRow, ...]:
    weights = [node.weight_g for node in components]
    total = sum(w for w in weights if w is not None) if all(w is not None for w in weights) else 0
    rows = []
    for node in components:
        annotation = annotations.get(node.food_id)
        rows.append(
            IngredientRow(
                component_id=node.component_id,
                food_id=node.food_id,
                name=node.name,
                kind=annotation.kind if annotation else FoodKind.BASIC,
                weight_g=node.weight_g,
                weight_share=node.weight_g / total if total and node.weight_g else None,
                has_own_recipe=bool(node.children),
                excluded=node.component_id in excluded,
                considerations=annotation.considerations if annotation else (),
            )
        )
    return tuple(rows)


def _contribution_cells(key: str, breakdown: NutrientBreakdown) -> list[ContributionCell]:
    return [
        ContributionCell(
            nutrient_key=key,
            component_id=c.component.component_id,
            status=c.status,
            amount=c.amount,
            share=c.share,
            estimated=c.estimated,
        )
        for c in breakdown.contributions
    ]


def _resolve_edited(
    nutrient: NutrientRecord,
    fact: NutrientFact | None,
    full: NutrientBreakdown | None,
    remaining: tuple[ComponentNode, ...],
    excluded: Collection[int],
    moisture: float,
) -> tuple[ResolvedValue, bool]:
    """A stated value is adjusted by what left. Anything else is rebuilt from what stays."""
    if fact is not None and not fact.estimated and full is not None:
        simulated = published_without(full, excluded, moisture, nutrient.key == WATER_KEY)
        return (
            ResolvedValue(
                simulated.status,
                amount=simulated.amount_per_100g,
                kind=ValueKind.CALCULATED if simulated.amount_per_100g is not None else None,
                source_ids=simulated.source_ids | {fact.source_id},
                gaps=simulated.gaps,
            ),
            simulated.approximate,
        )
    breakdown = nutrient_breakdown(
        remaining,
        nutrient.id,
        moisture_change_pct=moisture,
        is_water=nutrient.key == WATER_KEY,
    )
    gaps = (*breakdown.missing_names, *breakdown.unquantified_names)
    calculated = breakdown.calculated_per_100g
    if calculated is None or (breakdown.is_lower_bound and calculated <= 0):
        return ResolvedValue(NutrientStatus.UNKNOWN, gaps=gaps), False
    status = NutrientStatus.LOWER_BOUND if breakdown.is_lower_bound else NutrientStatus.CALCULATED
    return (
        ResolvedValue(
            status,
            amount=calculated,
            kind=ValueKind.CALCULATED,
            source_ids=frozenset(s for c in breakdown.contributions for s in c.source_ids),
            gaps=gaps,
        ),
        False,
    )


def food_composition(
    session: Session, food_id: int, excluded_component_ids: Collection[int] = ()
) -> FoodComposition:
    food = load_food(session, food_id)
    if food is None:
        raise FoodNotFound(food_id)

    excluded = frozenset(excluded_component_ids)
    catalog = load_nutrient_catalog(session)
    facts = load_facts(session, [food_id]).get(food_id, {})
    recipe = load_default_recipe(session, food_id)
    components = load_composition(session, food_id) if recipe else ()
    moisture = recipe.moisture_change_pct if recipe else 0.0

    known_components = {node.component_id for node in components}
    if excluded - known_components:
        raise InvalidEdit(
            f"Food {food_id} has no ingredient {sorted(excluded - known_components)}."
        )
    if excluded and excluded == known_components:
        raise InvalidEdit("A recipe cannot exclude every ingredient.")
    remaining = tuple(node for node in components if node.component_id not in excluded)

    source_ids: set[int] = {food.source_id}
    if food.classification_source_id is not None:
        source_ids.add(food.classification_source_id)

    resolved: dict[str, ResolvedValue] = {}
    base: dict[str, ResolvedValue] = {}
    approximate: dict[str, bool] = {}
    contributions: list[ContributionCell] = []
    for nutrient in catalog:
        fact = facts.get(nutrient.id)
        is_water = nutrient.key == WATER_KEY
        published = fact.amount_per_100g if fact and not fact.estimated else None
        full = (
            nutrient_breakdown(components, nutrient.id, published, moisture, is_water)
            if components
            else None
        )
        base[nutrient.key] = resolve_value(nutrient, fact, components, recipe)
        if excluded:
            resolved[nutrient.key], approximate[nutrient.key] = _resolve_edited(
                nutrient, fact, full, remaining, excluded, moisture
            )
        else:
            resolved[nutrient.key], approximate[nutrient.key] = base[nutrient.key], False
        if remaining:
            shown = nutrient_breakdown(remaining, nutrient.id, None, moisture, is_water)
            contributions.extend(_contribution_cells(nutrient.key, shown))
        source_ids |= resolved[nutrient.key].source_ids
        if nutrient.daily_value_source_id is not None:
            source_ids.add(nutrient.daily_value_source_id)

    images = load_food_images(session, food_id)
    source_ids |= {image.source_id for image in images}
    sources = load_sources(session, sorted(source_ids), [HIGH_PERCENT_DAILY_VALUE.source_key])
    keys = {source.id: source.key for source in sources}

    rows = {}
    for nutrient in catalog:
        value = resolved[nutrient.key]
        before = base[nutrient.key].amount
        rows[nutrient.key] = NutrientRow(
            key=nutrient.key,
            name=nutrient.name,
            unit=nutrient.unit,
            category=nutrient.category.value,
            direction=nutrient.direction.value,
            status=value.status,
            amount_per_100g=value.amount,
            base_amount_per_100g=before if excluded else None,
            delta_per_100g=(
                value.amount - before
                if excluded and value.amount is not None and before is not None
                else None
            ),
            approximate=approximate[nutrient.key],
            value_kind=value.kind,
            derivation=value.derivation,
            daily_value=nutrient.daily_value,
            daily_value_source_key=(
                keys[nutrient.daily_value_source_id] if nutrient.daily_value_source_id else None
            ),
            source_keys=tuple(sorted(keys[s] for s in value.source_ids)),
            missing_ingredients=value.gaps,
        )

    servings = build_servings(load_portions(session, food_id))
    weights = [node.weight_g for node in remaining]
    raw_weight = (
        sum(w for w in weights if w is not None)
        if weights and all(w is not None for w in weights)
        else None
    )
    annotations = load_ingredient_annotations(session, [node.food_id for node in components])

    return FoodComposition(
        id=food.id,
        slug=food.slug,
        name=food.name,
        description=food.description,
        kind=food.kind,
        food_group_key=food.food_group_key,
        food_group_name=food.food_group_name,
        processing_level=food.processing_level,
        processing_level_source_key=(
            keys[food.classification_source_id] if food.classification_source_id else None
        ),
        source_key=keys[food.source_id],
        is_modified=bool(excluded),
        high_percent_daily_value=HIGH_PERCENT_DAILY_VALUE.value,
        images=tuple(images),
        recipe=(
            RecipeSummary(
                label=recipe.label,
                moisture_change_pct=moisture,
                raw_weight_g=raw_weight,
                cooked_weight_g=cooked_weight(raw_weight, moisture) if raw_weight else None,
            )
            if recipe
            else None
        ),
        servings=servings,
        ingredients=_ingredient_rows(components, excluded, annotations),
        nutrients=tuple(rows[nutrient.key] for nutrient in catalog),
        contributions=tuple(contributions),
        evaluations=tuple(_evaluate_serving(s, catalog, rows) for s in servings),
        sources=tuple(sources),
    )
