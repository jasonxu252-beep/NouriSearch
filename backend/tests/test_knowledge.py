"""The curated swap file and the loader that brings it and the allergen findings in."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Food,
    FoodAllergen,
    FoodClassification,
    FoodExternalRef,
    FoodRole,
    FoodSensory,
    Source,
    SubstitutionComponent,
    SubstitutionOption,
)
from app.domain.allergens import allergens_in_name
from app.domain.enums import AllergenRelation, ExternalSystem, FoodClassificationKind, FoodKind
from app.ingest.knowledge import (
    SUBSTITUTIONS_PATH,
    CuratedFood,
    SubstitutionFile,
    load_allergen_findings,
    load_curated_knowledge,
    read_substitutions,
)
from app.ingest.vocabulary import load_vocabulary, read_bundle
from tests.factories import make_food, make_recipe, make_source

# Words the product must not use, the same as the frontend's own wording test.
ADVICE = re.compile(
    r"\b(healthy|healthier|unhealthy|safe|safer|should|must|deficien\w*|allergen-free|free of|"
    r"cures?|prevents?|treats?)\b",
    re.IGNORECASE,
)


def food_entry(**overrides: object) -> dict[str, object]:
    return {
        "key": "soy",
        "role": "sauce",
        "diet": "vegan",
        "records": [{"system": "ndb_number", "id": "1", "name": "Soy sauce"}],
        **overrides,
    }


def test_the_curated_file_is_valid() -> None:
    data = read_substitutions()
    assert len(data.foods) > 100
    assert len(data.swaps) > 80


def test_every_vocabulary_reference_in_the_curated_file_exists() -> None:
    data = read_substitutions()
    vocabulary = read_bundle().vocabularies
    roles = {entry.key for entry in vocabulary.ingredient_roles}
    allergens = {entry.key for entry in vocabulary.allergens}
    sensory = {entry.key: entry.kind for entry in vocabulary.sensory_attributes}
    for food in data.foods:
        assert food.role in roles, food.key
        assert set(food.contains) | set(food.may_contain) <= allergens, food.key
        for attribute in food.flavor:
            assert sensory[attribute] == "flavor", (food.key, attribute)
        for attribute in food.texture:
            assert sensory[attribute] == "texture", (food.key, attribute)


def test_a_hand_assessment_does_not_miss_what_the_food_name_says_it_contains() -> None:
    """Two independent readings of each food must agree on what is plainly there."""
    for food in read_substitutions().foods:
        assessed = set(food.contains)
        for record in food.records:
            for allergen, relation in allergens_in_name(record.name).items():
                if relation is AllergenRelation.CONTAINS:
                    assert allergen in assessed, (food.key, record.name, allergen)


def test_every_food_states_a_diet_and_a_plausible_one() -> None:
    meat_words = re.compile(
        r"\b(beef|chicken|turkey|pork|bacon|ham|tuna|shrimp|fish|sausage)\b", re.I
    )
    for food in read_substitutions().foods:
        for record in food.records:
            if meat_words.search(record.name):
                assert food.diet == "omnivore", (food.key, record.name)


def test_potassium_based_salt_substitutes_stay_out() -> None:
    """They can be dangerous for people with kidney disease or on some blood pressure medicines."""
    text = yaml.safe_dump(
        [record.name for food in read_substitutions().foods for record in food.records]
    )
    assert "potassium" not in text.lower()
    assert "salt substitute" not in text.lower()


def test_notes_carry_no_advice_or_health_claims() -> None:
    for swap in read_substitutions().swaps:
        assert not ADVICE.search(swap.note), swap.note


def test_a_swap_naming_an_unknown_food_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown foods"):
        SubstitutionFile.model_validate(
            {
                "source": "s",
                "foods": [food_entry()],
                "swaps": [
                    {"from": "soy", "to": [{"food": "ghost", "ratio": 1}], "fit": 3, "note": "n"}
                ],
            }
        )


def test_a_repeated_record_is_refused() -> None:
    with pytest.raises(ValidationError, match="listed twice"):
        SubstitutionFile.model_validate(
            {"source": "s", "foods": [food_entry(), food_entry(key="other")], "swaps": []}
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"diet": "pescatarian"},
        {"flavor": {"salty": 6}},
        {"flavor": {"salty": 1}},
        {"contains": ["milk"], "may_contain": ["milk"]},
        {"records": []},
        {"surprise": True},
    ],
)
def test_a_bad_food_entry_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CuratedFood.model_validate(food_entry(**overrides))


@pytest.mark.parametrize(
    "swap",
    [
        {"from": "soy", "to": [], "fit": 3, "note": "n"},
        {"from": "soy", "to": [{"food": "soy", "ratio": 0}], "fit": 3, "note": "n"},
        {"from": "soy", "to": [{"food": "soy", "ratio": 1}], "fit": 6, "note": "n"},
        {"from": "soy", "to": [{"food": "soy", "ratio": 1}], "fit": 3, "note": ""},
        {
            "from": "soy",
            "to": [{"food": "soy", "ratio": 1}, {"food": "soy", "ratio": 1}],
            "fit": 3,
            "note": "n",
        },
    ],
)
def test_a_bad_swap_is_refused(swap: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SubstitutionFile.model_validate({"source": "s", "foods": [food_entry()], "swaps": [swap]})


pytestmark_integration = pytest.mark.integration


def small_file() -> SubstitutionFile:
    return SubstitutionFile.model_validate(
        {
            "source": "nourisearch-editorial",
            "foods": [
                {
                    "key": "shoyu",
                    "role": "sauce",
                    "diet": "vegan",
                    "contains": ["soybeans", "wheat"],
                    "flavor": {"salty": 5, "umami": 5},
                    "records": [
                        {"system": "ndb_number", "id": "16123", "name": "Shoyu"},
                        {"system": "fndds_code", "id": "41420300", "name": "Soy sauce"},
                    ],
                },
                {
                    "key": "low",
                    "role": "sauce",
                    "diet": "vegan",
                    "flavor": {"salty": 4},
                    "texture": {"creamy": 2},
                    "records": [
                        {"system": "ndb_number", "id": "16424", "name": "Low sodium shoyu"}
                    ],
                },
                {
                    "key": "beef",
                    "role": "primary_protein",
                    "diet": "omnivore",
                    "records": [{"system": "ndb_number", "id": "13", "name": "Beef"}],
                },
                {
                    "key": "egg",
                    "role": "primary_protein",
                    "diet": "vegetarian",
                    "records": [{"system": "ndb_number", "id": "1123", "name": "Egg"}],
                },
            ],
            "swaps": [
                {"from": "shoyu", "to": [{"food": "low", "ratio": 1}], "fit": 5, "note": "Close."},
                {"from": "beef", "to": [{"food": "egg", "ratio": 1}], "fit": 2, "note": "Far."},
            ],
        }
    )


def add_record(session: Session, food: Food, system: ExternalSystem, external_id: str) -> None:
    session.add(FoodExternalRef(food_id=food.id, system=system, external_id=external_id))
    session.flush()


@pytest.fixture
def records(session: Session) -> dict[str, Food]:
    load_vocabulary(session)
    source = make_source(session)
    foods = {
        "shoyu": make_food(session, "Shoyu", source),
        "soy": make_food(session, "Soy sauce", source),
        "low": make_food(session, "Low sodium shoyu", source),
        "beef": make_food(session, "Beef", source),
        "egg": make_food(session, "Egg", source),
    }
    add_record(session, foods["shoyu"], ExternalSystem.NDB_NUMBER, "16123")
    add_record(session, foods["soy"], ExternalSystem.FNDDS_CODE, "41420300")
    add_record(session, foods["low"], ExternalSystem.NDB_NUMBER, "16424")
    add_record(session, foods["beef"], ExternalSystem.NDB_NUMBER, "13")
    add_record(session, foods["egg"], ExternalSystem.NDB_NUMBER, "1123")
    return foods


def count(session: Session, model: type[object]) -> int | None:
    return session.scalar(select(func.count()).select_from(model))


@pytest.mark.integration
def test_loading_writes_roles_sensory_data_allergens_diets_and_swaps(
    session: Session, records: dict[str, Food]
) -> None:
    result = load_curated_knowledge(session, small_file())

    assert result.missing_records == ()
    # Shoyu has two records, and each can be replaced by the one record offered in its place.
    assert result.swaps == 3
    options = session.scalars(
        select(SubstitutionOption).where(SubstitutionOption.from_food_id == records["soy"].id)
    ).all()
    assert len(options) == 1
    assert options[0].culinary_fit == 5
    assert options[0].notes == "Close."
    assert (
        session.scalar(
            select(SubstitutionComponent.to_food_id).where(
                SubstitutionComponent.option_id == options[0].id
            )
        )
        == records["low"].id
    )

    offered = dict(
        session.execute(
            select(FoodRole.food_id, FoodRole.is_offered).where(
                FoodRole.food_id.in_([records["shoyu"].id, records["soy"].id])
            )
        ).all()
    )
    assert offered == {records["shoyu"].id: True, records["soy"].id: False}

    kinds = session.scalars(
        select(FoodClassification.classification).where(
            FoodClassification.food_id == records["beef"].id
        )
    ).all()
    assert set(kinds) == {
        FoodClassificationKind.MEAT_OR_FISH,
        FoodClassificationKind.ANIMAL_DERIVED,
    }
    assert session.scalars(
        select(FoodClassification.classification).where(
            FoodClassification.food_id == records["egg"].id
        )
    ).all() == [FoodClassificationKind.ANIMAL_DERIVED]


@pytest.mark.integration
def test_a_vegan_food_carries_no_diet_facts(session: Session, records: dict[str, Food]) -> None:
    load_curated_knowledge(session, small_file())
    assert (
        session.scalar(
            select(func.count())
            .select_from(FoodClassification)
            .where(FoodClassification.food_id == records["low"].id)
        )
        == 0
    )


@pytest.mark.integration
def test_every_row_cites_the_editorial_source(session: Session, records: dict[str, Food]) -> None:
    load_curated_knowledge(session, small_file())
    editorial = session.scalar(select(Source.id).where(Source.key == "nourisearch-editorial"))
    for model in (FoodRole, FoodSensory, FoodAllergen, FoodClassification, SubstitutionOption):
        sources = set(session.scalars(select(model.source_id)).all())
        assert sources == {editorial}, model


@pytest.mark.integration
def test_loading_twice_leaves_the_same_result(session: Session, records: dict[str, Food]) -> None:
    load_curated_knowledge(session, small_file())

    def counts() -> list[int | None]:
        return [
            count(session, model)
            for model in (
                FoodRole,
                FoodSensory,
                FoodAllergen,
                FoodClassification,
                SubstitutionOption,
                SubstitutionComponent,
            )
        ]

    first = counts()
    load_curated_knowledge(session, small_file())
    assert counts() == first


@pytest.mark.integration
def test_a_swap_removed_from_the_file_leaves_the_database(
    session: Session, records: dict[str, Food]
) -> None:
    load_curated_knowledge(session, small_file())
    smaller = small_file().model_copy(update={"swaps": ()})
    load_curated_knowledge(session, smaller)
    assert count(session, SubstitutionOption) == 0


@pytest.mark.integration
def test_a_record_this_database_lacks_is_reported_and_its_swaps_skipped(
    session: Session, records: dict[str, Food]
) -> None:
    session.delete(
        session.scalars(select(FoodExternalRef).where(FoodExternalRef.external_id == "16424")).one()
    )
    session.flush()
    result = load_curated_knowledge(session, small_file())
    assert result.missing_records == ("ndb_number:16424 Low sodium shoyu",)
    assert result.swaps == 1


@pytest.mark.integration
def test_an_id_now_naming_another_food_stops_the_load(
    session: Session, records: dict[str, Food]
) -> None:
    """A shifted ID must fail loudly, or a swap would silently point at the wrong food."""
    records["low"].canonical_name = "Something else entirely"
    session.flush()
    with pytest.raises(ValueError, match="no longer match"):
        load_curated_knowledge(session, small_file())


@pytest.mark.integration
def test_allergen_findings_cover_names_and_recipes(
    session: Session, records: dict[str, Food]
) -> None:
    source = session.scalar(select(Source).where(Source.key == "test-usda"))
    assert source is not None
    tofu = make_food(session, "Tofu, firm", source)
    dish = make_food(session, "House special", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(tofu, 10.0)])

    load_allergen_findings(session)

    allergens = session.execute(
        select(FoodAllergen.relation, FoodAllergen.verification, Source.key)
        .join(Source, Source.id == FoodAllergen.source_id)
        .where(FoodAllergen.food_id == dish.id)
    ).all()
    assert [(a[0], a[1].value, a[2]) for a in allergens] == [
        (AllergenRelation.CONTAINS, "estimated", "nourisearch-derived-from-fdc")
    ]


@pytest.mark.integration
def test_rerunning_findings_replaces_only_its_own_rows(
    session: Session, records: dict[str, Food]
) -> None:
    load_curated_knowledge(session, small_file())
    load_allergen_findings(session)
    first = count(session, FoodAllergen)
    assessed = session.scalar(
        select(func.count())
        .select_from(FoodAllergen)
        .join(Source, Source.id == FoodAllergen.source_id)
        .where(Source.key == "nourisearch-editorial")
    )
    assert assessed and assessed > 0

    load_allergen_findings(session)

    assert count(session, FoodAllergen) == first
    assert (
        session.scalar(
            select(func.count())
            .select_from(FoodAllergen)
            .join(Source, Source.id == FoodAllergen.source_id)
            .where(Source.key == "nourisearch-editorial")
        )
        == assessed
    )


def test_the_curated_file_is_where_the_loader_looks() -> None:
    assert (
        Path(__file__).resolve().parents[1] / "data/curated/substitutions.yaml"
        == SUBSTITUTIONS_PATH
    )
