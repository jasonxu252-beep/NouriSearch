"""Curated reference data loads correctly and matches the sources it cites."""

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Allergen, Cuisine, Nutrient, NutrientReferenceValue, NutrientSourceCode
from app.domain.enums import NutrientDirection, ReferenceKind
from app.ingest.vocabulary import CuratedBundle, Vocabularies, load_vocabulary, read_bundle

# The FDA Daily Value table, retyped here on purpose. A typo in either place fails this test.
FDA_DAILY_VALUES = {
    "added_sugars": 50,
    "biotin": 30,
    "calcium": 1300,
    "chloride": 2300,
    "choline": 550,
    "cholesterol": 300,
    "chromium": 35,
    "copper": 0.9,
    "fiber": 28,
    "total_fat": 78,
    "folate": 400,
    "iodine": 150,
    "iron": 18,
    "magnesium": 420,
    "manganese": 2.3,
    "molybdenum": 45,
    "niacin": 16,
    "pantothenic_acid": 5,
    "phosphorus": 1250,
    "potassium": 4700,
    "protein": 50,
    "riboflavin": 1.3,
    "saturated_fat": 20,
    "selenium": 55,
    "sodium": 2300,
    "thiamin": 1.2,
    "carbohydrate": 275,
    "vitamin_a": 900,
    "vitamin_b6": 1.7,
    "vitamin_b12": 2.4,
    "vitamin_c": 90,
    "vitamin_d": 20,
    "vitamin_e": 15,
    "vitamin_k": 120,
    "zinc": 11,
}


def test_daily_values_match_the_fda_table_exactly() -> None:
    bundle = read_bundle()
    curated = {n.key: n.dv for n in bundle.nutrients if n.dv is not None}
    assert curated == FDA_DAILY_VALUES


def test_limit_and_encourage_lists_match_the_fda_guide() -> None:
    bundle = read_bundle()
    limit = {n.key for n in bundle.nutrients if n.direction is NutrientDirection.LIMIT}
    encourage = {n.key for n in bundle.nutrients if n.direction is NutrientDirection.ENCOURAGE}
    assert limit == {"saturated_fat", "sodium", "added_sugars"}
    assert encourage == {"fiber", "vitamin_d", "calcium", "iron", "potassium"}


def test_allergens_are_the_nine_fda_majors() -> None:
    keys = {a.key for a in read_bundle().vocabularies.allergens}
    assert keys == {
        "milk",
        "eggs",
        "fish",
        "crustacean_shellfish",
        "tree_nuts",
        "peanuts",
        "wheat",
        "soybeans",
        "sesame",
    }


def test_duplicate_keys_are_rejected_before_any_write() -> None:
    bundle = read_bundle()
    with pytest.raises(ValidationError, match="Duplicate nutrient keys"):
        CuratedBundle(
            sources=bundle.sources,
            nutrients=[*bundle.nutrients, bundle.nutrients[0]],
            vocabularies=bundle.vocabularies,
            reference_intakes=bundle.reference_intakes,
        )


def test_a_usda_code_cannot_map_to_two_nutrients() -> None:
    bundle = read_bundle()
    clash = bundle.nutrients[1].model_copy(update={"key": "protein_again", "dv": None})
    with pytest.raises(ValidationError, match="USDA codes mapped twice"):
        CuratedBundle(
            sources=bundle.sources,
            nutrients=[*bundle.nutrients, clash],
            vocabularies=bundle.vocabularies,
            reference_intakes=bundle.reference_intakes,
        )


def test_unknown_fields_in_curated_files_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Vocabularies.model_validate(
            {
                "allergens": [{"key": "milk", "name": "Milk", "typo_field": 1}],
                "cuisines": [],
                "food_groups": [],
                "ingredient_roles": [],
                "preparation_methods": [],
                "sensory_attributes": [],
            }
        )


@pytest.mark.integration
def test_loading_twice_changes_nothing(session: Session) -> None:
    first = load_vocabulary(session)
    daily_values = (
        select(func.count())
        .select_from(NutrientReferenceValue)
        .where(NutrientReferenceValue.kind == ReferenceKind.DV)
    )
    before = session.scalar(daily_values)
    second = load_vocabulary(session)
    after = session.scalar(daily_values)
    assert first == second
    assert before == after == len(FDA_DAILY_VALUES)


@pytest.mark.integration
def test_loaded_data_links_correctly(session: Session) -> None:
    load_vocabulary(session)

    sichuan = session.scalar(select(Cuisine).where(Cuisine.key == "sichuan"))
    chinese = session.scalar(select(Cuisine).where(Cuisine.key == "chinese"))
    assert sichuan is not None and chinese is not None
    assert sichuan.parent_id == chinese.id

    saturated = session.scalar(select(Nutrient).where(Nutrient.key == "saturated_fat"))
    total_fat = session.scalar(select(Nutrient).where(Nutrient.key == "total_fat"))
    assert saturated is not None and total_fat is not None
    assert saturated.parent_id == total_fat.id

    # USDA stores total sugars under two codes, and both must resolve to one nutrient.
    codes = session.execute(
        select(NutrientSourceCode.code, NutrientSourceCode.preference)
        .join(Nutrient)
        .where(Nutrient.key == "total_sugars")
        .order_by(NutrientSourceCode.preference)
    ).all()
    assert [tuple(row) for row in codes] == [("269", 0), ("269.3", 1)]

    assert session.scalar(select(func.count()).select_from(Allergen)) == 9
