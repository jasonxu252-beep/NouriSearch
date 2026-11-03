/**
 * The two-way highlighting logic. A nutrient highlights the ingredients supplying it, and an
 * ingredient highlights the nutrients it supplies, using the matrix the API sends with the page.
 */

import type { ContributionCell } from "../api/client";

// The plan's starting threshold, to be tuned during review.
export const HIGHLIGHT_MIN_SHARE = 0.05;

export type Strength = "strong" | "medium" | "weak";

export function strengthOf(share: number | null | undefined): Strength | null {
  if (share === null || share === undefined || share < HIGHLIGHT_MIN_SHARE) return null;
  if (share >= 0.5) return "strong";
  if (share >= 0.2) return "medium";
  return "weak";
}

export type IngredientHighlight =
  | { kind: "share"; strength: Strength; share: number; partial: boolean }
  | { kind: "no_quantity" }
  | { kind: "no_data" };

const COUNTED = new Set<ContributionCell["status"]>(["known", "calculated", "partial"]);

/** Null means a small contributor, which stays unmarked so the large ones stand out. */
export function highlightOf(cell: ContributionCell): IngredientHighlight | null {
  if (cell.status === "no_quantity") return { kind: "no_quantity" };
  if (cell.status === "no_data") return { kind: "no_data" };
  const strength = strengthOf(cell.share);
  if (strength === null || cell.share === null) return null;
  return { kind: "share", strength, share: cell.share, partial: cell.status === "partial" };
}

export class ContributionIndex {
  private readonly cells = new Map<string, ContributionCell>();
  private readonly byNutrient = new Map<string, ContributionCell[]>();
  private readonly byComponent = new Map<number, ContributionCell[]>();

  constructor(contributions: readonly ContributionCell[]) {
    for (const cell of contributions) {
      this.cells.set(`${cell.nutrient_key}:${cell.component_id}`, cell);
      this.push(this.byNutrient, cell.nutrient_key, cell);
      this.push(this.byComponent, cell.component_id, cell);
    }
  }

  private push<K>(map: Map<K, ContributionCell[]>, key: K, cell: ContributionCell): void {
    const list = map.get(key);
    if (list) list.push(cell);
    else map.set(key, [cell]);
  }

  cell(nutrientKey: string, componentId: number): ContributionCell | undefined {
    return this.cells.get(`${nutrientKey}:${componentId}`);
  }

  /** Ingredients a nutrient would highlight, largest first. */
  contributorsTo(nutrientKey: string): ContributionCell[] {
    return (this.byNutrient.get(nutrientKey) ?? [])
      .filter((cell) => COUNTED.has(cell.status) && strengthOf(cell.share) !== null)
      .sort((a, b) => (b.share ?? 0) - (a.share ?? 0));
  }

  /** Ingredients a nutrient would mark as documented without a quantity, or as having no data. */
  gapsIn(nutrientKey: string): ContributionCell[] {
    return (this.byNutrient.get(nutrientKey) ?? []).filter((cell) => !COUNTED.has(cell.status));
  }

  /** Nutrients an ingredient would highlight, largest share first. */
  suppliedBy(componentId: number): ContributionCell[] {
    return (this.byComponent.get(componentId) ?? [])
      .filter((cell) => COUNTED.has(cell.status) && strengthOf(cell.share) !== null)
      .sort((a, b) => (b.share ?? 0) - (a.share ?? 0));
  }
}
