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

async function openWrench(page: Page, name: string): Promise<Locator> {
  await page.getByRole("button", { name: `Change ${name}` }).click();
  const popup = page.getByRole("dialog", { name: `Change ${name}` });
  await expect(popup).toBeVisible();
  return popup;
}

async function removeIngredient(page: Page, name: string) {
  const popup = await openWrench(page, name);
  await popup.getByRole("button", { name: "Remove from this dish" }).click();
}

async function openOptions(page: Page, name: string): Promise<Locator> {
  const popup = await openWrench(page, name);
  await expect(popup.locator(".option").first()).toBeVisible();
  return popup;
}

async function avoid(page: Page, allergen: string) {
  await page.getByText("Avoid list and diet").click();
  await page.getByRole("checkbox", { name: allergen, exact: true }).check();
  await page.getByText("Avoid list and diet").click();
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
    await expect(page.getByLabel("Per serving").locator("option:checked")).toHaveText(
      "1 cup (162 g)",
    );
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
    await page.getByRole("button", { name: "Salt, table", exact: true }).click();
    await expect(nutrient(page, "sodium")).toHaveAttribute("data-highlight", "strong");
    await expect(ingredient(page, "Salt, table")).toContainText("Contributes to");
  });

  test("works with the keyboard alone", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().focus();
    await page.keyboard.press("Enter");
    await expect(ingredient(page, "Salt, table")).toHaveAttribute("data-highlight", "strong");
    await page.keyboard.press("Escape");
    await expect(ingredient(page, "Salt, table")).not.toHaveAttribute("data-highlight");

    await page.getByRole("button", { name: "Change Salt, table" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("combobox", { name: "Goal" })).toBeFocused();
    await expect(page.getByRole("button", { name: /Use 50%/ })).toBeVisible();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(page.getByText(/1 changed/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Change Salt, table" })).toBeFocused();
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
    const firstIngredient = visited.findIndex((label) => label.includes("Change Rice"));
    const sodium = visited.findIndex((label) => label.startsWith("Sodium"));
    expect(firstIngredient).toBeGreaterThan(-1);
    expect(sodium).toBeGreaterThan(firstIngredient);
  });
});

test.describe("the wrench", () => {
  test("shows a small popup with replacements and removal, on screen", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    // Salt is the last row, so this is where a popup is most likely to be cut off.
    const popup = await openWrench(page, "Salt, table");
    await expect(popup).toContainText("Supplies 91% of known sodium.");
    await expect(popup).toContainText("Replacements");
    await expect(popup.getByRole("combobox", { name: "Goal" })).toBeFocused();
    await expect(popup).toBeInViewport({ ratio: 1 });

    const size = await popup.boundingBox();
    // 25rem by 34rem at most, with a long list scrolling inside it.
    expect(size?.width).toBeLessThanOrEqual(400);
    expect(size?.height).toBeLessThanOrEqual(544);

    await page.keyboard.press("Escape");
    await expect(popup).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Change Salt, table" })).toBeFocused();
  });

  test("the popup stays on screen when the page scrolls near the bottom", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 620 });
    await openFood(page, "Bibimbap, Korean");
    const wrench = page.getByRole("button", { name: "Change Salt, table" });
    await wrench.scrollIntoViewIfNeeded();
    await wrench.click();
    await expect(page.getByRole("dialog")).toBeInViewport({ ratio: 1 });
  });

  test("clicking away closes it and changes nothing", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await openWrench(page, "Salt, table");
    await page.getByRole("heading", { level: 1 }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(ingredient(page, "Salt, table")).not.toHaveAttribute("data-excluded");
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
  });

  test("a removed ingredient comes back with one click", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await removeIngredient(page, "Salt, table");
    await expect(page.getByText(/1 changed/)).toBeVisible();
    await page.getByRole("button", { name: "Put back Salt, table" }).click();
    await expect(page.getByText("Modified version")).toHaveCount(0);
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
  });
});

test.describe("key nutrients", () => {
  const color = (locator: Locator) =>
    locator.evaluate((element) => getComputedStyle(element).backgroundColor);
  const GOLD = "rgb(192, 132, 0)";
  const BLUE = "rgb(42, 120, 214)";
  const RED = "rgb(208, 59, 59)";

  test("stand out in gold and in type, and a high serving stays red", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const sodiumBar = nutrient(page, "sodium").locator(".meter__fill");
    const fatBar = nutrient(page, "saturated_fat").locator(".meter__fill");
    const plainBar = nutrient(page, "total_fat").locator(".meter__fill");

    expect(await color(sodiumBar)).toBe(RED);
    expect(await color(fatBar)).toBe(GOLD);
    expect(await color(plainBar)).toBe(BLUE);

    await page.getByLabel("Per serving").selectOption({ label: "100 g" });
    await expect(mark(nutrient(page, "sodium"), "green")).toBeVisible();
    expect(await color(sodiumBar)).toBe(GOLD);

    const weight = (key: string) =>
      nutrient(page, key)
        .locator(".nutrient__name")
        .evaluate((element) => getComputedStyle(element).fontWeight);
    expect(await weight("sodium")).toBe("600");
    expect(await weight("protein")).toBe("600");
    expect(await weight("energy")).toBe("600");
    expect(await weight("total_fat")).toBe("400");

    const height = async (key: string) =>
      (await nutrient(page, key).locator(".meter").boundingBox())?.height ?? 0;
    expect(await height("sodium")).toBeGreaterThan(await height("total_fat"));
  });

  test("lead their sections", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const names = page.locator(".nutrient-section").first().locator("[data-nutrient]");
    expect(
      await names.evaluateAll((rows) => rows.slice(0, 4).map((r) => r.dataset.nutrient)),
    ).toEqual(["sodium", "total_sugars", "added_sugars", "saturated_fat"]);
    const vitamins = page.locator(".nutrient-section").nth(1).locator("[data-nutrient]").first();
    await expect(vitamins).toHaveAttribute("data-nutrient", "vitamin_d");
  });
});

test.describe("comparing with an age and sex group", () => {
  test("protein follows the chosen group, and the choice is remembered", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const protein = nutrient(page, "protein");
    await expect(protein).toContainText("8.91 g");
    await expect(protein).toContainText("18% DV");

    // The National Academies' Recommended Dietary Allowance for women over 70 is 46 g.
    await page.getByLabel("Compare with").selectOption("female_71_plus");
    await expect(protein).toContainText("19% of 46 g");
    await protein.getByRole("button").first().click();
    await expect(protein).toContainText("Recommended Dietary Allowance for Female, over 70");
    await expect(protein).toContainText("reference body weight");

    // For men over 70 it is 56 g, so the same food is a smaller share.
    await page.getByLabel("Compare with").selectOption("male_71_plus");
    await expect(protein).toContainText("16% of 56 g");

    await page.reload();
    await expect(page.getByLabel("Compare with")).toHaveValue("male_71_plus");
    await expect(nutrient(page, "protein")).toContainText("16% of 56 g");
  });

  test("the High mark stays on the FDA's value, even where a child's amount is lower", async ({
    page,
  }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByLabel("Compare with").selectOption("child_4_8");
    const sodium = nutrient(page, "sodium");
    // 705 mg against a child's 1,500 mg, while the mark still uses the FDA's 2,300 mg.
    await expect(sodium).toContainText("47% of 1,500 mg");
    await expect(mark(sodium, "exclamation")).toBeVisible();
    await expect(sodium.locator(".meter__tick")).toHaveCount(0);
  });

  test("energy compares with the FDA's guide and says needs vary", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const energy = nutrient(page, "energy");
    await expect(energy).toContainText("of 2,000 kcal");
    await energy.getByRole("button").first().click();
    await expect(energy).toContainText("general guide");
    await page.getByLabel("Compare with").selectOption("female_51_70");
    await expect(energy).toContainText("of 2,000 kcal");
    await expect(energy).toContainText("No amount exists for Female, 51 to 70");
  });

  test("the choice carries to the next food", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByLabel("Compare with").selectOption("female_51_70");
    await expect(nutrient(page, "protein")).toContainText("of 46 g");
    await openFood(page, "Dal");
    await expect(page.getByLabel("Compare with")).toHaveValue("female_51_70");
    await expect(nutrient(page, "protein")).toContainText("of 46 g");
  });

  test("has no accessibility violations", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await page.getByLabel("Compare with").selectOption("female_71_plus");
    await expect(nutrient(page, "protein")).toContainText("of 46 g");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});

test.describe("removing an ingredient", () => {
  test("recalculates the dish, and Reset puts it back", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const sodium = nutrient(page, "sodium");
    await expect(mark(sodium, "exclamation")).toBeVisible();

    await removeIngredient(page, "Salt, table");

    await expect(page.getByText(/1 changed/)).toBeVisible();
    // 39.89 mg per 100 g across a 162 g cup, from the arithmetic in the backend's tests.
    await expect(sodium).toContainText("64.6 mg");
    await expect(sodium).toContainText("from the original");
    await expect(mark(sodium, "green")).toBeVisible();
    await expect(ingredient(page, "Salt, table")).toContainText("Removed");

    await page.getByRole("button", { name: "Reset" }).click();
    await expect(page.getByText("Modified version")).toHaveCount(0);
    await expect(ingredient(page, "Salt, table")).not.toHaveAttribute("data-excluded");
    await expect(sodium).toContainText("705 mg");
    await expect(mark(sodium, "exclamation")).toBeVisible();
  });

  test("writes nothing, so a reload shows the original", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await removeIngredient(page, "Salt, table");
    await expect(page.getByText(/1 changed/)).toBeVisible();
    await page.reload();
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
    await expect(ingredient(page, "Salt, table")).not.toHaveAttribute("data-excluded");
  });
});

test.describe("swapping an ingredient", () => {
  test.beforeEach(async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
  });

  test("using half the salt reaches the plan's figure and clears the mark", async ({ page }) => {
    await expect(mark(nutrient(page, "sodium"), "exclamation")).toBeVisible();

    const popup = await openOptions(page, "Salt, table");
    await expect(popup.getByRole("combobox", { name: "Goal" })).toHaveValue("less_sodium");
    const half = popup.getByRole("button", { name: /Use 50% of the amount \(9 g\)/ });
    // 435 mg and about 238 mg per 100 g, in a 162 g cup.
    await expect(half).toContainText("Sodium per 1 cup: 705 mg to 386 mg");
    await half.click();

    await expect(popup).toBeHidden();
    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();
    await expect(nutrient(page, "sodium")).toContainText("386 mg");
    await expect(mark(nutrient(page, "sodium"), "green")).toBeVisible();
    await expect(nutrient(page, "sodium")).toContainText("from the original");
    await expect(ingredient(page, "Salt, table")).toContainText("9 g");
    await expect(ingredient(page, "Salt, table")).toContainText("Was 18 g");
  });

  test("a one-to-many swap shows both new rows, and each way back works", async ({ page }) => {
    const popup = await openOptions(page, "Salt, table");
    await popup
      .getByRole("button", { name: /Salt, table \(9 g\) \+ Lemon juice, raw \(9 g\)/ })
      .click();

    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();
    const rows = page.locator('[data-ingredient="Salt, table"]');
    await expect(rows).toHaveCount(2);
    await expect(
      page.locator('[data-ingredient="Salt, table"][data-edit="replaced"]'),
    ).toContainText("Replaced");
    await expect(page.locator('[data-ingredient="Salt, table"][data-edit="added"]')).toContainText(
      "9 g",
    );
    await expect(ingredient(page, "Lemon juice, raw")).toContainText("New");
    await expect(nutrient(page, "sodium")).toContainText("384 mg");
    await expect(mark(nutrient(page, "sodium"), "green")).toBeVisible();

    await page.getByRole("button", { name: "Take out Lemon juice, raw" }).click();

    await expect(page.getByText("Modified version")).toBeHidden();
    await expect(ingredient(page, "Lemon juice, raw")).toHaveCount(0);
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
  });

  test("swaps add up across ingredients, and Reset clears them all", async ({ page }) => {
    let popup = await openOptions(page, "Salt, table");
    await popup.getByRole("button", { name: /Use 50%/ }).click();
    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();

    popup = await openWrench(page, "Rice, white, long-grain, regular, enriched, cooked");
    await popup.getByRole("combobox", { name: "Goal" }).selectOption("more_fiber");
    await popup.getByRole("button", { name: /Rice, brown/ }).click();

    await expect(page.getByText("2 changed", { exact: false })).toBeVisible();
    await expect(
      ingredient(page, "Rice, white, long-grain, regular, enriched, cooked"),
    ).toContainText("Replaced");
    await expect(nutrient(page, "fiber")).toContainText("from the original");
    await expect(nutrient(page, "sodium")).toContainText("from the original");

    await page.getByRole("button", { name: "Reset" }).click();
    await expect(page.getByText("Modified version")).toBeHidden();
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
  });

  test("writes nothing, so a reload shows the original", async ({ page }) => {
    const popup = await openOptions(page, "Salt, table");
    await popup.getByRole("button", { name: /Use 50%/ }).click();
    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();
    await page.reload();
    await expect(nutrient(page, "sodium")).toContainText("705 mg");
    await expect(page.getByText("Modified version")).toBeHidden();
  });

  test("the goal changes what is offered", async ({ page }) => {
    const popup = await openOptions(page, "Salt, table");
    await expect(popup.locator(".option").first()).toContainText("Sodium per 1 cup");
    await popup.getByRole("combobox", { name: "Goal" }).selectOption("more_protein");
    await expect(popup.locator(".option").first()).toContainText("Protein per 1 cup");
  });

  test("each option can explain how it ranked, and shows a gap as no data", async ({ page }) => {
    const popup = await openOptions(page, "Salt, table");
    const first = popup.locator('[data-origin="use_less"]').first();
    await first.getByText("How this ranked").click();
    await expect(first.getByText("Nutrition change")).toBeVisible();
    await expect(first.getByText("No data").first()).toBeVisible();
  });

  test("works with the keyboard alone", async ({ page }) => {
    await page.getByRole("button", { name: "Change Salt, table" }).focus();
    await page.keyboard.press("Enter");
    const popup = page.getByRole("dialog", { name: "Change Salt, table" });
    await expect(popup.getByRole("combobox", { name: "Goal" })).toBeFocused();
    const first = popup.getByRole("button", { name: /Use 50%/ });
    await expect(first).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(first).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Change Salt, table" })).toBeFocused();
  });

  test("the popup's list scrolls inside it, with removal always in reach", async ({ page }) => {
    const popup = await openOptions(page, "Salt, table");
    const box = await popup.boundingBox();
    const viewport = page.viewportSize();
    expect(box && viewport && box.y + box.height <= viewport.height).toBeTruthy();
    const remove = popup.getByRole("button", { name: "Remove from this dish" });
    await expect(remove).toBeInViewport();
    await popup.locator(".menu__scroll").evaluate((list) => list.scrollTo(0, list.scrollHeight));
    await expect(remove).toBeInViewport();
    await expect(popup.getByText(/only reliable source/)).toBeInViewport();
  });

  test("adding a food recalculates the dish and shows what it holds", async ({ page }) => {
    await page.getByRole("button", { name: "Add an ingredient" }).click();
    await expect(page.getByText(/whole recipe weighs 1,?766 g/)).toBeVisible();
    await page.getByRole("searchbox", { name: "Food" }).fill("tofu firm");
    await page.getByRole("button", { name: "Find" }).click();
    await page.getByRole("spinbutton", { name: "Amount in grams" }).fill("200");
    const name = "Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari)";
    await page.getByRole("button", { name: `Add ${name}` }).click();

    await expect(ingredient(page, name)).toContainText("New");
    await expect(ingredient(page, name)).toContainText("200 g");
    await expect(
      page.getByText(/Contains: Sesame, Soybeans|Contains: Soybeans, Sesame/),
    ).toBeVisible();
    await expect(nutrient(page, "protein")).toContainText("from the original");
  });
});

test.describe("what someone avoids", () => {
  test.beforeEach(async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
  });

  test("what a dish contains is visible without opening anything", async ({ page }) => {
    await expect(page.getByText(/Contains: Sesame/)).toBeVisible();
    await expect(page.getByText(/only reliable source/).first()).toBeVisible();
  });

  test("an excluded allergen never appears, and the list says something was hidden", async ({
    page,
  }) => {
    let popup = await openOptions(page, "Salt, table");
    await expect(popup.getByText(/Soy sauce made from soy and wheat/)).toBeVisible();
    await page.keyboard.press("Escape");

    await avoid(page, "Soybeans");

    popup = await openOptions(page, "Salt, table");
    await expect(popup.getByText(/1 hidden by your allergen list/)).toBeVisible();
    await expect(popup.getByText(/Soy sauce/)).toHaveCount(0);
    await expect(popup.getByRole("button", { name: /Use 50%/ })).toBeVisible();
  });

  test("a may-contain finding is excluded too", async ({ page }) => {
    await avoid(page, "Wheat");
    const popup = await openWrench(page, "Rice, white, long-grain, regular, enriched, cooked");
    await popup.getByRole("combobox", { name: "Goal" }).selectOption("more_fiber");
    await expect(popup.getByRole("button", { name: /Rice, brown/ })).toBeVisible();
    await expect(popup.getByRole("button", { name: /Barley/ })).toHaveCount(0);
    await expect(popup.getByRole("button", { name: /Bulgur/ })).toHaveCount(0);
    await expect(popup.getByText(/hidden by your allergen list/)).toBeVisible();
  });

  test("warns in words, marks the row, and offers a stand-in without it", async ({ page }) => {
    await avoid(page, "Sesame");
    await expect(page.getByText(/You avoid Sesame, and this dish has it/)).toBeVisible();
    await expect(page.getByText(/Found in: Oil, sesame, salad or cooking/)).toBeVisible();
    await expect(ingredient(page, "Oil, sesame, salad or cooking")).toContainText("Has Sesame");

    const popup = await openOptions(page, "Oil, sesame, salad or cooking");
    await expect(popup.getByRole("combobox", { name: "Goal" })).toHaveValue("closest_match");
    await expect(popup.getByRole("button", { name: /Oil, canola/ })).toBeVisible();
    await expect(popup.getByRole("button", { name: /Use / })).toHaveCount(0);

    await popup.getByRole("button", { name: /Oil, canola/ }).click();
    await expect(page.getByText(/You avoid Sesame/)).toBeHidden();
    await expect(page.getByText(/Contains: Sesame/)).toBeHidden();
  });

  test("the list and the diet are remembered, and the diet filters options", async ({ page }) => {
    await page.getByText("Avoid list and diet").click();
    await page.getByRole("combobox", { name: "Diet" }).selectOption("vegan");
    await page.reload();
    await page.getByText("Avoid list and diet").click();
    await expect(page.getByRole("combobox", { name: "Diet" })).toHaveValue("vegan");

    const popup = await openWrench(
      page,
      'Beef, round, top round roast, boneless, separable lean and fat, trimmed to 0" fat, all grades, cooked, roasted',
    );
    await popup.getByRole("combobox", { name: "Goal" }).selectOption("less_saturated_fat");
    await expect(popup.getByRole("button", { name: /Tofu, firm/ })).toBeVisible();
    await expect(popup.getByRole("button", { name: /Chicken/ })).toHaveCount(0);
    await expect(popup.getByText(/hidden by your diet choice/)).toBeVisible();
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
    await removeIngredient(page, "Salt, table");
    await expect(page.getByText(/1 changed/)).toBeVisible();
    await page.getByRole("button", { name: "Oil, sesame, salad or cooking", exact: true }).click();
    await expect(ingredient(page, "Oil, sesame, salad or cooking")).toContainText("Contributes to");
    await expectNoViolations(page);
  });

  test("the food page has none with replacements listed and a score open", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const popup = await openOptions(page, "Salt, table");
    await popup.getByText("How this ranked").first().click();
    await expectNoViolations(page);
  });

  test("the food page has none once swapped, with an avoided allergen shown", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const popup = await openOptions(page, "Salt, table");
    await popup.getByRole("button", { name: /Lemon juice/ }).click();
    await expect(page.getByText("1 changed", { exact: false })).toBeVisible();
    await page.getByText("Avoid list and diet").click();
    await page.getByRole("checkbox", { name: "Sesame", exact: true }).check();
    await page.getByRole("button", { name: "Add an ingredient" }).click();
    await expectNoViolations(page);
  });

  test("the food page has none with the wrench popup open", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await openWrench(page, "Salt, table");
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

  test("the replacement list fits on the screen and scrolls inside the popup", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const popup = await openOptions(page, "Salt, table");
    const box = await popup.boundingBox();
    const screen = page.viewportSize();
    expect(box && screen && box.x >= 0 && box.x + box.width <= screen.width).toBeTruthy();
    expect(box && screen && box.y >= 0 && box.y + box.height <= screen.height).toBeTruthy();
    await expect(popup.getByRole("button", { name: "Remove from this dish" })).toBeInViewport();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("the wrench popup fits on the screen", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    const popup = await openWrench(page, "Salt, table");
    await expect(popup).toBeInViewport({ ratio: 1 });
    await popup.getByRole("button", { name: "Remove from this dish" }).click();
    await expect(page.getByText(/1 changed/)).toBeVisible();
  });

  test("highlighting still works, without trapping the scroll", async ({ page }) => {
    await openFood(page, "Bibimbap, Korean");
    await nutrient(page, "sodium").getByRole("button").first().click();
    await expect(ingredient(page, "Salt, table")).toHaveAttribute("data-highlight", "strong");
    await expect(nutrient(page, "sodium")).toBeInViewport();
  });
});
