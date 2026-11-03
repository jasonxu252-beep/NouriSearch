"""Pure rules that turn USDA records into NouriSearch classifications.

USDA has no "whole food" field, and its fruit category includes juices and jams. These rules read
the description to decide. When no rule applies, the answer is unknown rather than a guess.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.domain.enums import FoodKind, ProcessingLevel, ValueKind
from app.domain.text import normalize_name
from app.integrations.fdc_bulk import FdcDataset

MAPPINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "curated" / "fdc_mappings.yaml"

# Cited for processing levels, which are this project's judgment and never USDA's.
CLASSIFICATION_SOURCE_KEY = "nourisearch-derived-from-fdc"

# Foods in these groups are made products. A cookie is never whole, whatever its description says.
_PROCESSED_GROUPS = frozenset({"sweets", "snacks", "fats_oils", "baby_foods", "mixed_dishes"})

# "With salt" alone is left out, because USDA lists boiled vegetables with and without cooking salt.
# Baby foods have their own group, so "baby" here would only catch "Carrots, baby, raw".
_PROCESSED_WORDS = re.compile(
    r"\b("
    r"juice|nectar|drink|concentrate|canned|sweetened|syrup|sugar(?![- ](?:apple|snap))|candied|"
    r"jam|jelly|sauce|gravy|soup|salted|with salt added|cured|smoked|pickled|pickles?|brine|"
    # Some of these words also name cuts or varieties, such as a "leg (ham)" of fresh pork, a beef
    # "cube roll", spaghetti squash, and "pie pumpkin". The lookarounds keep those out.
    r"sausage|bacon|ham(?!\))|frankfurter|luncheon|bologna|salami|breaded|battered|fried|chips|"
    r"puffs|puffed|crackers?|cookies?|cake|pie(?! pumpkin)|pastry|pastries|bread|"
    r"(?<!cube )(?<!eye )rolls?|muffins?|bagels?|tortillas?|pancakes?|waffles?|cereal|"
    r"ready-to-eat|ready-to-heat|pizza|sandwich|burger|nuggets?|patties|patty|stuffing|flour|meal|"
    r"starch|pasta|noodles?|(?<!squash, )spaghetti|macaroni|enriched|instant|powder|powdered|"
    r"extract|imitation|substitute|analog|formulated|fortified|restaurant|fast food|with added|"
    r"fat added|(?<!ribs )prepared|mix|paste|spread|butter|oil|margarine|dressing|frozen dinner|"
    r"entree|snack|bars?|alcoholic|wine|beer|liquor|carbonated|creamer|hot dogs?|mortadella|"
    r"pastrami|loaf|croutons?|biscuits?|dough|meatless"
    r")\b",
    re.IGNORECASE,
)
_MINIMAL_WORDS = re.compile(
    r"\b(cooked|boiled|steamed|baked|roasted|broiled|grilled|braised|stewed|microwaved|"
    r"frozen|dried|dehydrated|unprepared|from fresh|from dried|from frozen|blanched|sprouted|"
    r"rolled|hulled|shelled|pasteurized|dry)\b",
    re.IGNORECASE,
)
_RAW_WORD = re.compile(r"\braw\b|\bfresh\b|\buncooked\b", re.IGNORECASE)

# USDA's "NS as to" means "not specified", and these words appear in plain foods too.
_NOT_SPECIFIED = re.compile(r"\bns as to [^,;]*", re.IGNORECASE)

# USDA's reference amount for labels, not something a person would recognize as a serving.
_REFERENCE_AMOUNT = re.compile(r"\bracc\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IngredientRecord:
    food_id: int
    normalized_name: str


@dataclass(frozen=True, slots=True)
class DescriptionOverride:
    category: str
    pattern: re.Pattern[str]
    group: str


@dataclass(frozen=True, slots=True)
class FdcMappings:
    sr_groups: Mapping[str, str]
    sr_dish_categories: frozenset[str]
    wweia_groups: Mapping[str, str]
    sr_overrides: Sequence[DescriptionOverride] = ()
    dataset_files: Mapping[FdcDataset, str] = field(default_factory=dict)
    dataset_sources: Mapping[FdcDataset, str] = field(default_factory=dict)
    dataset_hashes: Mapping[FdcDataset, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = MAPPINGS_PATH) -> "FdcMappings":
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        wweia = {
            category: group
            for group, categories in raw["wweia_groups"].items()
            for category in categories
        }
        datasets = raw["datasets"]
        return cls(
            sr_groups=raw["sr_categories"],
            sr_dish_categories=frozenset(raw["sr_dish_categories"]),
            wweia_groups=wweia,
            sr_overrides=tuple(
                DescriptionOverride(
                    o["category"], re.compile(o["pattern"], re.IGNORECASE), o["group"]
                )
                for o in raw["sr_description_overrides"]
            ),
            dataset_files={FdcDataset(k): v["file"] for k, v in datasets.items()},
            dataset_sources={FdcDataset(k): v["source_key"] for k, v in datasets.items()},
            dataset_hashes={FdcDataset(k): v["sha256"] for k, v in datasets.items()},
        )


def food_group_key(
    dataset: FdcDataset, category: str | None, description: str, mappings: FdcMappings
) -> str | None:
    if category is None:
        return None
    if dataset is FdcDataset.FNDDS:
        return mappings.wweia_groups.get(category)
    for override in mappings.sr_overrides:
        if override.category == category and override.pattern.search(description):
            return override.group
    return mappings.sr_groups.get(category)


def _describes_plain_food(description: str) -> bool:
    text = _NOT_SPECIFIED.sub("", description)
    if _PROCESSED_WORDS.search(text):
        return False
    return bool(_MINIMAL_WORDS.search(text) or _RAW_WORD.search(text))


def food_kind(
    dataset: FdcDataset,
    category: str | None,
    description: str,
    group_key: str | None,
    ingredient_count: int,
    mappings: FdcMappings,
) -> FoodKind:
    """A dish is a mixed-dish food, or a food USDA builds from three or more ingredients.

    A recipe alone does not make a dish. USDA's "Apple, raw" is a blend of three apple varieties,
    and "Broccoli, cooked" is broccoli, water, and salt, so a plain description overrides the count.
    """
    if dataset is not FdcDataset.FNDDS:
        if category in mappings.sr_dish_categories:
            return FoodKind.PREPARED_DISH
        return FoodKind.BASIC
    if group_key == "mixed_dishes":
        return FoodKind.PREPARED_DISH
    if ingredient_count >= 3 and not _describes_plain_food(description):
        return FoodKind.PREPARED_DISH
    return FoodKind.BASIC


def processing_level(description: str, kind: FoodKind, group_key: str | None) -> ProcessingLevel:
    """Classifies conservatively. Whole means the description itself supports it.

    Cooking or freezing a food takes it from whole to minimally processed, so that check runs before
    the raw check. "Cooked, from fresh" and "raw, frozen" both describe changed foods.
    """
    if kind is FoodKind.PREPARED_DISH or group_key in _PROCESSED_GROUPS:
        return ProcessingLevel.PROCESSED
    if group_key is None:
        return ProcessingLevel.UNKNOWN

    text = _NOT_SPECIFIED.sub("", description)
    if _PROCESSED_WORDS.search(text):
        return ProcessingLevel.PROCESSED
    if _MINIMAL_WORDS.search(text):
        return ProcessingLevel.MINIMALLY_PROCESSED
    if _RAW_WORD.search(text):
        return ProcessingLevel.WHOLE
    return ProcessingLevel.UNKNOWN


def value_kind(derivation: str | None) -> ValueKind:
    """Maps USDA's free-text derivation onto our vocabulary, keeping "assumed zero" distinct.

    The original text is stored too, so this grouping never loses what USDA said. Order matters:
    "Calculated from different food" is a borrowed value despite starting with "calculated".
    """
    if derivation is None:
        return ValueKind.SOURCE_REPORTED
    text = derivation.casefold()
    if text.startswith("assumed zero"):
        return ValueKind.ASSUMED_ZERO
    if (
        "imputed" in text
        or "imputing" in text
        or text.startswith(
            ("based on another form", "calculated from different food", "taken from another source")
        )
    ):
        return ValueKind.IMPUTED
    if "label claim" in text:
        return ValueKind.LABEL
    if text.startswith(("analytical", "manufacturer supplied(")):
        return ValueKind.ANALYTICAL
    if text.startswith(
        (
            "calculated",
            "summed",
            "recipe",
            "based on",
            "estimated",
            "nutrient that is based",
            "aggregated",
            "concentration adjustment",
            "manufacturer supplied",
        )
    ):
        return ValueKind.CALCULATED
    return ValueKind.SOURCE_REPORTED


def resolve_ingredient(
    description: str,
    sr: IngredientRecord | None,
    foundation: IngredientRecord | None,
    fndds: IngredientRecord | None,
) -> int | None:
    """Picks the record a recipe cites, given every record holding its ingredient code.

    Foundation and SR Legacy share numbers for the same food, freshly analyzed in Foundation. USDA's
    ingredient name shows which one it used. Matching that name measurably improves how closely
    dishes rebuild, so Foundation wins when only its name matches.
    """
    if foundation is not None:
        name = normalize_name(description)
        names_foundation = foundation.normalized_name == name
        if sr is None or (names_foundation and sr.normalized_name != name):
            return foundation.food_id
    if sr is not None:
        return sr.food_id
    return fndds.food_id if fndds is not None else None


def is_household_measure(description: str) -> bool:
    """False for placeholders like "Quantity not specified", guideline amounts, and label RACCs."""
    lowered = description.casefold()
    return not (
        "not specified" in lowered
        or "guideline amount" in lowered
        or _REFERENCE_AMOUNT.search(lowered)
    )


def is_discoverable(description: str, group_key: str | None) -> bool:
    """Ingredient-only records and baby foods stay out of general results, but stay queryable."""
    return not description.casefold().endswith("as ingredient") and group_key != "baby_foods"
