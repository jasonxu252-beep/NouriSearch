/** Groups the nutrient panel as in the owner's sketch, with a "Dietary" section. */

import type { Nutrient } from "../api/client";
import type { MessageKey } from "../i18n";

// Sodium is a mineral, but the sketch shows it beside sugar and saturated fat, so those three lead.
const DIETARY_ORDER = [
  "sodium",
  "total_sugars",
  "added_sugars",
  "saturated_fat",
  "protein",
  "energy",
  "fiber",
  "total_fat",
  "trans_fat",
  "cholesterol",
  "carbohydrate",
];

/**
 * The nutrients shown with more importance. Importance comes from a source and not our own opinion:
 * the FDA's guide names what to limit and what to encourage, which is each nutrient's direction.
 * The owner adds protein and energy, which people often look for first, and total sugars, because
 * the sketch names sugar and added sugars is usually unknown.
 */
const OWNER_KEY_NUTRIENTS = new Set(["protein", "energy", "total_sugars"]);

export function isKeyNutrient(nutrient: Pick<Nutrient, "key" | "direction">): boolean {
  return nutrient.direction !== "neutral" || OWNER_KEY_NUTRIENTS.has(nutrient.key);
}

export interface NutrientSection {
  id: string;
  title: MessageKey;
  nutrients: Nutrient[];
}

export function sectionsOf(nutrients: readonly Nutrient[]): NutrientSection[] {
  const sections: NutrientSection[] = [
    { id: "dietary", title: "nutrients.section.dietary", nutrients: [] },
    { id: "vitamin", title: "nutrients.section.vitamin", nutrients: [] },
    { id: "mineral", title: "nutrients.section.mineral", nutrients: [] },
    { id: "other", title: "nutrients.section.other", nutrients: [] },
  ];
  const byId = new Map(sections.map((section) => [section.id, section]));
  for (const nutrient of nutrients) {
    const id = DIETARY_ORDER.includes(nutrient.key)
      ? "dietary"
      : byId.has(nutrient.category)
        ? nutrient.category
        : "other";
    byId.get(id)?.nutrients.push(nutrient);
  }
  byId
    .get("dietary")
    ?.nutrients.sort((a, b) => DIETARY_ORDER.indexOf(a.key) - DIETARY_ORDER.indexOf(b.key));
  for (const section of sections) {
    if (section.id === "dietary") continue;
    // Sorting is stable, so nutrients keep the catalog's order within each level of importance.
    section.nutrients.sort((a, b) => Number(isKeyNutrient(b)) - Number(isKeyNutrient(a)));
  }
  return sections.filter((section) => section.nutrients.length > 0);
}
