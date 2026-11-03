import { describe, expect, it } from "vitest";

import type { ContributionCell } from "../api/client";
import { messageCatalog, t, translateKey } from "../i18n";
import { nutrient } from "../test/fixtures";
import { ContributionIndex, HIGHLIGHT_MIN_SHARE, highlightOf, strengthOf } from "./contributions";
import {
  formatAmount,
  formatDelta,
  formatGrams,
  formatNumber,
  formatPercent,
  formatShare,
  inSentence,
} from "./format";
import { isKeyNutrient, sectionsOf } from "./nutrientSections";

function cell(overrides: Partial<ContributionCell>): ContributionCell {
  return {
    nutrient_key: "sodium",
    component_id: 1,
    status: "known",
    amount: 1,
    share: 0.5,
    estimated: false,
    ...overrides,
  };
}

describe("highlight strength", () => {
  it("starts at the plan's 5% threshold", () => {
    expect(HIGHLIGHT_MIN_SHARE).toBe(0.05);
    expect(strengthOf(0.0499)).toBeNull();
    expect(strengthOf(0.05)).toBe("weak");
  });

  it.each([
    [0.19, "weak"],
    [0.2, "medium"],
    [0.49, "medium"],
    [0.5, "strong"],
    [1, "strong"],
  ])("treats a share of %s as %s", (share, expected) => {
    expect(strengthOf(share)).toBe(expected);
  });

  it("gives no strength to a missing share, which is not the same as a small one", () => {
    expect(strengthOf(null)).toBeNull();
    expect(strengthOf(undefined)).toBeNull();
  });
});

describe("what an ingredient shows for a nutrient", () => {
  it("shows a share", () => {
    expect(highlightOf(cell({ share: 0.91 }))).toEqual({
      kind: "share",
      strength: "strong",
      share: 0.91,
      partial: false,
    });
  });

  it("marks a share that rests on a recipe with gaps", () => {
    expect(highlightOf(cell({ share: 0.3, status: "partial" }))).toMatchObject({ partial: true });
  });

  it("counts a share from an ingredient's own recipe", () => {
    expect(highlightOf(cell({ share: 0.3, status: "calculated" }))).toMatchObject({
      kind: "share",
    });
  });

  it("leaves a small contributor unmarked", () => {
    expect(highlightOf(cell({ share: 0.01 }))).toBeNull();
  });

  it("treats no quantity and no data as their own states, whatever the share says", () => {
    expect(highlightOf(cell({ status: "no_quantity", share: null }))).toEqual({
      kind: "no_quantity",
    });
    expect(highlightOf(cell({ status: "no_data", share: null }))).toEqual({ kind: "no_data" });
  });
});

describe("the contribution index", () => {
  const index = new ContributionIndex([
    cell({ nutrient_key: "sodium", component_id: 1, share: 0.2 }),
    cell({ nutrient_key: "sodium", component_id: 2, share: 0.7 }),
    cell({ nutrient_key: "sodium", component_id: 3, share: 0.01 }),
    cell({ nutrient_key: "sodium", component_id: 4, status: "no_data", share: null }),
    cell({ nutrient_key: "sodium", component_id: 5, status: "no_quantity", share: null }),
    cell({ nutrient_key: "iron", component_id: 1, share: 0.1 }),
    cell({ nutrient_key: "zinc", component_id: 1, share: 0.9 }),
  ]);

  it("finds one cell", () => {
    expect(index.cell("sodium", 2)?.share).toBe(0.7);
    expect(index.cell("sodium", 99)).toBeUndefined();
  });

  it("ranks a nutrient's contributors, leaving out the small and the unknown", () => {
    expect(index.contributorsTo("sodium").map((c) => c.component_id)).toEqual([2, 1]);
  });

  it("lists a nutrient's gaps separately", () => {
    expect(index.gapsIn("sodium").map((c) => c.component_id)).toEqual([4, 5]);
  });

  it("ranks what an ingredient supplies", () => {
    expect(index.suppliedBy(1).map((c) => c.nutrient_key)).toEqual(["zinc", "sodium", "iron"]);
    expect(index.suppliedBy(3)).toEqual([]);
  });

  it("answers for things it has never heard of", () => {
    expect(index.contributorsTo("nothing")).toEqual([]);
    expect(index.suppliedBy(99)).toEqual([]);
  });
});

describe("number formatting", () => {
  it.each([
    [0, "0"],
    [0.004, "<0.01"],
    [0.123, "0.12"],
    [1.5, "1.5"],
    [12.34, "12.3"],
    [704.7, "705"],
    [38758, "38,758"],
  ])("formats %s as %s", (value, expected) => {
    expect(formatNumber(value)).toBe(expected);
  });

  it("keeps a real zero as zero, never as a small number", () => {
    expect(formatAmount(0, "mg")).toBe("0 mg");
    expect(formatPercent(0)).toBe("0%");
  });

  it("prints the unit", () => {
    expect(formatAmount(2.46, "g")).toBe("2.46 g");
  });

  it("formats grams for ingredients", () => {
    expect(formatGrams(226.8)).toBe("227");
    expect(formatGrams(18)).toBe("18");
    expect(formatGrams(1.5)).toBe("1.5");
  });

  it.each([
    [0.4, "<1%"],
    [30.64, "31%"],
    [20, "20%"],
    [167, "167%"],
    [1234, "1,234%"],
    // Rounding must not put a value that was not flagged on the line that flags it.
    [19.6, "19.6%"],
    [19.96, "19.9%"],
    [19.4, "19%"],
  ])("formats a percent of %s as %s", (value, expected) => {
    expect(formatPercent(value)).toBe(expected);
  });

  it("formats shares", () => {
    expect(formatShare(0.909)).toBe("91%");
    expect(formatShare(0.004)).toBe("<1%");
    expect(formatShare(0)).toBe("0%");
  });

  it("signs a change with a true minus", () => {
    expect(formatDelta(-640, "mg")).toBe("−640 mg");
    expect(formatDelta(1.5, "mg")).toBe("+1.5 mg");
    expect(formatDelta(0, "mg")).toBe("0 mg");
  });

  it("lowers a nutrient's first letter for use in a sentence", () => {
    expect(inSentence("Sodium")).toBe("sodium");
    expect(inSentence("Vitamin C")).toBe("vitamin C");
    expect(inSentence("")).toBe("");
  });
});

describe("nutrient sections", () => {
  it("groups as in the sketch, with sodium beside sugar under Dietary", () => {
    const sections = sectionsOf([
      nutrient("vitamin_c", "Vitamin C", { category: "vitamin" }),
      nutrient("sodium", "Sodium", { category: "mineral" }),
      nutrient("iron", "Iron", { category: "mineral" }),
      nutrient("total_sugars", "Total sugars", { category: "macronutrient" }),
      nutrient("water", "Water", { category: "other" }),
      nutrient("mystery", "Mystery", { category: "macronutrient" }),
    ]);
    expect(sections.map((s) => [s.id, s.nutrients.map((n) => n.key)])).toEqual([
      ["dietary", ["sodium", "total_sugars"]],
      ["vitamin", ["vitamin_c"]],
      ["mineral", ["iron"]],
      ["other", ["water", "mystery"]],
    ]);
  });

  it("leads Dietary with the three the sketch names, whatever order they arrive in", () => {
    const sections = sectionsOf([
      nutrient("total_fat", "Total fat"),
      nutrient("energy", "Energy"),
      nutrient("protein", "Protein"),
      nutrient("saturated_fat", "Saturated fat"),
      nutrient("total_sugars", "Total sugars"),
      nutrient("sodium", "Sodium"),
    ]);
    expect(sections[0]?.nutrients.map((n) => n.key)).toEqual([
      "sodium",
      "total_sugars",
      "saturated_fat",
      "protein",
      "energy",
      "total_fat",
    ]);
  });

  it("puts key nutrients first in the other sections, keeping the catalog's order", () => {
    const sections = sectionsOf([
      nutrient("vitamin_a", "Vitamin A", { category: "vitamin" }),
      nutrient("vitamin_d", "Vitamin D", { category: "vitamin", direction: "encourage" }),
      nutrient("vitamin_c", "Vitamin C", { category: "vitamin" }),
    ]);
    expect(sections[0]?.nutrients.map((n) => n.key)).toEqual([
      "vitamin_d",
      "vitamin_a",
      "vitamin_c",
    ]);
  });

  it("takes importance from the FDA's guide, and adds what the owner chose", () => {
    expect(isKeyNutrient({ key: "sodium", direction: "limit" })).toBe(true);
    expect(isKeyNutrient({ key: "calcium", direction: "encourage" })).toBe(true);
    expect(isKeyNutrient({ key: "total_sugars", direction: "neutral" })).toBe(true);
    expect(isKeyNutrient({ key: "protein", direction: "neutral" })).toBe(true);
    expect(isKeyNutrient({ key: "energy", direction: "neutral" })).toBe(true);
    expect(isKeyNutrient({ key: "total_fat", direction: "neutral" })).toBe(false);
  });

  it("leaves out empty sections", () => {
    expect(sectionsOf([])).toEqual([]);
  });
});

describe("translated text", () => {
  it("fills in parameters", () => {
    expect(t("nutrients.percentDv", { percent: "31%" })).toBe("31% DV");
  });

  it("leaves a missing parameter visible rather than printing undefined", () => {
    expect(t("nutrients.percentDv")).toBe("{percent} DV");
  });

  it("translates keys from the API, and shows an unknown key rather than nothing", () => {
    expect(translateKey("group.fruits")).toBe("Fruits");
    expect(translateKey("no.such.key")).toBe("no.such.key");
  });

  it("has the labels every API value can need", () => {
    for (const level of ["whole", "minimally_processed", "processed", "unknown"]) {
      expect(messageCatalog[`level.${level}`]).toBeTruthy();
    }
    for (const mark of ["exclamation", "green", "question"]) {
      expect(messageCatalog[`mark.${mark}`]).toBeTruthy();
    }
  });

  // The plan: fixed templates, educational framing, no diagnosis, and wording tests.
  const FORBIDDEN = [
    /\bdeficien/i,
    /\bdiagnos/i,
    /\byou (should|must|need)\b/i,
    /\bshould\b/i,
    /\bunhealthy\b/i,
    /\bhealthy\b/i,
    /\bdangerous\b/i,
    /\bsafe\b/i,
    /\bno concern\b/i,
    /\btoo much\b/i,
    /\bcures?\b/i,
    /\btreats? (a|an|your)\b/i,
    /\bgood for\b/i,
    /\bbad for\b/i,
    /\byou (ate|eat|consumed|got)\b/i,
  ];

  it("gives no medical advice and asserts nothing about the reader", () => {
    for (const [key, text] of Object.entries(messageCatalog)) {
      // The disclaimer is the one place allowed to name what the product does not do.
      if (key === "footer.disclaimer") continue;
      for (const pattern of FORBIDDEN) {
        expect(`${key}: ${text}`).not.toMatch(pattern);
      }
    }
  });

  it("uses every message in the catalog, so none is left behind", () => {
    const sources = import.meta.glob("../**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const code = Object.entries(sources)
      .filter(([path]) => !path.includes(".test.") && !path.includes("/test/"))
      .map(([, text]) => text)
      .join("\n");
    // These are built at runtime from a value the API or the page supplies.
    const dynamic = [
      "group.",
      "level.",
      "mark.",
      "filter.",
      "dataset.",
      "conclusion.",
      "related.",
      "population.",
    ];
    const unused = Object.keys(messageCatalog).filter(
      (key) => !code.includes(key) && !dynamic.some((prefix) => key.startsWith(prefix)),
    );
    expect(unused).toEqual([]);
  });

  it("says the disclaimer", () => {
    expect(t("footer.disclaimer")).toMatch(/does not diagnose/);
  });

  it("never calls a question mark or an unknown value clear or fine", () => {
    for (const key of Object.keys(messageCatalog).filter(
      (candidate) =>
        candidate.startsWith("conclusion.could_not_evaluate") || candidate === "mark.question",
    )) {
      expect(messageCatalog[key]).not.toMatch(/\b(fine|clear|ok|okay|not flagged|not high)\b/i);
    }
  });
});
