/** A small dish in the API's exact shape, with one of every case the page has to handle. */

import type {
  Conclusion,
  ContributionCell,
  FoodComposition,
  Ingredient,
  Nutrient,
  RelatedFoods,
  ServingEvaluation,
  ServingNutrient,
  SubstitutionOption,
  Substitutions,
} from "../api/client";

export const SALT = 1;
export const TOFU = 2;
export const PASTE = 3;
export const SOY_SAUCE = 4;

function ingredient(
  componentId: number,
  name: string,
  weight: number | null,
  overrides: Partial<Ingredient> = {},
): Ingredient {
  return {
    component_id: componentId,
    food_id: 100 + componentId,
    name,
    kind: "basic",
    weight_g: weight,
    weight_share: null,
    has_own_recipe: false,
    excluded: false,
    edit: "none",
    original_weight_g: weight,
    replaces_component_id: null,
    allergens: [],
    considerations: [],
    ...overrides,
  };
}

export function nutrient(key: string, name: string, overrides: Partial<Nutrient> = {}): Nutrient {
  return {
    key,
    name,
    unit: "mg",
    category: "mineral",
    direction: "neutral",
    status: "known",
    amount_per_100g: 1,
    base_amount_per_100g: null,
    delta_per_100g: null,
    approximate: false,
    value_kind: "source_reported",
    derivation: null,
    daily_value: 100,
    daily_value_source_key: "fda-daily-values",
    source_keys: ["usda-fdc-fndds-2024-10"],
    missing_ingredients: [],
    ...overrides,
  };
}

function cell(
  nutrientKey: string,
  componentId: number,
  share: number | null,
  status: ContributionCell["status"] = "known",
): ContributionCell {
  return {
    nutrient_key: nutrientKey,
    component_id: componentId,
    status,
    amount: share,
    share,
    estimated: false,
  };
}

const NUTRIENTS: Nutrient[] = [
  nutrient("sodium", "Sodium", { direction: "limit", amount_per_100g: 395, daily_value: 2300 }),
  nutrient("saturated_fat", "Saturated fat", {
    unit: "g",
    category: "macronutrient",
    direction: "limit",
    status: "lower_bound",
    amount_per_100g: 2,
    value_kind: "calculated",
    daily_value: 20,
    missing_ingredients: ["Doubanjiang"],
  }),
  nutrient("total_sugars", "Total sugars", {
    unit: "g",
    category: "macronutrient",
    amount_per_100g: 2.5,
    daily_value: null,
    daily_value_source_key: null,
  }),
  nutrient("added_sugars", "Added sugars", {
    unit: "g",
    category: "macronutrient",
    direction: "limit",
    status: "unknown",
    amount_per_100g: null,
    value_kind: null,
    daily_value: 50,
    source_keys: [],
    missing_ingredients: ["Salt, table", "Tofu"],
  }),
  nutrient("vitamin_c", "Vitamin C", {
    category: "vitamin",
    status: "unknown",
    amount_per_100g: null,
    value_kind: null,
    daily_value: 90,
    source_keys: [],
  }),
  nutrient("vitamin_d", "Vitamin D", {
    unit: "µg",
    category: "vitamin",
    amount_per_100g: 0,
    daily_value: 20,
  }),
  nutrient("iron", "Iron", { amount_per_100g: 1.5, daily_value: 18 }),
  nutrient("manganese", "Manganese", {
    status: "lower_bound",
    amount_per_100g: 0.2,
    value_kind: "calculated",
    daily_value: 2.3,
    missing_ingredients: ["Doubanjiang"],
  }),
  nutrient("vitamin_k", "Vitamin K", {
    unit: "µg",
    category: "vitamin",
    amount_per_100g: 100,
    daily_value: 120,
  }),
];

function serving(values: Record<string, [number | null, number | null, ServingNutrient["mark"]]>) {
  return Object.entries(values).map(([key, [amount, percent, mark]]): ServingNutrient => ({
    key,
    amount,
    percent_daily_value: percent,
    mark,
  }));
}

function conclusion(
  subject: string,
  messageKey: string,
  severity: Conclusion["severity"],
  params: Record<string, number | string>,
  overrides: Partial<Conclusion> = {},
): Conclusion {
  return {
    code: "nutrient.high_percent_daily_value",
    severity,
    subject,
    message_key: messageKey,
    message_params: { threshold: 20, ...params },
    supporting_facts: [],
    rules_triggered: [{ id: "nutrient.high_percent_daily_value", version: 1 }],
    sources: ["fda-percent-dv-guide", "fda-daily-values", "usda-fdc-fndds-2024-10"],
    uncertainty: "verified",
    missing: [],
    ...overrides,
  };
}

const CUP: ServingEvaluation = {
  serving_key: "portion-0",
  nutrients: serving({
    sodium: [790, 34.3, "exclamation"],
    saturated_fat: [4, 20, "exclamation"],
    total_sugars: [5, null, "green"],
    added_sugars: [null, null, "question"],
    vitamin_c: [null, null, "question"],
    vitamin_d: [0, 0, "green"],
    iron: [3, 16.7, "green"],
    manganese: [0.4, 17.4, "question"],
    vitamin_k: [200, 166.7, "green"],
  }),
  conclusions: [
    conclusion("sodium", "conclusion.high_percent_daily_value", "high", {
      serving: "1 cup",
      percent: 34.35,
    }),
    conclusion(
      "saturated_fat",
      "conclusion.high_percent_daily_value.lower_bound",
      "high",
      { serving: "1 cup", percent: 20 },
      { uncertainty: "inferred", missing: ["Doubanjiang"] },
    ),
    conclusion(
      "added_sugars",
      "conclusion.could_not_evaluate.no_value",
      "undetermined",
      { serving: "1 cup" },
      { code: "nutrient.could_not_evaluate" },
    ),
  ],
};

const PER_100G: ServingEvaluation = {
  serving_key: "per-100g",
  nutrients: serving({
    sodium: [395, 17.17, "green"],
    saturated_fat: [2, 10, "question"],
    total_sugars: [2.5, null, "green"],
    added_sugars: [null, null, "question"],
    vitamin_c: [null, null, "question"],
    vitamin_d: [0, 0, "green"],
    iron: [1.5, 8.3, "green"],
    manganese: [0.2, 8.7, "question"],
    vitamin_k: [100, 83.3, "green"],
  }),
  conclusions: [
    conclusion(
      "sodium",
      "conclusion.not_high_percent_daily_value",
      "not_flagged",
      { serving: "100 g", percent: 17.17 },
      { code: "nutrient.not_high_percent_daily_value" },
    ),
    conclusion(
      "saturated_fat",
      "conclusion.could_not_evaluate.lower_bound",
      "undetermined",
      { serving: "100 g", percent: 10 },
      { code: "nutrient.could_not_evaluate", missing: ["Doubanjiang"] },
    ),
    conclusion(
      "added_sugars",
      "conclusion.could_not_evaluate.no_value",
      "undetermined",
      { serving: "100 g" },
      { code: "nutrient.could_not_evaluate" },
    ),
  ],
};

export function dish(overrides: Partial<FoodComposition> = {}): FoodComposition {
  return {
    id: 7,
    slug: "mapo-tofu-7",
    name: "Mapo tofu",
    description: null,
    kind: "prepared_dish",
    food_group_key: "mixed_dishes",
    food_group_name: "Mixed dishes",
    processing_level: "processed",
    processing_level_source_key: "nourisearch-derived-from-fdc",
    source_key: "usda-fdc-fndds-2024-10",
    is_modified: false,
    high_percent_daily_value: 20,
    images: [],
    allergens: [],
    recipe: {
      label: "USDA survey recipe",
      moisture_change_pct: 0,
      raw_weight_g: 100,
      cooked_weight_g: 100,
    },
    servings: [
      {
        key: "portion-0",
        label: "1 cup",
        grams: 200,
        is_household_measure: true,
        is_default: true,
      },
      {
        key: "per-100g",
        label: "100 g",
        grams: 100,
        is_household_measure: false,
        is_default: false,
      },
    ],
    ingredients: [
      ingredient(SALT, "Salt, table", 1),
      ingredient(TOFU, "Tofu", 80),
      ingredient(PASTE, "Doubanjiang", 19),
      ingredient(SOY_SAUCE, "Soy sauce", null),
    ],
    nutrients: NUTRIENTS,
    contributions: [
      cell("sodium", SALT, 0.91),
      cell("sodium", TOFU, 0.02),
      cell("sodium", PASTE, null, "no_data"),
      cell("sodium", SOY_SAUCE, null, "no_quantity"),
      cell("iron", TOFU, 0.8),
      cell("iron", SALT, 0),
      cell("iron", PASTE, 0.06, "partial"),
      cell("vitamin_k", TOFU, 0.3),
    ],
    evaluations: [CUP, PER_100G],
    sources: [
      {
        key: "usda-fdc-fndds-2024-10",
        publisher: "U.S. Department of Agriculture",
        title: "FoodData Central, Survey Foods",
        url: "https://fdc.nal.usda.gov/download-datasets",
        version: "2024-10-31",
        license: "CC0-1.0",
      },
      {
        key: "fda-daily-values",
        publisher: "U.S. Food and Drug Administration",
        title: "Daily Value on the Nutrition and Supplement Facts Labels",
        url: "https://www.fda.gov/dv",
        version: null,
        license: null,
      },
      {
        key: "fda-percent-dv-guide",
        publisher: "U.S. Food and Drug Administration",
        title: "The Lows and Highs of Percent Daily Value",
        url: "https://www.fda.gov/guide",
        version: null,
        license: null,
      },
    ],
    ...overrides,
  };
}

/** What the API answers once salt leaves the recipe: sodium falls and its mark clears. */
export function dishWithoutSalt(): FoodComposition {
  const base = dish();
  return {
    ...base,
    is_modified: true,
    ingredients: base.ingredients.map((item) =>
      item.component_id === SALT ? { ...item, excluded: true, edit: "removed" as const } : item,
    ),
    nutrients: base.nutrients.map((item) => {
      if (item.key === "sodium") {
        return {
          ...item,
          status: "calculated" as const,
          amount_per_100g: 7,
          base_amount_per_100g: 395,
          delta_per_100g: -388,
          value_kind: "calculated" as const,
        };
      }
      if (item.key === "iron") {
        return { ...item, base_amount_per_100g: 1.5, delta_per_100g: 0.06 };
      }
      return item;
    }),
    contributions: base.contributions.filter((item) => item.component_id !== SALT),
    evaluations: [
      {
        ...CUP,
        nutrients: CUP.nutrients.map((item) =>
          item.key === "sodium"
            ? { ...item, amount: 14, percent_daily_value: 0.6, mark: "green" as const }
            : item,
        ),
        conclusions: CUP.conclusions.map((item) =>
          item.subject === "sodium"
            ? conclusion("sodium", "conclusion.not_high_percent_daily_value", "not_flagged", {
                serving: "1 cup",
                percent: 0.6,
              })
            : item,
        ),
      },
      PER_100G,
    ],
  };
}

export const RELATED: RelatedFoods = {
  similar: [
    {
      id: 8,
      slug: "tofu-stew-8",
      name: "Tofu stew",
      kind: "prepared_dish",
      food_group: "mixed_dishes",
      reason: "shares_ingredients",
      shared_ingredients: ["Doubanjiang", "Salt, table"],
    },
  ],
  explore: [
    {
      id: 9,
      slug: "fried-rice-9",
      name: "Fried rice",
      kind: "prepared_dish",
      food_group: "mixed_dishes",
      reason: "same_group",
      shared_ingredients: [],
    },
  ],
};

/** A ranked replacement in the API's exact shape. */
export function option(overrides: Partial<SubstitutionOption> = {}): SubstitutionOption {
  return {
    key: "option-1",
    origin: "curated",
    edit: {
      type: "replace",
      component_id: SALT,
      replacements: [{ food_id: 501, ratio: 1 }],
    },
    replacements: [{ food_id: 501, name: "Lemon juice", ratio: 1, weight_g: 1 }],
    scale_factor: null,
    goal_effect: {
      nutrient_key: "sodium",
      unit: "mg",
      before_per_100g: 395,
      after_per_100g: 200,
      approximate: false,
    },
    scores: {
      nutrition: 0.9,
      flavor: 0.31,
      texture: null,
      culinary_fit: 0.75,
      preference: null,
      total: 0.8,
      completeness: 1,
    },
    reasons: [],
    allergens: [],
    note: null,
    verification: "typical",
    source_keys: [],
    ...overrides,
  };
}

export function substitutions(overrides: Partial<Substitutions> = {}): Substitutions {
  return {
    food_id: 7,
    component_id: SALT,
    goal: "less_sodium",
    nutrient_key: "sodium",
    serving_label: "1 cup",
    unavailable_reason: null,
    options: [option()],
    hidden_for_allergens: 0,
    hidden_for_diet: 0,
    could_not_evaluate: [],
    sources: [],
    ...overrides,
  };
}
