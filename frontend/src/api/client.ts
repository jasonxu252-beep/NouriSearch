/** The typed API client. Its types are generated from the backend's OpenAPI document. */

import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type FoodComposition = Schemas["FoodCompositionResponse"];
export type Ingredient = Schemas["IngredientResponse"];
export type Nutrient = Schemas["CompositionNutrientResponse"];
export type ContributionCell = Schemas["ContributionResponse"];
export type Serving = Schemas["ServingResponse"];
export type ServingEvaluation = Schemas["ServingEvaluationResponse"];
export type ServingNutrient = Schemas["ServingNutrientResponse"];
export type Conclusion = Schemas["ConclusionResponse"];
export type Source = Schemas["SourceResponse"];
export type FoodImage = Schemas["ImageResponse"];
export type RelatedFood = Schemas["RelatedFoodResponse"];
export type RelatedFoods = Schemas["RelatedFoodsResponse"];
export type FoodSearchResult = Schemas["FoodSearchResult"];
export type FoodSearchResponse = Schemas["FoodSearchResponse"];
export type FoodType = Schemas["FoodTypeFilter"];
export type Mark = Schemas["NutrientMark"];
export type ReferencePopulation = Schemas["ReferencePopulation"];
export type ReferenceValue = Schemas["ReferenceValueResponse"];
export type ReferenceIntakes = Schemas["ReferenceIntakesResponse"];
export type IngredientEdit =
  | Schemas["RemoveIngredientEdit"]
  | Schemas["ScaleIngredientEdit"]
  | Schemas["ReplaceIngredientEdit"]
  | Schemas["AddIngredientEdit"];
export type Goal = Schemas["Goal"];
export type Diet = Schemas["Diet"];
export type DishAllergen = Schemas["DishAllergenResponse"];
export type Substitutions = Schemas["SubstitutionsResponse"];
export type SubstitutionOption = Schemas["SubstitutionOptionResponse"];
export type SubstitutionRequest = Schemas["SubstitutionRequest"];
export type ScoreParts = Schemas["ScoreResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const client = createClient<paths>({
  baseUrl: window.location.origin,
  // Read at call time, so tests can answer requests themselves.
  fetch: (request) => globalThis.fetch(request),
});

function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data === undefined) {
    const message =
      typeof result.error === "object" && result.error !== null && "message" in result.error
        ? String(result.error.message)
        : `The request failed with status ${result.response.status}.`;
    throw new ApiError(result.response.status, message);
  }
  return result.data;
}

export async function fetchComposition(
  foodId: number,
  signal?: AbortSignal,
): Promise<FoodComposition> {
  return unwrap(
    await client.GET("/v1/foods/{food_id}/composition", {
      params: { path: { food_id: foodId } },
      signal,
    }),
  );
}

export async function simulateEdits(
  foodId: number,
  edits: readonly IngredientEdit[],
  signal?: AbortSignal,
): Promise<FoodComposition> {
  return unwrap(
    await client.POST("/v1/foods/{food_id}/simulations", {
      params: { path: { food_id: foodId } },
      body: { edits: [...edits] },
      signal,
    }),
  );
}

export async function fetchSubstitutions(
  foodId: number,
  request: SubstitutionRequest,
  signal?: AbortSignal,
): Promise<Substitutions> {
  return unwrap(
    await client.POST("/v1/foods/{food_id}/substitutions", {
      params: { path: { food_id: foodId } },
      body: request,
      signal,
    }),
  );
}

export async function fetchRelated(foodId: number, signal?: AbortSignal): Promise<RelatedFoods> {
  return unwrap(
    await client.GET("/v1/foods/{food_id}/related", {
      params: { path: { food_id: foodId } },
      signal,
    }),
  );
}

export async function fetchReferenceIntakes(
  population: ReferencePopulation,
  signal?: AbortSignal,
): Promise<ReferenceIntakes> {
  return unwrap(
    await client.GET("/v1/reference-intakes", {
      params: { query: { population } },
      signal,
    }),
  );
}

export async function searchFoods(
  query: string,
  type: FoodType,
  options: { limit?: number; offset?: number; signal?: AbortSignal } = {},
): Promise<FoodSearchResponse> {
  return unwrap(
    await client.GET("/v1/foods/search", {
      params: {
        query: { q: query, type, limit: options.limit ?? 20, offset: options.offset ?? 0 },
      },
      signal: options.signal,
    }),
  );
}
