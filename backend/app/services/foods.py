"""Baseline food search and the nutrient view of one food.

The rule that matters most here: a value nobody knows reaches the reader as unknown. It never
becomes zero, and it never becomes a number that merely looks complete.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.enums import FoodKind, FoodTypeFilter, NutrientStatus, ProcessingLevel, ValueKind
from app.domain.nutrition.composition import (
    WATER_KEY,
    ComponentNode,
    NutrientFact,
    nutrient_breakdown,
)
from app.domain.text import normalize_name
from app.repositories.composition import (
    DefaultRecipe,
    load_composition,
    load_default_recipe,
    load_facts,
)
from app.repositories.foods import (
    FoodHit,
    NutrientRecord,
    PortionRecord,
    SourceRecord,
    load_food,
    load_nutrient_catalog,
    load_portions,
    load_sources,
    search_food_aliases,
)


class FoodNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class SearchPage:
    query: str
    results: tuple[FoodHit, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class NutrientValue:
    key: str
    name: str
    unit: str
    status: NutrientStatus
    amount_per_100g: float | None
    # How the source obtained the value, which says whether a zero was measured or assumed.
    value_kind: ValueKind | None
    derivation: str | None
    # Null where no Daily Value exists, such as total sugars.
    daily_value: float | None
    daily_value_source_key: str | None
    source_keys: tuple[str, ...]
    # Ingredients that kept a rebuilt value from being complete.
    missing_ingredients: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FoodDetail:
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
    recipe_label: str | None
    portions: tuple[PortionRecord, ...]
    nutrients: tuple[NutrientValue, ...]
    sources: tuple[SourceRecord, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedValue:
    status: NutrientStatus
    amount: float | None = None
    kind: ValueKind | None = None
    derivation: str | None = None
    source_ids: frozenset[int] = frozenset()
    gaps: tuple[str, ...] = ()


def search_foods(
    session: Session, query: str, food_type: FoodTypeFilter, limit: int, offset: int
) -> SearchPage:
    normalized = normalize_name(query)
    if not normalized:
        return SearchPage(normalized, (), False)
    # One extra row shows whether another page exists, without counting every match.
    hits = search_food_aliases(session, normalized, food_type, limit + 1, offset)
    return SearchPage(normalized, tuple(hits[:limit]), len(hits) > limit)


def _resolve_from_recipe(
    nutrient: NutrientRecord, components: tuple[ComponentNode, ...], recipe: DefaultRecipe
) -> _ResolvedValue:
    """Rebuilds a value the food does not state itself, keeping track of what is missing."""
    breakdown = nutrient_breakdown(
        components,
        nutrient.id,
        moisture_change_pct=recipe.moisture_change_pct,
        is_water=nutrient.key == WATER_KEY,
    )
    gaps = (*breakdown.missing_names, *breakdown.unquantified_names)
    calculated = breakdown.calculated_per_100g
    # "At least 0" says nothing and reads like a zero, so a partial total of zero stays unknown.
    if calculated is None or (breakdown.is_lower_bound and calculated <= 0):
        return _ResolvedValue(NutrientStatus.UNKNOWN, gaps=gaps)
    return _ResolvedValue(
        NutrientStatus.LOWER_BOUND if breakdown.is_lower_bound else NutrientStatus.CALCULATED,
        amount=calculated,
        kind=ValueKind.CALCULATED,
        source_ids=frozenset(s for c in breakdown.contributions for s in c.source_ids),
        gaps=gaps,
    )


def _resolve(
    nutrient: NutrientRecord,
    fact: NutrientFact | None,
    components: tuple[ComponentNode, ...],
    recipe: DefaultRecipe | None,
) -> _ResolvedValue:
    if fact is not None:
        return _ResolvedValue(
            NutrientStatus.ESTIMATED if fact.estimated else NutrientStatus.KNOWN,
            amount=fact.amount_per_100g,
            kind=fact.value_kind,
            derivation=fact.derivation,
            source_ids=frozenset({fact.source_id}),
        )
    if recipe is None or not components:
        return _ResolvedValue(NutrientStatus.UNKNOWN)
    return _resolve_from_recipe(nutrient, components, recipe)


def food_detail(session: Session, food_id: int) -> FoodDetail:
    food = load_food(session, food_id)
    if food is None:
        raise FoodNotFound(food_id)

    catalog = load_nutrient_catalog(session)
    facts = load_facts(session, [food_id]).get(food_id, {})
    recipe = load_default_recipe(session, food_id)
    unstated = [nutrient.id for nutrient in catalog if nutrient.id not in facts]
    components = load_composition(session, food_id, unstated) if recipe and unstated else ()

    resolved = {n.id: _resolve(n, facts.get(n.id), components, recipe) for n in catalog}

    cited = {food.source_id}
    if food.classification_source_id is not None:
        cited.add(food.classification_source_id)
    for nutrient in catalog:
        cited |= resolved[nutrient.id].source_ids
        if nutrient.daily_value_source_id is not None:
            cited.add(nutrient.daily_value_source_id)
    sources = load_sources(session, sorted(cited))
    keys = {source.id: source.key for source in sources}

    return FoodDetail(
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
        recipe_label=recipe.label if recipe else None,
        portions=tuple(load_portions(session, food_id)),
        nutrients=tuple(
            NutrientValue(
                key=nutrient.key,
                name=nutrient.name,
                unit=nutrient.unit,
                status=value.status,
                amount_per_100g=value.amount,
                value_kind=value.kind,
                derivation=value.derivation,
                daily_value=nutrient.daily_value,
                daily_value_source_key=(
                    keys[nutrient.daily_value_source_id] if nutrient.daily_value_source_id else None
                ),
                source_keys=tuple(sorted(keys[s] for s in value.source_ids)),
                missing_ingredients=value.gaps,
            )
            for nutrient in catalog
            for value in (resolved[nutrient.id],)
        ),
        sources=tuple(sources),
    )
