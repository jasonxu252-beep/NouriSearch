"""USDA classification rules, checked against real USDA descriptions labeled by hand."""

import pytest

from app.domain.enums import FoodKind, ProcessingLevel, ValueKind
from app.ingest.fdc_rules import (
    CLASSIFICATION_SOURCE_KEY,
    FdcMappings,
    IngredientRecord,
    food_group_key,
    food_kind,
    is_discoverable,
    is_household_measure,
    processing_level,
    resolve_ingredient,
    value_kind,
)
from app.ingest.vocabulary import read_bundle
from app.integrations.fdc_bulk import FdcDataset

MAPPINGS = FdcMappings.load()


@pytest.mark.parametrize(
    ("description", "group", "expected"),
    [
        ("Apples, raw, with skin", "fruits", ProcessingLevel.WHOLE),
        ("Broccoli, raw", "vegetables", ProcessingLevel.WHOLE),
        ("Egg, whole, raw, fresh", "eggs", ProcessingLevel.WHOLE),
        ("Teff, uncooked", "grains", ProcessingLevel.WHOLE),
        ("Mollusks, oyster, eastern, farmed, raw", "seafood", ProcessingLevel.WHOLE),
        # Words that also name cuts and varieties, so they must not count as processing.
        ("Pork, fresh, leg (ham), whole, separable lean only, raw", "meat", ProcessingLevel.WHOLE),
        (
            "Beef, New Zealand, imported, cube roll, separable lean only, raw",
            "meat",
            ProcessingLevel.WHOLE,
        ),
        ("Squash, spaghetti, peeled, seeded, raw", "vegetables", ProcessingLevel.WHOLE),
        ("Squash, pie pumpkin, peeled, seeded, raw", "vegetables", ProcessingLevel.WHOLE),
        ("Carrots, baby, raw", "vegetables", ProcessingLevel.WHOLE),
        ("Sugar-apples, (sweetsop), raw", "fruits", ProcessingLevel.WHOLE),
        ("Peas, edible-podded, raw", "vegetables", ProcessingLevel.WHOLE),
        # Cooked, frozen, or dried foods are changed but still recognizable.
        (
            "Broccoli, cooked, boiled, drained, without salt",
            "vegetables",
            ProcessingLevel.MINIMALLY_PROCESSED,
        ),
        (
            "Cabbage, chinese (pak-choi), cooked, boiled, drained, with salt",
            "vegetables",
            ProcessingLevel.MINIMALLY_PROCESSED,
        ),
        (
            "Broccoli, cooked, from fresh, fat not added in cooking",
            "vegetables",
            ProcessingLevel.MINIMALLY_PROCESSED,
        ),
        ("Blackberries, frozen, unsweetened", "fruits", ProcessingLevel.MINIMALLY_PROCESSED),
        ("Egg, whole, raw, frozen, pasteurized", "eggs", ProcessingLevel.MINIMALLY_PROCESSED),
        ("Beans, Dry, Red (0% moisture)", "legumes", ProcessingLevel.MINIMALLY_PROCESSED),
        # The description shows real processing.
        ("Apple juice, canned or bottled, unsweetened", "beverages", ProcessingLevel.PROCESSED),
        ("Strawberries, frozen, sweetened", "fruits", ProcessingLevel.PROCESSED),
        ("Tuna, canned in oil, drained", "seafood", ProcessingLevel.PROCESSED),
        (
            "Pork, cured, ham, center slice, country-style, separable lean only, raw",
            "meat",
            ProcessingLevel.PROCESSED,
        ),
        ("Sausage, turkey, fresh, raw", "meat", ProcessingLevel.PROCESSED),
        (
            "Chicken, dark meat, thigh, meat only, with added solution, raw",
            "poultry",
            ProcessingLevel.PROCESSED,
        ),
        ("Rice, white, long-grain, regular, raw, enriched", "grains", ProcessingLevel.PROCESSED),
        (
            "Broccoli, cooked, from fresh, fat added in cooking",
            "vegetables",
            ProcessingLevel.PROCESSED,
        ),
        ("Nuts, almonds, dry roasted, with salt added", "nuts_seeds", ProcessingLevel.PROCESSED),
        ("Pickles, cucumber, dill, reduced sodium", "vegetables", ProcessingLevel.PROCESSED),
        (
            "Alcoholic beverage, wine, table, white, Semillon",
            "beverages",
            ProcessingLevel.PROCESSED,
        ),
        # A group of made products is processed whatever the description says.
        ("Cookies, chocolate chip, baked", "sweets", ProcessingLevel.PROCESSED),
        ("Oil, olive, raw", "fats_oils", ProcessingLevel.PROCESSED),
        ("Babyfood, carrots, strained, raw", "baby_foods", ProcessingLevel.PROCESSED),
        # No rule applies, so the honest answer is unknown. Section 6 of the plan requires this.
        ("Milk, whole, 3.25% milkfat", "dairy", ProcessingLevel.UNKNOWN),
        ("Spices, pepper, black", "seasonings", ProcessingLevel.UNKNOWN),
        ("Beverages, water, tap, drinking", "beverages", ProcessingLevel.UNKNOWN),
        ("Lamb, ground", "meat", ProcessingLevel.UNKNOWN),
        ("Spinach, baby", "vegetables", ProcessingLevel.UNKNOWN),
        ("Pistachio nuts, NFS", "nuts_seeds", ProcessingLevel.UNKNOWN),
        ("Any food at all, raw", None, ProcessingLevel.UNKNOWN),
    ],
)
def test_processing_level(description: str, group: str | None, expected: ProcessingLevel) -> None:
    assert processing_level(description, FoodKind.BASIC, group) is expected


def test_not_specified_wording_does_not_count_as_processing() -> None:
    """ "NS as to" means USDA does not know. It says nothing about how the food was made."""
    level = processing_level(
        "Chicken breast, baked, NS as to skin eaten, NS as to fried", FoodKind.BASIC, "poultry"
    )
    assert level is ProcessingLevel.MINIMALLY_PROCESSED


def test_a_prepared_dish_is_never_whole() -> None:
    assert processing_level("Spinach, raw", FoodKind.PREPARED_DISH, "vegetables") is (
        ProcessingLevel.PROCESSED
    )


@pytest.mark.parametrize(
    ("description", "group", "ingredients", "expected"),
    [
        ("Bibimbap, Korean", "mixed_dishes", 11, FoodKind.PREPARED_DISH),
        ("Kung pao chicken", "mixed_dishes", 1, FoodKind.PREPARED_DISH),
        ("Egg, deviled", "eggs", 5, FoodKind.PREPARED_DISH),
        # USDA blends three apple varieties for this one. Blending does not make it a dish.
        ("Apple, raw", "fruits", 3, FoodKind.BASIC),
        ("Broccoli, cooked, from fresh, fat not added in cooking", "vegetables", 3, FoodKind.BASIC),
        ("Apple, candied", "fruits", 3, FoodKind.PREPARED_DISH),
        ("Rice, white, cooked", "grains", 2, FoodKind.BASIC),
    ],
)
def test_food_kind_in_the_survey_data(
    description: str, group: str, ingredients: int, expected: FoodKind
) -> None:
    kind = food_kind(FdcDataset.FNDDS, "ignored", description, group, ingredients, MAPPINGS)
    assert kind is expected


def test_food_kind_in_standard_reference_data_follows_its_category() -> None:
    def kind(category: str) -> FoodKind:
        return food_kind(FdcDataset.SR_LEGACY, category, "A food", "meat", 0, MAPPINGS)

    assert kind("Fast Foods") is FoodKind.PREPARED_DISH
    assert kind("Beef Products") is FoodKind.BASIC


@pytest.mark.parametrize(
    ("category", "description", "expected"),
    [
        ("Dairy and Egg Products", "Egg, whole, raw, fresh", "eggs"),
        ("Dairy and Egg Products", "Eggs, Grade A, Large, egg whole", "eggs"),
        ("Dairy and Egg Products", "Eggnog", "dairy"),
        ("Dairy and Egg Products", "Milk, whole", "dairy"),
        ("Fruits and Fruit Juices", "Lemon juice, raw", "beverages"),
        ("Fruits and Fruit Juices", "Apricot nectar, canned", "beverages"),
        ("Fruits and Fruit Juices", "Pineapple, canned, juice pack, drained", "fruits"),
        ("Fruits and Fruit Juices", "Apples, raw, with skin", "fruits"),
        ("Baked Products", "Cookies, chocolate chip", "sweets"),
        ("Baked Products", "Archway Home Style Cookies, Iced Molasses", "sweets"),
        ("Baked Products", "Pie, lemon meringue", "sweets"),
        ("Baked Products", "Crackers, saltines", "snacks"),
        ("Baked Products", "Bread, white, commercially prepared", "grains"),
        ("Baked Products", "Pancakes, plain", "grains"),
    ],
)
def test_mixed_usda_categories_split_by_description(
    category: str, description: str, expected: str
) -> None:
    assert food_group_key(FdcDataset.SR_LEGACY, category, description, MAPPINGS) == expected


def test_survey_categories_are_not_split_because_they_are_already_specific() -> None:
    assert food_group_key(FdcDataset.FNDDS, "Citrus juice", "Lemon juice", MAPPINGS) == "beverages"


def test_a_food_with_no_category_has_no_group() -> None:
    assert food_group_key(FdcDataset.FNDDS, None, "Mystery", MAPPINGS) is None
    assert food_group_key(FdcDataset.SR_LEGACY, "Not a category", "Mystery", MAPPINGS) is None


def test_every_group_and_source_in_the_mappings_exists_in_the_vocabulary() -> None:
    bundle = read_bundle()
    groups = {g.key for g in bundle.vocabularies.food_groups}
    used = {*MAPPINGS.sr_groups.values(), *MAPPINGS.wweia_groups.values()}
    used |= {o.group for o in MAPPINGS.sr_overrides}
    assert used <= groups

    sources = {s.key for s in bundle.sources}
    assert set(MAPPINGS.dataset_sources.values()) <= sources
    assert CLASSIFICATION_SOURCE_KEY in sources


def test_every_dataset_is_pinned_by_hash() -> None:
    assert set(MAPPINGS.dataset_hashes) == set(FdcDataset)
    assert all(len(pin) == 64 for pin in MAPPINGS.dataset_hashes.values())


@pytest.mark.parametrize(
    ("derivation", "expected"),
    [
        (None, ValueKind.SOURCE_REPORTED),
        (
            "Assumed zero (Insignificant amount or not naturally occurring in a food, such as fiber in meat)",
            ValueKind.ASSUMED_ZERO,
        ),
        ("Analytical", ValueKind.ANALYTICAL),
        ("Analytical data; derived by linear regression", ValueKind.ANALYTICAL),
        (
            "Analytical data; from the literature or  government;  incomplete documentation",
            ValueKind.ANALYTICAL,
        ),
        (
            "Manufacturer supplied(industry or trade association), Analytical data, incomplete documentation",
            ValueKind.ANALYTICAL,
        ),
        ("Calculated", ValueKind.CALCULATED),
        ("Summed", ValueKind.CALCULATED),
        ("Recipe; Cookbook", ValueKind.CALCULATED),
        (
            "Based on physical composition; Derived from analytical data; Known physical composition",
            ValueKind.CALCULATED,
        ),
        (
            "Estimated formulation based on ingredient list; Linear program used to estimate ingredients; Claim on label/serving",
            ValueKind.CALCULATED,
        ),
        (
            "Manufacturer supplied; Calculated by manufacturer or unknown if analytical or calculated",
            ValueKind.CALCULATED,
        ),
        (
            "Nutrient that is based on other nutrient/s; value used directly, ex. Nut.#204 from Nut.#298",
            ValueKind.CALCULATED,
        ),
        (
            "Aggregated data involving combinations of data with only source codes 1 and 12 and/or 13",
            ValueKind.CALCULATED,
        ),
        (
            "Concentration adjustment using factor; derived from analytical data",
            ValueKind.CALCULATED,
        ),
        (
            "Label claim (back calculated from label by NDL staff; Calculated from label claim/serving (g or %RDI)",
            ValueKind.LABEL,
        ),
        (
            "Manufacturer supplied; Value upon which manufacturer based label claim for fortified/enriched nutrient",
            ValueKind.LABEL,
        ),
        (
            "Based on another form of the food or similar food; Concentration adjustment; Fat; Retention factors not used",
            ValueKind.IMPUTED,
        ),
        (
            "Based on physical composition; Derived from imputed data; Known physical composition",
            ValueKind.IMPUTED,
        ),
        (
            "Calculated from different food; From average values for food category; No adjustment; Retention factors not used",
            ValueKind.IMPUTED,
        ),
        ("Other procedure used from imputing", ValueKind.IMPUTED),
        ("Taken from another source--other tables of food composition", ValueKind.IMPUTED),
        (
            "Product standard, such as enrichment level specified in CFR or AMS commodity standard",
            ValueKind.SOURCE_REPORTED,
        ),
    ],
)
def test_value_kind(derivation: str | None, expected: ValueKind) -> None:
    assert value_kind(derivation) is expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("1 cup", True),
        ("1 cup, chopped", True),
        ("2 tablespoon", True),
        ("Quantity not specified", False),
        ("Guideline amount per fl oz of beverage", False),
        ("1 RACC", False),
    ],
)
def test_household_measures(description: str, expected: bool) -> None:
    assert is_household_measure(description) is expected


def test_discoverability() -> None:
    assert is_discoverable("Spinach, raw", "vegetables") is True
    assert is_discoverable("Spinach, cooked, as ingredient", "vegetables") is False
    assert is_discoverable("Applesauce, strained", "baby_foods") is False


SR_EGG = IngredientRecord(1, "egg whole raw fresh")
FOUNDATION_EGG = IngredientRecord(2, "eggs grade a large egg whole")
FNDDS_FOOD = IngredientRecord(3, "milk nfs")


def test_foundation_wins_when_usda_names_its_record_and_not_the_other() -> None:
    assert resolve_ingredient("Eggs, Grade A, Large, egg whole", SR_EGG, FOUNDATION_EGG, None) == 2


def test_standard_reference_wins_when_usda_names_it() -> None:
    assert resolve_ingredient("Egg, whole, raw, fresh", SR_EGG, FOUNDATION_EGG, None) == 1


def test_standard_reference_wins_when_both_names_match() -> None:
    same = IngredientRecord(2, "egg whole raw fresh")
    assert resolve_ingredient("Egg, whole, raw, fresh", SR_EGG, same, None) == 1


def test_standard_reference_wins_when_neither_name_matches() -> None:
    assert resolve_ingredient("Eggs, large", SR_EGG, FOUNDATION_EGG, None) == 1


def test_a_number_only_foundation_has_resolves_to_foundation() -> None:
    assert resolve_ingredient("Anything", None, FOUNDATION_EGG, None) == 2


def test_survey_foods_resolve_through_their_own_code() -> None:
    assert resolve_ingredient("Milk, NFS", None, None, FNDDS_FOOD) == 3


def test_an_ingredient_with_no_record_resolves_to_nothing() -> None:
    assert resolve_ingredient("Iron as ingredient", None, None, None) is None
