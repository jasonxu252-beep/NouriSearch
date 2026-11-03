"""Proves the schema itself enforces the project's data rules, independent of application code."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import FoodNutrient
from app.db.models._types import Sourced
from tests.factories import make_food, make_nutrient, make_proxy, make_recipe, make_source

pytestmark = pytest.mark.integration

# Each table that states a fact about the world. Adding one without a citation should fail here.
KNOWLEDGE_TABLES = {
    "allergen",
    "food",
    "food_alias",
    "food_allergen",
    "food_classification",
    "food_cuisine",
    "food_health_consideration",
    "food_image",
    "food_nutrient",
    "food_portion",
    "food_sensory",
    "nutrient_function",
    "nutrient_health_effect",
    "nutrient_proxy",
    "nutrient_reference_value",
    "nutrient_translation",
    "preparation_effect",
    "recipe",
    "substitution_option",
}


def test_every_knowledge_table_requires_a_source_at_the_database_level() -> None:
    for name in KNOWLEDGE_TABLES:
        column = Base.metadata.tables[name].c.source_id
        assert column.nullable is False, f"{name}.source_id must be required"
        foreign_keys = {fk.column.table.name for fk in column.foreign_keys}
        assert foreign_keys == {"source"}, f"{name}.source_id must reference source"


def test_every_table_using_the_sourced_mixin_is_listed_above() -> None:
    sourced = {
        m.class_.__tablename__ for m in Base.registry.mappers if issubclass(m.class_, Sourced)
    }
    assert sourced == KNOWLEDGE_TABLES


def test_uncited_nutrient_fact_is_rejected(session: Session) -> None:
    source = make_source(session)
    nutrient = make_nutrient(session)
    food = make_food(session, "Salt, table", source)
    with pytest.raises(IntegrityError, match="source_id"), session.begin_nested():
        session.execute(
            text(
                "INSERT INTO food_nutrient (food_id, nutrient_id, amount_per_100g, value_kind) "
                "VALUES (:f, :n, 38800, 'analytical')"
            ),
            {"f": food.id, "n": nutrient.id},
        )


def test_nutrient_amount_has_no_default_so_missing_cannot_become_zero(session: Session) -> None:
    source = make_source(session)
    nutrient = make_nutrient(session)
    food = make_food(session, "Salt, table", source)
    amount = FoodNutrient.__table__.c.amount_per_100g
    assert amount.nullable is False
    assert amount.server_default is None
    assert amount.default is None
    with pytest.raises(IntegrityError, match="amount_per_100g"), session.begin_nested():
        session.execute(
            text(
                "INSERT INTO food_nutrient (food_id, nutrient_id, source_id, value_kind) "
                "VALUES (:f, :n, :s, 'analytical')"
            ),
            {"f": food.id, "n": nutrient.id, "s": source.id},
        )


def test_a_real_zero_is_still_allowed(session: Session) -> None:
    source = make_source(session)
    nutrient = make_nutrient(session)
    food = make_food(session, "Oil, sesame", source, values={nutrient: 0.0})
    stored = session.get_one(FoodNutrient, (food.id, nutrient.id, source.id))
    assert stored.amount_per_100g == 0.0


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "INSERT INTO food_nutrient "
            "(food_id, nutrient_id, source_id, amount_per_100g, value_kind) "
            "VALUES (:food, :nutrient, :source, -1, 'analytical')",
            "amount_not_negative",
        ),
        (
            "INSERT INTO food_nutrient "
            "(food_id, nutrient_id, source_id, amount_per_100g, value_kind) "
            "VALUES (:food, :nutrient, :source, 1, 'guessed')",
            "valuekind",
        ),
        (
            "INSERT INTO food_portion (food_id, description, gram_weight, source_id, "
            "is_household_measure) VALUES (:food, '1 cup', 0, :source, true)",
            "gram_weight_positive",
        ),
        (
            "INSERT INTO food_alias "
            "(food_id, language, name, normalized_name, alias_type, source_id) "
            "VALUES (:food, 'Not A Language', 'x', 'x', 'preferred', :source)",
            "language_is_bcp47",
        ),
    ],
)
def test_invalid_values_are_rejected(session: Session, statement: str, constraint: str) -> None:
    source = make_source(session)
    nutrient = make_nutrient(session)
    food = make_food(session, "Salt, table", source)
    with pytest.raises(IntegrityError, match=constraint), session.begin_nested():
        session.execute(
            text(statement), {"food": food.id, "nutrient": nutrient.id, "source": source.id}
        )


def test_recipe_weight_must_be_positive_when_present_and_may_be_unknown(session: Session) -> None:
    source = make_source(session)
    dish = make_food(session, "Bibimbap", source)
    salt = make_food(session, "Salt, table", source)
    make_recipe(session, dish, source, [(salt, None)])  # Unknown quantity is allowed.
    with pytest.raises(IntegrityError, match="weight_positive"), session.begin_nested():
        make_recipe(session, make_food(session, "Dal", source), source, [(salt, -1.0)])


def test_a_dish_has_at_most_one_default_recipe(session: Session) -> None:
    source = make_source(session)
    dish = make_food(session, "Bibimbap", source)
    make_recipe(session, dish, source, [])
    with pytest.raises(IntegrityError, match="uq_recipe_default_per_dish"), session.begin_nested():
        make_recipe(session, dish, source, [])
    # A second recipe that is not the default is fine: dishes can have variations.
    make_recipe(session, dish, source, [], is_default=False)


def test_a_food_cannot_be_its_own_proxy(session: Session) -> None:
    source = make_source(session)
    food = make_food(session, "Salted fish", source)
    with pytest.raises(IntegrityError, match="proxy_is_another_food"), session.begin_nested():
        make_proxy(session, food, food, source)


def test_a_cited_source_cannot_be_deleted(session: Session) -> None:
    source = make_source(session)
    make_food(session, "Salt, table", source)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("DELETE FROM source WHERE id = :id"), {"id": source.id})
