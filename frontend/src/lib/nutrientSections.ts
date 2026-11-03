/** Groups the nutrient panel as in the owner's sketch, with a "Dietary" section. */

import type { Nutrient } from "../api/client";
import type { MessageKey } from "../i18n";

// Sodium is a mineral, but the sketch shows it beside sugar and saturated fat.
const DIETARY_KEYS = new Set([
  "energy",
  "protein",
  "total_fat",
  "saturated_fat",
  "trans_fat",
  "cholesterol",
  "carbohydrate",
  "fiber",
  "total_sugars",
  "added_sugars",
  "sodium",
]);

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
    const id = DIETARY_KEYS.has(nutrient.key)
      ? "dietary"
      : byId.has(nutrient.category)
        ? nutrient.category
        : "other";
    byId.get(id)?.nutrients.push(nutrient);
  }
  return sections.filter((section) => section.nutrients.length > 0);
}
