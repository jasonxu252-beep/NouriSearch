import { describe, expect, it } from "vitest";

import type { ReferenceValue } from "../api/client";
import { messageCatalog } from "../i18n";
import {
  compareWithReference,
  GENERAL_POPULATION,
  parsePopulation,
  POPULATION_GROUPS,
} from "./references";

function reference(overrides: Partial<ReferenceValue> = {}): ReferenceValue {
  return {
    nutrient_key: "protein",
    amount: 46,
    unit: "g",
    kind: "rda",
    source_key: "nasem-dri-summary",
    is_general: false,
    ...overrides,
  };
}

describe("comparing with a daily amount", () => {
  it("works out the share of the amount that applies", () => {
    const result = compareWithReference({ daily_value: 50 }, 23, reference());
    expect(result.percent).toBe(50);
  });

  it("keeps an unknown amount unknown, rather than calling it zero", () => {
    expect(compareWithReference({ daily_value: 50 }, null, reference()).percent).toBeNull();
    expect(compareWithReference({ daily_value: 50 }, undefined, reference()).percent).toBeNull();
  });

  it("keeps a stated zero as zero", () => {
    expect(compareWithReference({ daily_value: 50 }, 0, reference()).percent).toBe(0);
  });

  it("has nothing to compare with when no reference exists", () => {
    expect(compareWithReference({ daily_value: null }, 5, undefined)).toEqual({
      reference: null,
      percent: null,
      showHighLine: false,
    });
  });

  it("shows the FDA's high line only against the FDA's own number", () => {
    const fda = reference({ amount: 2300, kind: "cdrr" });
    expect(compareWithReference({ daily_value: 2300 }, 100, fda).showHighLine).toBe(true);
    const child = reference({ amount: 1500, kind: "cdrr" });
    expect(compareWithReference({ daily_value: 2300 }, 100, child).showHighLine).toBe(false);
    expect(compareWithReference({ daily_value: 50 }, 10, reference()).showHighLine).toBe(false);
  });

  it("draws no high line on the calorie guide, which has no Daily Value", () => {
    const guide = reference({ amount: 2000, kind: "label_guide" });
    expect(compareWithReference({ daily_value: null }, 100, guide).showHighLine).toBe(false);
  });
});

describe("the groups", () => {
  it("cover both sexes and every age in the published tables, in age order", () => {
    const [female, male, children] = POPULATION_GROUPS;
    expect(female?.populations).toHaveLength(6);
    expect(male?.populations).toHaveLength(6);
    expect(children?.populations).toEqual(["child_1_3", "child_4_8"]);
    expect(female?.populations.at(-1)).toBe("female_71_plus");
  });

  it("each have a label", () => {
    for (const group of POPULATION_GROUPS) {
      expect(messageCatalog[group.label]).toBeTruthy();
      for (const population of group.populations) {
        expect(messageCatalog[`population.${population}`]).toBeTruthy();
      }
    }
  });

  it("read back from storage, and anything unexpected falls back to general", () => {
    expect(parsePopulation("female_51_70")).toBe("female_51_70");
    expect(parsePopulation(null)).toBe(GENERAL_POPULATION);
    expect(parsePopulation("not_a_group")).toBe(GENERAL_POPULATION);
  });
});
