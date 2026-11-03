/* global process */
// Takes the screenshots used to review the layout against the owner's sketches.
//   node e2e/screenshots.mjs <output directory>
// Needs the API running with data loaded, and the app at http://localhost:4173.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const output = process.argv[2] ?? "screenshots";
mkdirSync(output, { recursive: true });
const base = "http://localhost:4173";

const browser = await chromium.launch();

async function foodIdNamed(page, name) {
  const response = await page.request.get(
    `${base}/v1/foods/search?q=${encodeURIComponent(name)}&limit=10`,
  );
  const body = await response.json();
  return body.results.find((food) => food.name === name).id;
}

async function open(viewport, colorScheme = "light") {
  const context = await browser.newContext({ viewport, colorScheme });
  return context.newPage();
}

const desktop = { width: 1440, height: 1000 };

let page = await open(desktop);
const bibimbap = await foodIdNamed(page, "Bibimbap, Korean");
await page.goto(`${base}/foods/${bibimbap}`);
await page.getByRole("heading", { name: "Bibimbap, Korean" }).waitFor();
await page.getByText("Shares", { exact: false }).first().waitFor();
await page.screenshot({ path: join(output, "food-desktop.png") });

await page.getByRole("button", { name: /Sodium/ }).click();
await page.screenshot({ path: join(output, "food-nutrient-selected.png") });

await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Salt, table", exact: true }).click();
await page.screenshot({ path: join(output, "food-ingredient-selected.png") });

await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Change Salt, table" }).click();
await page
  .getByRole("dialog")
  .getByRole("button", { name: /Use 50%/ })
  .waitFor();
await page.screenshot({ path: join(output, "food-wrench.png") });
await page.getByRole("button", { name: "Remove from this dish" }).click();
await page.getByText("Modified version").waitFor();
await page.getByText("changed.", { exact: false }).waitFor();
await page.screenshot({ path: join(output, "food-modified.png") });

page = await open(desktop);
const milk = await foodIdNamed(page, "Milk, human");
await page.goto(`${base}/foods/${milk}`);
await page.getByRole("heading", { name: "Milk, human" }).waitFor();
await page.screenshot({ path: join(output, "food-all-unknown.png") });

page = await open(desktop);
await page.goto(`${base}/?q=broccoli`);
await page.getByRole("heading", { name: /Results for/ }).waitFor();
await page.screenshot({ path: join(output, "search.png") });

page = await open(desktop, "dark");
await page.goto(`${base}/foods/${bibimbap}`);
await page.getByRole("heading", { name: "Bibimbap, Korean" }).waitFor();
await page.getByText("Shares", { exact: false }).first().waitFor();
await page.screenshot({ path: join(output, "food-dark.png") });

page = await open({ width: 390, height: 844 });
await page.goto(`${base}/foods/${bibimbap}`);
await page.getByRole("heading", { name: "Bibimbap, Korean" }).waitFor();
await page.screenshot({ path: join(output, "food-phone.png"), fullPage: true });

await browser.close();
