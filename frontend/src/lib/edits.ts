/** The changes a person has made to a dish. Each ingredient has at most one. */

import type { Goal, Ingredient, IngredientEdit } from "../api/client";
import type { ContributionIndex } from "./contributions";

export function editedComponent(edit: IngredientEdit): number | null {
  return edit.type === "add" ? null : edit.component_id;
}

/** Adds an edit, replacing any earlier one on the same ingredient or adding the same food again. */
export function withEdit(edits: readonly IngredientEdit[], edit: IngredientEdit): IngredientEdit[] {
  const component = editedComponent(edit);
  const kept = edits.filter((existing) => {
    if (edit.type === "add") return !(existing.type === "add" && existing.food_id === edit.food_id);
    return editedComponent(existing) !== component;
  });
  return [...kept, edit];
}

export function withoutComponentEdit(
  edits: readonly IngredientEdit[],
  componentId: number,
): IngredientEdit[] {
  return edits.filter((edit) => editedComponent(edit) !== componentId);
}

export function withoutAddedFood(
  edits: readonly IngredientEdit[],
  foodId: number,
): IngredientEdit[] {
  return edits.filter((edit) => !(edit.type === "add" && edit.food_id === foodId));
}

/** Ingredients that have left the recipe, known as soon as the person acts. */
export function excludedComponents(edits: readonly IngredientEdit[]): ReadonlySet<number> {
  const excluded = new Set<number>();
  for (const edit of edits) {
    if (edit.type === "remove" || edit.type === "replace") excluded.add(edit.component_id);
  }
  return excluded;
}

/** Undoing a new ingredient undoes the edit that brought it in. */
export function withoutNewIngredient(
  edits: readonly IngredientEdit[],
  ingredient: Pick<Ingredient, "replaces_component_id" | "food_id">,
): IngredientEdit[] {
  return ingredient.replaces_component_id === null
    ? withoutAddedFood(edits, ingredient.food_id)
    : withoutComponentEdit(edits, ingredient.replaces_component_id);
}

const LESS_GOALS: readonly { goal: Goal; nutrient: string }[] = [
  { goal: "less_sodium", nutrient: "sodium" },
  { goal: "less_saturated_fat", nutrient: "saturated_fat" },
  { goal: "less_sugar", nutrient: "total_sugars" },
];

// An ingredient supplying this much of a dish's nutrient is the obvious place to start.
const MAIN_SUPPLIER_SHARE = 0.2;

export const GOALS: readonly Goal[] = [
  "less_sodium",
  "less_saturated_fat",
  "less_sugar",
  "fewer_calories",
  "more_protein",
  "more_fiber",
  "closest_match",
];

/**
 * The goal a popup opens on. Someone avoiding what an ingredient contains wants a stand-in. Otherwise
 * it starts on what this ingredient most contributes to, and on protein when nothing stands out.
 */
export function defaultGoal(
  ingredient: Pick<Ingredient, "component_id" | "allergens">,
  contributions: ContributionIndex,
  avoid: ReadonlySet<string>,
): Goal {
  if (ingredient.allergens.some((allergen) => avoid.has(allergen.key))) return "closest_match";
  let best: { goal: Goal; share: number } | null = null;
  for (const { goal, nutrient } of LESS_GOALS) {
    const share = contributions.cell(nutrient, ingredient.component_id)?.share ?? 0;
    if (share >= MAIN_SUPPLIER_SHARE && (best === null || share > best.share)) {
      best = { goal, share };
    }
  }
  return best?.goal ?? "more_protein";
}
