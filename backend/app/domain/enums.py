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
    FNDDS_CODE = "fndds_code"
    WIKIDATA = "wikidata"
    BARCODE = "barcode"


class AliasType(StrEnum):
    PREFERRED = "preferred"
    SYNONYM = "synonym"
    ROMANIZATION = "romanization"
    SOURCE_LABEL = "source_label"
    MACHINE_TRANSLATED = "machine_translated"
