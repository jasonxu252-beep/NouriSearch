"""Everything the food detail page needs, in one response, so the page can respond instantly.

Ingredients, nutrients, who contributes what, and the marks for every serving all arrive together.
Switching a serving or a highlight then needs no further request. A simulation returns the same
shape with its changes applied, and writes nothing.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.allergens import allergens_in_name, merge_findings
from app.domain.enums import (
    AllergenRelation,
    FoodKind,
    NutrientMark,
    NutrientStatus,
    ProcessingLevel,
    ValueKind,
    Verification,
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
from app.domain.nutrition.simulation import (
    AddEdit,
    Edit,
    EditedIngredient,
    EditedRecipe,
    IngredientEdit,
    InvalidEdit,
    ReplaceEdit,
    apply_edits,
    published_after_edits,
)
from app.domain.rules.engine import Conclusion, Rule, ServingFact, evaluate, nutrient_mark
from app.domain.rules.percent_daily_value import (
    HIGH_PERCENT_DAILY_VALUE,
    high_percent_daily_value,
)
from app.repositories.composition import (
    load_composition,
    load_default_recipe,
    load_facts,
    load_food_nodes,
)
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
from app.repositories.substitutions import (
    AllergenFinding,
    load_allergen_findings,
    load_allergen_names,
)
from app.services.foods import FoodNotFound, ResolvedValue, resolve_value

RULES: tuple[Rule, ...] = (high_percent_daily_value,)

PER_100G_KEY = "per-100g"


@dataclass(frozen=True, slots=True)
class Serving:
    key: str
    label: str
    grams: float
    is_household_measure: bool
    is_default: bool


@dataclass(frozen=True, slots=True)
class IngredientAllergen:
    key: str
    relation: AllergenRelation
    verification: Verification


@dataclass(frozen=True, slots=True)
class DishAllergen:
    """An allergen found in this dish, and the ingredients it was found in."""

    key: str
    name: str
    relation: AllergenRelation
    verification: Verification
    ingredient_names: tuple[str, ...]


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
    # True when the ingredient has left the recipe, whether removed or replaced.
    excluded: bool
    edit: IngredientEdit
    # The weight before a scale edit. Null for an ingredient the edits brought in.
    original_weight_g: float | None
    replaces_component_id: int | None
    allergens: tuple[IngredientAllergen, ...]
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
    # What names and recipes reveal, after any edits. Anything not listed is simply not known.
    allergens: tuple[DishAllergen, ...]
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
    edited: EditedRecipe,
    annotations: Mapping[int, IngredientAnnotation],
    allergens: Mapping[int, Mapping[str, AllergenFinding]],
) -> tuple[IngredientRow, ...]:
    weights = [row.node.weight_g for row in edited.rows if row.is_in_recipe]
    total = sum(w for w in weights if w is not None) if all(w is not None for w in weights) else 0
    return tuple(_ingredient_row(row, total, annotations, allergens) for row in edited.rows)


def _ingredient_row(
    row: EditedIngredient,
    total_weight: float,
    annotations: Mapping[int, IngredientAnnotation],
    allergens: Mapping[int, Mapping[str, AllergenFinding]],
) -> IngredientRow:
    node = row.node
    annotation = annotations.get(node.food_id)
    return IngredientRow(
        component_id=node.component_id,
        food_id=node.food_id,
        name=node.name,
        kind=annotation.kind if annotation else FoodKind.BASIC,
        weight_g=node.weight_g,
        weight_share=(
            node.weight_g / total_weight
            if total_weight and node.weight_g and row.is_in_recipe
            else None
        ),
        has_own_recipe=bool(node.children),
        excluded=not row.is_in_recipe,
        edit=row.edit,
        original_weight_g=row.original_weight_g,
        replaces_component_id=row.replaces_component_id,
        allergens=tuple(
            IngredientAllergen(key, finding.relation, finding.verification)
            for key, finding in sorted(allergens.get(node.food_id, {}).items())
        ),
        considerations=annotation.considerations if annotation else (),
    )


def _dish_allergens(
    dish_id: int,
    dish_name: str,
    edited: EditedRecipe,
    findings: Mapping[int, Mapping[str, AllergenFinding]],
    names: Mapping[str, str],
) -> tuple[DishAllergen, ...]:
    """What is known about the dish as it now stands.

    A dish's own stored findings came from its original recipe, so an edited dish is worked out
    again from its name and its current ingredients. Removing the only cheese can drop milk, unless
    the dish's name still says cheese.
    """
    components = edited.components
    own = {key: finding.relation for key, finding in findings.get(dish_id, {}).items()}
    relations = (
        merge_findings(
            [
                allergens_in_name(dish_name),
                *(
                    {key: f.relation for key, f in findings.get(node.food_id, {}).items()}
                    for node in components
                ),
            ]
        )
        if edited.is_modified
        else own
    )
    rows = []
    for key, name in names.items():
        relation = relations.get(key)
        if relation is None:
            continue
        sources = [
            findings[node.food_id][key]
            for node in components
            if key in findings.get(node.food_id, {})
        ]
        stored = findings.get(dish_id, {}).get(key)
        verification = (
            Verification.TYPICAL
            if any(s.verification is Verification.TYPICAL for s in sources)
            else stored.verification
            if stored
            else Verification.ESTIMATED
        )
        rows.append(
            DishAllergen(
                key,
                name,
                relation,
                verification,
                tuple(
                    dict.fromkeys(
                        node.name for node in components if key in findings.get(node.food_id, {})
                    )
                ),
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


def resolve_edited_value(
    nutrient: NutrientRecord,
    fact: NutrientFact | None,
    full: NutrientBreakdown | None,
    final: tuple[ComponentNode, ...],
    moisture: float,
) -> tuple[ResolvedValue, bool]:
    """A stated value moves by what the edits changed. Anything else is rebuilt from the result."""
    breakdown = nutrient_breakdown(
        final,
        nutrient.id,
        moisture_change_pct=moisture,
        is_water=nutrient.key == WATER_KEY,
    )
    if fact is not None and not fact.estimated and full is not None:
        simulated = published_after_edits(full, breakdown, moisture, nutrient.key == WATER_KEY)
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


def _foods_edits_bring_in(edits: Collection[Edit]) -> set[int]:
    food_ids: set[int] = set()
    for edit in edits:
        if isinstance(edit, AddEdit):
            food_ids.add(edit.food_id)
        elif isinstance(edit, ReplaceEdit):
            food_ids.update(item.food_id for item in edit.replacements)
    return food_ids


def food_composition(
    session: Session, food_id: int, edits: Collection[Edit] = ()
) -> FoodComposition:
    food = load_food(session, food_id)
    if food is None:
        raise FoodNotFound(food_id)

    catalog = load_nutrient_catalog(session)
    facts = load_facts(session, [food_id]).get(food_id, {})
    recipe = load_default_recipe(session, food_id)
    components = load_composition(session, food_id) if recipe else ()
    moisture = recipe.moisture_change_pct if recipe else 0.0

    if edits and recipe is None:
        raise InvalidEdit(f"Food {food_id} has no recipe to edit.")
    edited = apply_edits(
        components, tuple(edits), load_food_nodes(session, _foods_edits_bring_in(edits))
    )
    final = edited.components
    is_modified = edited.is_modified

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
        if is_modified:
            resolved[nutrient.key], approximate[nutrient.key] = resolve_edited_value(
                nutrient, fact, full, final, moisture
            )
        else:
            resolved[nutrient.key], approximate[nutrient.key] = base[nutrient.key], False
        if final:
            shown = nutrient_breakdown(final, nutrient.id, None, moisture, is_water)
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
            base_amount_per_100g=before if is_modified else None,
            delta_per_100g=(
                value.amount - before
                if is_modified and value.amount is not None and before is not None
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
    weights = [node.weight_g for node in final]
    raw_weight = (
        sum(w for w in weights if w is not None)
        if weights and all(w is not None for w in weights)
        else None
    )
    food_ids = [row.node.food_id for row in edited.rows]
    annotations = load_ingredient_annotations(session, food_ids)
    allergen_findings = load_allergen_findings(session, [food_id, *food_ids])

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
        is_modified=is_modified,
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
        allergens=_dish_allergens(
            food_id, food.name, edited, allergen_findings, load_allergen_names(session)
        ),
        ingredients=_ingredient_rows(edited, annotations, allergen_findings),
        nutrients=tuple(rows[nutrient.key] for nutrient in catalog),
        contributions=tuple(contributions),
        evaluations=tuple(_evaluate_serving(s, catalog, rows) for s in servings),
        sources=tuple(sources),
    )
