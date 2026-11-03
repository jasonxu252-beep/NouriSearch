/**
 * The real page against the real API, with the complete USDA data loaded. Figures are worked out
 * from USDA's published values for bibimbap: 435 mg of sodium per 100 g, 162 g per cup.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

async function openFood(page: Page, name: string) {
  const response = await page.request.get(`/v1/foods/search?q=${encodeURIComponent(name)}`);
  const body = (await response.json()) as { results: { id: number; name: string }[] };
  const food = body.results.find((result) => result.name === name);
  expect(food, `${name} should be in the data`).toBeTruthy();
  await page.goto(`/foods/${food?.id}`);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

function nutrient(page: Page, key: string): Locator {
  return page.locator(`[data-nutrient="${key}"]`);
}

function ingredient(page: Page, name: string): Locator {
  return page.locator(`[data-ingredient="${name}"]`);
}

function mark(row: Locator, kind: string): Locator {
  return row.locator(`[data-mark="${kind}"]`);
}

test.describe("finding a food", () => {
  test("search leads to the food page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Search for a food" }).fill("bibimbap");
    await page.keyboard.press("Enter");
    await page.getByRole("link", { name: "Bibimbap, Korean" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Bibimbap, Korean" })).toBeVisible();
    await expect(page).toHaveTitle("Bibimbap, Korean | NouriSearch");
  });

  test("suggestions appear while typing and open with the keyboard", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Search for a food" }).pressSequentially("bibim");
    await expect(page.getByRole("option", { name: /Bibimbap, Korean/ })).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Bibimbap, Korean" })).toBeVisible();
  });

  test("a filter excludes everything else", async ({ page }) => {
    await page.goto("/?q=apple");
    await expect(page.getByRole("link", { name: "Apple juice, 100%" }).first()).toBeVisible();
    await page.getByText("Whole foods", { exact: true }).click();
    await expect(page.getByRole("link", { name: "Apple, raw" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /juice/i })).toHaveCount(0);
    expect(page.url()).toContain("type=whole_foods");
  });
});

test.describe("the food page, against the owner's sketch", () => {
  test("has every panel, in the planned arrangement", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");

    const overview = await page.locator(".carousel").boundingBox();
    const description = await page.locator(".panel--description").boundingBox();
    const related = await page.locator(".panel--related").boundingBox();
    const ingredients = await page.locator(".panel--ingredients").boundingBox();
    const nutrients = await page.locator(".panel--nutrients").boundingBox();

    // Image, description, and Similar stack in the left column, as the plan moved them.
    expect(description?.y).toBeGreaterThan(overview?.y ?? 0);
    expect(related?.y).toBeGreaterThan(description?.y ?? 0);
    expect(Math.abs((related?.x ?? 0) - (overview?.x ?? 1))).toBeLessThan(2);

    // Ingredients and Nutrients sit side by side, with more width than the left column.
    expect(ingredients?.x).toBeGreaterThan((overview?.x ?? 0) + (overview?.width ?? 0));
    expect(nutrients?.x).toBeGreaterThan((ingredients?.x ?? 0) + (ingredients?.width ?? 0));
    expect(Math.abs((ingredients?.y ?? 0) - (nutrients?.y ?? 1))).toBeLessThan(2);
    expect(ingredients?.width).toBeGreaterThan(overview?.width ?? 0);

    // The header matches the sketch, under its new name.
    await expect(page.getByText("NouriSearch", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Search", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Profile" })).toBeVisible();
    await expect(page.getByLabel("Cuisine")).toHaveValue("All cuisines");
    await expect(page.getByRole("button", { name: "Translate" })).toHaveCount(2);
    await expect(page.getByRole("tab", { name: "Explore" })).toBeVisible();
  });

  test("labels USDA's recipe and lists its ingredients", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await expect(page.getByText("USDA survey recipe.")).toBeVisible();
    await expect(page.getByText(/not an authentic recipe/)).toBeVisible();
    await expect(page.locator("[data-ingredient]")).toHaveCount(11);
    await expect(ingredient(page, "Salt, table")).toContainText("18 g");
  });

  test("states the serving above the panel, and the serving changes the mark", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const sodium = nutrient(page, "sodium");
    const serving = page.getByLabel("Per serving");

    await expect(serving).toHaveValue("portion-0");
    await expect(page.locator(".serving__select option:checked")).toHaveText("1 cup (162 g)");
    await expect(sodium).toContainText("705 mg");
    await expect(sodium).toContainText("31% DV");
    await expect(mark(sodium, "exclamation")).toContainText("High");

    await serving.selectOption({ label: "100 g" });
    await expect(sodium).toContainText("435 mg");
    await expect(sodium).toContainText("19% DV");
    await expect(mark(sodium, "green")).toBeVisible();
    await expect(mark(sodium, "exclamation")).toHaveCount(0);
  });

  test("sugar follows the owner's decision", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const total = nutrient(page, "total_sugars");
    await expect(total).toContainText(" g");
    await expect(total).toContainText("No Daily Value");
    await expect(total.locator(".meter")).toHaveCount(0);

    const added = nutrient(page, "added_sugars");
    await expect(added).toContainText("Unknown");
    await expect(mark(added, "question")).toBeVisible();
    await added.getByRole("button").first().click();
    await expect(added).toContainText("The Daily Value is 50 g");
  });
});

test.describe("two-way highlighting", () => {
  test("a nutrient highlights its contributors", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().click();

    const salt = ingredient(page, "Salt, table");
    await expect(salt).toHaveAttribute("data-highlight", "strong");
    await expect(salt).toContainText("91% of known sodium");
    await expect(salt).toBeInViewport();
    await expect(nutrient(page, "sodium")).toContainText("The FDA treats 20% or more as high");
    await expect(nutrient(page, "sodium")).toContainText("Salt, table: 91%");
  });

  test("an ingredient highlights the nutrients it supplies", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByRole("button", { name: "Salt, table" }).click();
    await expect(nutrient(page, "sodium")).toHaveAttribute("data-highlight", "strong");
    await expect(ingredient(page, "Salt, table")).toContainText("Replacements");
  });

  test("works with the keyboard alone", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().focus();
    await page.keyboard.press("Enter");
    await expect(ingredient(page, "Salt, table")).toHaveAttribute("data-highlight", "strong");
    await page.keyboard.press("Escape");
    await expect(ingredient(page, "Salt, table")).not.toHaveAttribute("data-highlight");

    const check = page.getByRole("checkbox", { name: /Salt, table/ });
    await check.focus();
    await page.keyboard.press("Space");
    await expect(check).not.toBeChecked();
    await expect(page.getByText(/1 excluded/)).toBeVisible();
  });

  test("a keyboard user can reach everything in a sensible order", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByRole("combobox", { name: "Search for a food" }).focus();
    const visited: string[] = [];
    for (let step = 0; step < 60; step += 1) {
      await page.keyboard.press("Tab");
      const label = await page.evaluate(() => {
        const element = document.activeElement;
        return element?.getAttribute("aria-label") ?? element?.textContent?.trim() ?? "";
      });
      visited.push(label);
    }
    const firstIngredient = visited.findIndex((label) => label.includes("Include Rice"));
    const sodium = visited.findIndex((label) => label.startsWith("Sodium"));
    expect(firstIngredient).toBeGreaterThan(-1);
    expect(sodium).toBeGreaterThan(firstIngredient);
  });
});

test.describe("excluding an ingredient", () => {
  test("recalculates the dish, and Reset puts it back", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const sodium = nutrient(page, "sodium");
    await expect(mark(sodium, "exclamation")).toBeVisible();

    const check = page.getByRole("checkbox", { name: /Salt, table/ });
    await check.uncheck();

    await expect(page.getByText(/1 excluded/)).toBeVisible();
    // 39.89 mg per 100 g across a 162 g cup, from the arithmetic in the backend's tests.
    await expect(sodium).toContainText("64.6 mg");
    await expect(sodium).toContainText("from the original");
    await expect(mark(sodium, "green")).toBeVisible();
    await expect(ingredient(page, "Salt, table")).toContainText("Excluded");

    await page.getByRole("button", { name: "Reset" }).click();
    await expect(page.getByText("Modified version")).toHaveCount(0);
    await expect(check).toBeChecked();
    await expect(sodium).toContainText("705 mg");
    await expect(mark(sodium, "exclamation")).toBeVisible();
  });

  test("writes nothing, so a reload shows the original", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByRole("checkbox", { name: /Salt, table/ }).uncheck();
    await expect(page.getByText(/1 excluded/)).toBeVisible();
    await page.reload();
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
    await expect(page.getByRole("checkbox", { name: /Salt, table/ })).toBeChecked();
  });
});

test.describe("missing data", () => {
  test("a food with no USDA values shows only question marks, and never zero", async ({ page }) => {
    await openFood(page, "Milk, human");
    const rows = page.locator("[data-nutrient]");
    await expect(rows).toHaveCount(41);
    await expect(page.locator('[data-nutrient] [data-mark="question"]')).toHaveCount(41);
    await expect(page.locator('[data-nutrient] [data-mark="green"]')).toHaveCount(0);
    await expect(page.locator('[data-nutrient] [data-mark="exclamation"]')).toHaveCount(0);
    await expect(page.locator("[data-nutrient] .meter__fill")).toHaveCount(0);
    for (const text of await rows.locator(".nutrient__value").allInnerTexts()) {
      expect(text).toMatch(/^Unknown/);
      expect(text).not.toMatch(/\d/);
    }
  });

  test("a food with no breakdown says so and keeps its values", async ({ page }) => {
    await openFood(page, "Kung pao chicken");
    await expect(page.getByText(/USDA lists no ingredient breakdown/)).toBeVisible();
    await expect(nutrient(page, "sodium")).not.toContainText("Unknown");
  });

  test("USDA's stated zero appears as zero, with its provenance", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const vitaminD = nutrient(page, "vitamin_d");
    await expect(vitaminD).toContainText("0 µg");
    await vitaminD.getByRole("button").first().click();
    await expect(vitaminD).toContainText("USDA reports zero here");
  });

  test("a value rebuilt from incomplete data says at least, and names the gaps", async ({
    page,
  }) => {
    await openFood(page, "Bibimbap, Korean");
    const manganese = nutrient(page, "manganese");
    await expect(manganese).toContainText("at least");
    await expect(mark(manganese, "question")).toBeVisible();
    await manganese.getByRole("button").first().click();
    await expect(manganese).toContainText("No data for");
  });
});

test.describe("moving around", () => {
  test("a similar food opens fresh, with focus on the new page", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().click();
    const card = page.locator(".related-card__link").first();
    const name = (await card.locator(".related-card__name").innerText()).trim();
    await card.click();

    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.locator("[data-selected]")).toHaveCount(0);
    await expect(page.locator("main")).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });

  test("the browser's back button returns to the results", async ({ page }) => {
    await page.goto("/?q=bibimbap");
    await page.getByRole("link", { name: "Bibimbap, Korean" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Bibimbap, Korean" })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("heading", { level: 1, name: /Results for/ })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Search for a food" })).toHaveValue("bibimbap");
  });

  test("a food that does not exist says so", async ({ page }) => {
    await page.goto("/foods/99999999");
    await expect(page.getByRole("alert")).toContainText("We could not find that food.");
  });
});

test.describe("accessibility", () => {
  async function expectNoViolations(page: Page) {
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.map((violation) => ({
        id: violation.id,
        nodes: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
      })),
    ).toEqual([]);
  }

  test("the food page has no violations", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await expect(page.locator(".related-card").first()).toBeVisible();
    await expectNoViolations(page);
  });

  test("the food page has none with a nutrient open", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().click();
    await expect(nutrient(page, "sodium")).toContainText("Top contributing ingredients");
    await expectNoViolations(page);
  });

  test("the food page has none with an ingredient open and another excluded", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByRole("checkbox", { name: /Salt, table/ }).uncheck();
    await expect(page.getByText(/1 excluded/)).toBeVisible();
    await page.getByRole("button", { name: "Oil, sesame, salad or cooking" }).click();
    await expect(ingredient(page, "Oil, sesame, salad or cooking")).toContainText("Replacements");
    await expectNoViolations(page);
  });

  test("the search page has none", async ({ page }) => {
    await page.goto("/");
    await expectNoViolations(page);
    await page.goto("/?q=broccoli");
    await expect(page.getByRole("heading", { level: 1, name: /Results for/ })).toBeVisible();
    await expectNoViolations(page);
  });

  test("dark mode has none", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await openFood(page, "Bibimbap, Korean");
    await expectNoViolations(page);
  });
});

test.describe("small screens", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("nothing overflows sideways, and the panels stack with related foods last", async ({
    page,
  }) => {
    await openFood(page, "Bibimbap, Korean");
    await expect(page.locator(".related-card").first()).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    const y = async (selector: string) => (await page.locator(selector).boundingBox())?.y ?? 0;
    expect(await y(".panel--ingredients")).toBeLessThan(await y(".panel--nutrients"));
    expect(await y(".panel--nutrients")).toBeLessThan(await y(".panel--related"));
  });

  test("highlighting still works, without trapping the scroll", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().click();
    await expect(ingredient(page, "Salt, table")).toHaveAttribute("data-highlight", "strong");
    await expect(nutrient(page, "sodium")).toBeInViewport();
  });
});
