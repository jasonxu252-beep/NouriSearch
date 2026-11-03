"""Small builders for integration tests. Values passed in tests come from real USDA records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Food,
    FoodNutrient,
    Nutrient,
    NutrientProxy,
    Recipe,
    RecipeComponent,
    Source,
    SubstitutionComponent,
    SubstitutionOption,
)
from app.domain.enums import FoodKind, SourceTier, ValueKind, Verification
from app.domain.text import slugify


def make_source(session: Session, key: str = "test-usda", priority: int = 20) -> Source:
    source = Source(
        key=key,
        publisher="U.S. Department of Agriculture",
        title=f"Test source {key}",
        tier=SourceTier.GOVERNMENT_DATASET,
        priority=priority,
    )
    session.add(source)
    session.flush()
    return source


def make_nutrient(session: Session, key: str = "sodium", unit: str = "mg") -> Nutrient:
    existing = session.scalar(select(Nutrient).where(Nutrient.key == key))
    if existing is not None:
        return existing
    nutrient = Nutrient(
        key=key,
        name=key.title(),
        unit=unit,
        category="mineral",
        direction="limit",
        display_order=1,
    )
    session.add(nutrient)
    session.flush()
    return nutrient


def make_food(
    session: Session,
    name: str,
    source: Source,
    kind: FoodKind = FoodKind.BASIC,
    values: dict[Nutrient, float] | None = None,
) -> Food:
    food = Food(slug=slugify(name), kind=kind, canonical_name=name, source_id=source.id)
    session.add(food)
    session.flush()
    for nutrient, amount in (values or {}).items():
        session.add(
            FoodNutrient(
                food_id=food.id,
                nutrient_id=nutrient.id,
                source_id=source.id,
                amount_per_100g=amount,
                value_kind=ValueKind.ANALYTICAL,
            )
        )
    session.flush()
    return food


def make_recipe(
    session: Session,
    dish: Food,
    source: Source,
    components: list[tuple[Food, float | None]],
    is_default: bool = True,
    verification: Verification = Verification.SOURCE_DOCUMENTED,
    label: str | None = None,
    moisture_change_pct: float | None = None,
) -> Recipe:
    recipe = Recipe(
        dish_id=dish.id,
        label=label or f"Recipe for {dish.canonical_name}",
        moisture_change_pct=moisture_change_pct,
        verification=verification,
        is_default=is_default,
        source_id=source.id,
    )
    session.add(recipe)
    session.flush()
    for position, (food, weight) in enumerate(components):
        session.add(
            RecipeComponent(
                recipe_id=recipe.id,
                component_food_id=food.id,
                position=position,
                weight_g=weight,
            )
        )
    session.flush()
    return recipe


def make_substitution(
    session: Session,
    from_food: Food,
    to_foods: list[tuple[Food, float]],
    source: Source,
) -> SubstitutionOption:
    option = SubstitutionOption(
        from_food_id=from_food.id,
        verification=Verification.TYPICAL,
        source_id=source.id,
    )
    session.add(option)
    session.flush()
    for food, ratio in to_foods:
        session.add(
            SubstitutionComponent(option_id=option.id, to_food_id=food.id, ratio_by_weight=ratio)
        )
    session.flush()
    return option


def make_proxy(session: Session, food: Food, proxy: Food, source: Source) -> NutrientProxy:
    row = NutrientProxy(
        food_id=food.id,
        proxy_food_id=proxy.id,
        rationale="Closest documented food.",
        source_id=source.id,
    )
    session.add(row)
    session.flush()
    return row
