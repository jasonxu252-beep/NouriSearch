"""All tables, imported together so Alembic and the metadata see the complete schema."""

from app.db.models.catalog import (
    Cuisine,
    Food,
    FoodAlias,
    FoodCuisine,
    FoodExternalRef,
    FoodGroup,
    FoodImage,
    FoodPortion,
)
from app.db.models.composition import (
    IngredientRole,
    PreparationEffect,
    PreparationMethod,
    Recipe,
    RecipeComponent,
    RecipePreparation,
)
from app.db.models.education import (
    HealthEffect,
    HealthFunction,
    NutrientFunction,
    NutrientHealthEffect,
)
from app.db.models.nutrition import (
    FoodNutrient,
    Nutrient,
    NutrientProxy,
    NutrientReferenceValue,
    NutrientSourceCode,
    NutrientTranslation,
)
from app.db.models.provenance import Source
from app.db.models.safety import (
    Allergen,
    FoodAllergen,
    FoodClassification,
    FoodHealthConsideration,
    HealthConsideration,
)
from app.db.models.substitution import (
    FoodRole,
    FoodSensory,
    SensoryAttribute,
    SubstitutionComponent,
    SubstitutionOption,
)

__all__ = [
    "Allergen",
    "Cuisine",
    "Food",
    "FoodAlias",
    "FoodAllergen",
    "FoodClassification",
    "FoodCuisine",
    "FoodExternalRef",
    "FoodGroup",
    "FoodHealthConsideration",
    "FoodImage",
    "FoodNutrient",
    "FoodPortion",
    "FoodRole",
    "FoodSensory",
    "HealthConsideration",
    "HealthEffect",
    "HealthFunction",
    "IngredientRole",
    "Nutrient",
    "NutrientFunction",
    "NutrientHealthEffect",
    "NutrientProxy",
    "NutrientReferenceValue",
    "NutrientSourceCode",
    "NutrientTranslation",
    "PreparationEffect",
    "PreparationMethod",
    "Recipe",
    "RecipeComponent",
    "RecipePreparation",
    "SensoryAttribute",
    "Source",
    "SubstitutionComponent",
    "SubstitutionOption",
]
