/** What a nutrient's bar and percent compare with, once an age and sex group is chosen. */

import type { Nutrient, ReferencePopulation, ReferenceValue } from "../api/client";

export const GENERAL_POPULATION: ReferencePopulation = "general_label";

/** The groups in the National Academies' tables, in the order the menu shows them. */
export const POPULATION_GROUPS: readonly {
  label: "population.group.female" | "population.group.male" | "population.group.children";
  populations: readonly ReferencePopulation[];
}[] = [
  {
    label: "population.group.female",
    populations: [
      "female_9_13",
      "female_14_18",
      "female_19_30",
      "female_31_50",
      "female_51_70",
      "female_71_plus",
    ],
  },
  {
    label: "population.group.male",
    populations: [
      "male_9_13",
      "male_14_18",
      "male_19_30",
      "male_31_50",
      "male_51_70",
      "male_71_plus",
    ],
  },
  { label: "population.group.children", populations: ["child_1_3", "child_4_8"] },
];

const KNOWN = new Set<string>([
  GENERAL_POPULATION,
  ...POPULATION_GROUPS.flatMap((group) => group.populations),
]);

export function parsePopulation(value: string | null): ReferencePopulation {
  return value !== null && KNOWN.has(value) ? (value as ReferencePopulation) : GENERAL_POPULATION;
}

export interface Comparison {
  reference: ReferenceValue | null;
  /** What share of the daily amount this serving holds. Null when either side is unknown. */
  percent: number | null;
  /** The FDA's 20% line only means something against the FDA's own number. */
  showHighLine: boolean;
}

export function compareWithReference(
  nutrient: Pick<Nutrient, "daily_value">,
  amountPerServing: number | null | undefined,
  reference: ReferenceValue | undefined,
): Comparison {
  const amount = amountPerServing ?? null;
  if (!reference) {
    return { reference: null, percent: null, showHighLine: false };
  }
  return {
    reference,
    percent: amount === null ? null : (amount / reference.amount) * 100,
    showHighLine: nutrient.daily_value !== null && reference.amount === nutrient.daily_value,
  };
}
