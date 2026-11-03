"""Controlled vocabularies shared by the database and the domain logic."""

from enum import StrEnum


class FoodKind(StrEnum):
    """What a catalog entry is. "Ingredient" is deliberately absent: it is a role, not a kind."""

    BASIC = "basic"
    PREPARED_DISH = "prepared_dish"
    PACKAGED_PRODUCT = "packaged_product"
    ADDITIVE = "additive"


class ProcessingLevel(StrEnum):
    WHOLE = "whole"
    MINIMALLY_PROCESSED = "minimally_processed"
    PROCESSED = "processed"
    UNKNOWN = "unknown"


class Verification(StrEnum):
    """How we know a relationship holds."""

    SOURCE_DOCUMENTED = "source_documented"
    TYPICAL = "typical"
    ESTIMATED = "estimated"
    USER_REPORTED = "user_reported"


class EvidenceLevel(StrEnum):
    """How strong the support for a health claim is."""

    AUTHORITATIVE_BODY = "authoritative_body"
    SYSTEMATIC_REVIEW = "systematic_review"
    OBSERVATIONAL = "observational"
    EDITORIAL = "editorial"
    INFERRED = "inferred"


class SourceTier(StrEnum):
    REGULATORY = "regulatory"
    AUTHORITATIVE_REFERENCE = "authoritative_reference"
    GOVERNMENT_DATASET = "government_dataset"
    OPEN_DATA = "open_data"
    EDITORIAL = "editorial"
    USER_CONTRIBUTED = "user_contributed"


class ValueKind(StrEnum):
    """How a nutrient value was obtained. Zero means different things across these kinds."""

    ANALYTICAL = "analytical"
    CALCULATED = "calculated"
    IMPUTED = "imputed"
    ASSUMED_ZERO = "assumed_zero"
    LABEL = "label"
    SOURCE_REPORTED = "source_reported"


class NutrientStatus(StrEnum):
    """How a value reached a reader. Only `unknown` has no number, and it never becomes zero."""

    # The food's own value, as a source states it.
    KNOWN = "known"
    # Borrowed from a similar food through a nutrient proxy.
    ESTIMATED = "estimated"
    # Rebuilt from a recipe in which every ingredient had a value.
    CALCULATED = "calculated"
    # Rebuilt from a recipe with gaps, so the true value is at least this much.
    LOWER_BOUND = "lower_bound"
    UNKNOWN = "unknown"


class NutrientMark(StrEnum):
    """The mark beside a nutrient. Green requires a known value, so it never reassures falsely."""

    EXCLAMATION = "exclamation"
    GREEN = "green"
    QUESTION = "question"


class ConclusionSeverity(StrEnum):
    HIGH = "high"
    # The rule ran on complete data and did not fire.
    NOT_FLAGGED = "not_flagged"
    # The rule could not evaluate, which is never the same as finding no concern.
    UNDETERMINED = "undetermined"


class Uncertainty(StrEnum):
    VERIFIED = "verified"
    INFERRED = "inferred"


class FoodTypeFilter(StrEnum):
    """The search filters from the owner's sketches. Each one excludes everything else."""

    ALL = "all"
    WHOLE_FOODS = "whole_foods"
    FRUITS = "fruits"
    VEGETABLES = "vegetables"
    PROTEINS = "proteins"
    GRAINS = "grains"
    DISHES = "dishes"
    INGREDIENTS = "ingredients"


class RelatedReason(StrEnum):
    SHARES_INGREDIENTS = "shares_ingredients"
    USES_THIS_FOOD = "uses_this_food"
    SIMILAR_NAME = "similar_name"
    SAME_GROUP = "same_group"


class SearchMatch(StrEnum):
    """Why a food matched a query, strongest first."""

    EXACT = "exact"
    PREFIX = "prefix"
    WORD_PREFIX = "word_prefix"
    ALL_WORDS = "all_words"
    SIMILAR = "similar"


class NutrientCategory(StrEnum):
    MACRONUTRIENT = "macronutrient"
    VITAMIN = "vitamin"
    MINERAL = "mineral"
    FIBER = "fiber"
    OTHER = "other"


class NutrientDirection(StrEnum):
    """Whether general guidance favors less or more of a nutrient."""

    LIMIT = "limit"
    ENCOURAGE = "encourage"
    NEUTRAL = "neutral"


class ReferenceKind(StrEnum):
    DV = "dv"
    RDA = "rda"
    AI = "ai"
    UL = "ul"
    CDRR = "cdrr"
    # A label's general guide that is not a Daily Value, such as the FDA's 2,000 calories.
    LABEL_GUIDE = "label_guide"


# The population FDA Daily Values apply to on a food label.
GENERAL_LABEL_POPULATION = "general_label"


class ReferencePopulation(StrEnum):
    """Who a daily amount applies to, in the life stages the National Academies publish."""

    GENERAL_LABEL = GENERAL_LABEL_POPULATION
    CHILD_1_3 = "child_1_3"
    CHILD_4_8 = "child_4_8"
    MALE_9_13 = "male_9_13"
    MALE_14_18 = "male_14_18"
    MALE_19_30 = "male_19_30"
    MALE_31_50 = "male_31_50"
    MALE_51_70 = "male_51_70"
    MALE_71_PLUS = "male_71_plus"
    FEMALE_9_13 = "female_9_13"
    FEMALE_14_18 = "female_14_18"
    FEMALE_19_30 = "female_19_30"
    FEMALE_31_50 = "female_31_50"
    FEMALE_51_70 = "female_51_70"
    FEMALE_71_PLUS = "female_71_plus"


class AllergenRelation(StrEnum):
    CONTAINS = "contains"
    MAY_CONTAIN = "may_contain"
    FREE_OF = "free_of"


class ConsiderationCategory(StrEnum):
    SODIUM = "sodium"
    SATURATED_FAT = "saturated_fat"
    ADDED_SUGAR = "added_sugar"
    FOOD_SAFETY = "food_safety"
    PRESERVATION = "preservation"
    ADDITIVE = "additive"
    LONG_TERM = "long_term"


class FoodClassificationKind(StrEnum):
    ADDED_SUGAR_SOURCE = "added_sugar_source"
    ARTIFICIAL_COLOR = "artificial_color"
    PRESERVED = "preserved"


class EffectContext(StrEnum):
    INADEQUATE = "inadequate"
    EXCESS = "excess"


class EffectType(StrEnum):
    CONSEQUENCE = "consequence"
    WARNING_SIGN = "warning_sign"


class EffectDirection(StrEnum):
    INCREASES = "increases"
    DECREASES = "decreases"
    VARIABLE = "variable"


class SensoryKind(StrEnum):
    FLAVOR = "flavor"
    TEXTURE = "texture"


class ExternalSystem(StrEnum):
    FDC = "fdc"
    NDB_NUMBER = "ndb_number"
    # Foundation records reuse SR Legacy's numbers for the same food, so they need their own system.
    FOUNDATION_NDB = "foundation_ndb"
    FNDDS_CODE = "fndds_code"
    WIKIDATA = "wikidata"
    BARCODE = "barcode"


class AliasType(StrEnum):
    PREFERRED = "preferred"
    SYNONYM = "synonym"
    ROMANIZATION = "romanization"
    SOURCE_LABEL = "source_label"
    MACHINE_TRANSLATED = "machine_translated"
