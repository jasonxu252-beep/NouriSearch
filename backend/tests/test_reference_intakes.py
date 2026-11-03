"""The age and sex references, checked against the National Academies' printed tables.

The tables below are typed a second time on purpose, as printed: one row per life stage. The
curated file holds one row per nutrient. A slip in either place fails here, because these numbers
are health facts.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import NutrientReferenceValue
from app.db.session import get_session
from app.domain.enums import ReferenceKind, ReferencePopulation
from app.ingest.vocabulary import (
    CuratedBundle,
    ReferenceIntakeFile,
    load_vocabulary,
    read_bundle,
)
from app.main import create_app

# Life stage: vitamin A, C, D, E, K, thiamin, riboflavin, niacin, B6, folate, B12, pantothenic acid,
# biotin, choline.
PRINTED_VITAMINS = {
    "child_1_3": (300, 15, 15, 6, 30, 0.5, 0.5, 6, 0.5, 150, 0.9, 2, 8, 200),
    "child_4_8": (400, 25, 15, 7, 55, 0.6, 0.6, 8, 0.6, 200, 1.2, 3, 12, 250),
    "male_9_13": (600, 45, 15, 11, 60, 0.9, 0.9, 12, 1.0, 300, 1.8, 4, 20, 375),
    "male_14_18": (900, 75, 15, 15, 75, 1.2, 1.3, 16, 1.3, 400, 2.4, 5, 25, 550),
    "male_19_30": (900, 90, 15, 15, 120, 1.2, 1.3, 16, 1.3, 400, 2.4, 5, 30, 550),
    "male_31_50": (900, 90, 15, 15, 120, 1.2, 1.3, 16, 1.3, 400, 2.4, 5, 30, 550),
    "male_51_70": (900, 90, 15, 15, 120, 1.2, 1.3, 16, 1.7, 400, 2.4, 5, 30, 550),
    "male_71_plus": (900, 90, 20, 15, 120, 1.2, 1.3, 16, 1.7, 400, 2.4, 5, 30, 550),
    "female_9_13": (600, 45, 15, 11, 60, 0.9, 0.9, 12, 1.0, 300, 1.8, 4, 20, 375),
    "female_14_18": (700, 65, 15, 15, 75, 1.0, 1.0, 14, 1.2, 400, 2.4, 5, 25, 400),
    "female_19_30": (700, 75, 15, 15, 90, 1.1, 1.1, 14, 1.3, 400, 2.4, 5, 30, 425),
    "female_31_50": (700, 75, 15, 15, 90, 1.1, 1.1, 14, 1.3, 400, 2.4, 5, 30, 425),
    "female_51_70": (700, 75, 15, 15, 90, 1.1, 1.1, 14, 1.5, 400, 2.4, 5, 30, 425),
    "female_71_plus": (700, 75, 20, 15, 90, 1.1, 1.1, 14, 1.5, 400, 2.4, 5, 30, 425),
}
VITAMIN_COLUMNS = (
    "vitamin_a",
    "vitamin_c",
    "vitamin_d",
    "vitamin_e",
    "vitamin_k",
    "thiamin",
    "riboflavin",
    "niacin",
    "vitamin_b6",
    "folate",
    "vitamin_b12",
    "pantothenic_acid",
    "biotin",
    "choline",
)

# Life stage: calcium, chromium, copper (as printed, in micrograms), iodine, iron, magnesium,
# manganese, molybdenum, phosphorus, selenium, zinc, potassium, chloride (as printed, in grams).
PRINTED_ELEMENTS = {
    "child_1_3": (700, 11, 340, 90, 7, 80, 1.2, 17, 460, 20, 3, 2000, 1.5),
    "child_4_8": (1000, 15, 440, 90, 10, 130, 1.5, 22, 500, 30, 5, 2300, 1.9),
    "male_9_13": (1300, 25, 700, 120, 8, 240, 1.9, 34, 1250, 40, 8, 2500, 2.3),
    "male_14_18": (1300, 35, 890, 150, 11, 410, 2.2, 43, 1250, 55, 11, 3000, 2.3),
    "male_19_30": (1000, 35, 900, 150, 8, 400, 2.3, 45, 700, 55, 11, 3400, 2.3),
    "male_31_50": (1000, 35, 900, 150, 8, 420, 2.3, 45, 700, 55, 11, 3400, 2.3),
    "male_51_70": (1000, 30, 900, 150, 8, 420, 2.3, 45, 700, 55, 11, 3400, 2.0),
    "male_71_plus": (1200, 30, 900, 150, 8, 420, 2.3, 45, 700, 55, 11, 3400, 1.8),
    "female_9_13": (1300, 21, 700, 120, 8, 240, 1.6, 34, 1250, 40, 8, 2300, 2.3),
    "female_14_18": (1300, 24, 890, 150, 15, 360, 1.6, 43, 1250, 55, 9, 2300, 2.3),
    "female_19_30": (1000, 25, 900, 150, 18, 310, 1.8, 45, 700, 55, 8, 2600, 2.3),
    "female_31_50": (1000, 25, 900, 150, 18, 320, 1.8, 45, 700, 55, 8, 2600, 2.3),
    "female_51_70": (1200, 20, 900, 150, 8, 320, 1.8, 45, 700, 55, 8, 2600, 2.0),
    "female_71_plus": (1200, 20, 900, 150, 8, 320, 1.8, 45, 700, 55, 8, 2600, 1.8),
}
ELEMENT_COLUMNS = (
    "calcium",
    "chromium",
    "copper",
    "iodine",
    "iron",
    "magnesium",
    "manganese",
    "molybdenum",
    "phosphorus",
    "selenium",
    "zinc",
    "potassium",
    "chloride",
)

# Life stage: carbohydrate, fiber, protein, and the sodium Chronic Disease Risk Reduction Intake.
PRINTED_MACROS_AND_SODIUM = {
    "child_1_3": (130, 19, 13, 1200),
    "child_4_8": (130, 25, 19, 1500),
    "male_9_13": (130, 31, 34, 1800),
    "male_14_18": (130, 38, 52, 2300),
    "male_19_30": (130, 38, 56, 2300),
    "male_31_50": (130, 38, 56, 2300),
    "male_51_70": (130, 30, 56, 2300),
    "male_71_plus": (130, 30, 56, 2300),
    "female_9_13": (130, 26, 34, 1800),
    "female_14_18": (130, 26, 46, 2300),
    "female_19_30": (130, 25, 46, 2300),
    "female_31_50": (130, 25, 46, 2300),
    "female_51_70": (130, 21, 46, 2300),
    "female_71_plus": (130, 21, 46, 2300),
}
MACRO_COLUMNS = ("carbohydrate", "fiber", "protein", "sodium")

ADEQUATE_INTAKES = {
    "vitamin_k",
    "pantothenic_acid",
    "biotin",
    "choline",
    "chromium",
    "manganese",
    "potassium",
    "chloride",
    "fiber",
}


def curated_value(nutrient: str, population: str) -> float:
    data = read_bundle().reference_intakes
    entry = next(item for item in data.intakes if item.nutrient == nutrient)
    return entry.values[data.populations.index(ReferencePopulation(population))]


@pytest.mark.parametrize("population", PRINTED_VITAMINS)
def test_vitamins_match_the_printed_table(population: str) -> None:
    for column, printed in zip(VITAMIN_COLUMNS, PRINTED_VITAMINS[population], strict=True):
        assert curated_value(column, population) == printed, column


@pytest.mark.parametrize("population", PRINTED_ELEMENTS)
def test_elements_match_the_printed_table(population: str) -> None:
    for column, printed in zip(ELEMENT_COLUMNS, PRINTED_ELEMENTS[population], strict=True):
        # The table prints these in other units than the catalog uses.
        if column == "copper":
            expected = printed / 1000
        elif column == "chloride":
            expected = printed * 1000
        else:
            expected = printed
        assert curated_value(column, population) == pytest.approx(expected), column


@pytest.mark.parametrize("population", PRINTED_MACROS_AND_SODIUM)
def test_macronutrients_and_sodium_match_the_printed_tables(population: str) -> None:
    for column, printed in zip(MACRO_COLUMNS, PRINTED_MACROS_AND_SODIUM[population], strict=True):
        assert curated_value(column, population) == printed, column


def test_every_value_in_the_file_was_checked_against_a_printed_table() -> None:
    checked = {*VITAMIN_COLUMNS, *ELEMENT_COLUMNS, *MACRO_COLUMNS}
    assert {entry.nutrient for entry in read_bundle().reference_intakes.intakes} == checked


def test_each_nutrient_says_what_kind_of_value_it_is() -> None:
    for entry in read_bundle().reference_intakes.intakes:
        if entry.nutrient == "sodium":
            assert entry.kind is ReferenceKind.CDRR
        elif entry.nutrient in ADEQUATE_INTAKES:
            assert entry.kind is ReferenceKind.AI, entry.nutrient
        else:
            assert entry.kind is ReferenceKind.RDA, entry.nutrient


def test_the_file_covers_every_group_except_the_general_one() -> None:
    populations = read_bundle().reference_intakes.populations
    assert set(populations) == set(ReferencePopulation) - {ReferencePopulation.GENERAL_LABEL}


def test_a_list_of_the_wrong_length_is_rejected_before_any_write() -> None:
    bundle = read_bundle()
    data = bundle.reference_intakes
    short = data.intakes[0].model_copy(update={"values": [1.0, 2.0]})
    with pytest.raises(ValueError, match="values"):
        CuratedBundle(
            sources=bundle.sources,
            nutrients=bundle.nutrients,
            vocabularies=bundle.vocabularies,
            reference_intakes=ReferenceIntakeFile(
                source=data.source,
                populations=data.populations,
                intakes=[short],
                general_guides=data.general_guides,
            ),
        )


def test_an_unknown_nutrient_is_rejected_before_any_write() -> None:
    bundle = read_bundle()
    data = bundle.reference_intakes
    wrong = data.intakes[0].model_copy(update={"nutrient": "vitamin_x"})
    with pytest.raises(ValueError, match="vitamin_x"):
        CuratedBundle(
            sources=bundle.sources,
            nutrients=bundle.nutrients,
            vocabularies=bundle.vocabularies,
            reference_intakes=ReferenceIntakeFile(
                source=data.source,
                populations=data.populations,
                intakes=[wrong],
                general_guides=data.general_guides,
            ),
        )


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    load_vocabulary(session)
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)


def read(client: TestClient, population: str | None = None) -> dict[str, Any]:
    params = {"population": population} if population else {}
    response = client.get("/v1/reference-intakes", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def values_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {value["nutrient_key"]: value for value in body["values"]}


@pytest.mark.integration
def test_the_general_group_is_the_fda_daily_values_and_the_calorie_guide(
    client: TestClient,
) -> None:
    values = values_of(read(client))
    assert values["protein"]["amount"] == 50
    assert values["protein"]["kind"] == "dv"
    assert values["protein"]["source_key"] == "fda-daily-values"
    assert values["energy"]["amount"] == 2000
    assert values["energy"]["kind"] == "label_guide"
    assert values["energy"]["source_key"] == "fda-nutrition-facts-guide"
    assert "total_sugars" not in values, "the FDA sets no Daily Value for total sugars"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("population", "expected"),
    [
        ("female_71_plus", {"protein": 46, "calcium": 1200, "vitamin_d": 20, "iron": 8}),
        ("female_19_30", {"protein": 46, "calcium": 1000, "vitamin_d": 15, "iron": 18}),
        ("male_71_plus", {"protein": 56, "calcium": 1200, "vitamin_d": 20, "iron": 8}),
        ("child_4_8", {"protein": 19, "calcium": 1000, "vitamin_d": 15, "iron": 10}),
    ],
)
def test_the_values_follow_age_and_sex(
    client: TestClient, population: str, expected: dict[str, float]
) -> None:
    values = values_of(read(client, population))
    for nutrient, amount in expected.items():
        assert values[nutrient]["amount"] == amount, nutrient
        assert values[nutrient]["is_general"] is False, nutrient
        assert values[nutrient]["source_key"] == "nasem-dri-summary", nutrient


@pytest.mark.integration
def test_sodium_is_compared_with_its_limit_rather_than_its_adequate_intake(
    client: TestClient,
) -> None:
    adult = values_of(read(client, "female_51_70"))["sodium"]
    assert (adult["amount"], adult["kind"]) == (2300, "cdrr")
    child = values_of(read(client, "child_1_3"))["sodium"]
    assert (child["amount"], child["kind"]) == (1200, "cdrr")


@pytest.mark.integration
def test_nutrients_with_no_age_or_sex_value_fall_back_and_say_so(client: TestClient) -> None:
    values = values_of(read(client, "female_51_70"))
    for nutrient, amount in [("saturated_fat", 20), ("added_sugars", 50), ("total_fat", 78)]:
        assert values[nutrient]["amount"] == amount, nutrient
        assert values[nutrient]["kind"] == "dv", nutrient
        assert values[nutrient]["is_general"] is True, nutrient
    assert values["energy"]["amount"] == 2000
    assert values["energy"]["is_general"] is True


@pytest.mark.integration
def test_nothing_is_invented_for_a_nutrient_with_no_reference_at_all(client: TestClient) -> None:
    values = values_of(read(client, "female_51_70"))
    for nutrient in ("total_sugars", "trans_fat", "water", "caffeine", "alcohol"):
        assert nutrient not in values, nutrient


@pytest.mark.integration
def test_every_cited_source_is_described(client: TestClient) -> None:
    body = read(client, "female_51_70")
    described = {source["key"] for source in body["sources"]}
    assert {value["source_key"] for value in body["values"]} == described


@pytest.mark.integration
def test_an_unknown_group_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/v1/reference-intakes", params={"population": "cat_1_3"})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


@pytest.mark.integration
def test_loading_again_adds_no_rows(session: Session) -> None:
    load_vocabulary(session)
    count = select(func.count()).select_from(NutrientReferenceValue)
    before = session.scalar(count)
    load_vocabulary(session)
    assert session.scalar(count) == before
    # 35 Daily Values, 31 nutrients across 14 groups, and the calorie guide.
    assert before == 35 + 31 * 14 + 1
