import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FoodComposition } from "../api/client";
import {
  dish,
  dishWithoutSalt,
  nutrient,
  PASTE,
  RELATED,
  SALT,
  SOY_SAUCE,
  TOFU,
} from "../test/fixtures";
import { jsonResponse, renderApp, stubApi } from "../test/render";

function setup(food: FoodComposition = dish(), simulate: () => unknown = dishWithoutSalt) {
  const api = stubApi({
    "GET /v1/foods/7/composition": () => food,
    "GET /v1/foods/7/related": () => RELATED,
    "POST /v1/foods/7/simulations": () => simulate(),
  });
  renderApp("/foods/7");
  return api;
}

async function loaded() {
  await screen.findByRole("heading", { level: 1, name: "Mapo tofu" });
}

function nutrientRow(key: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(`[data-nutrient="${key}"]`);
  if (!row) throw new Error(`No row for ${key}`);
  return row;
}

function ingredientRow(name: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(`[data-ingredient="${name}"]`);
  if (!row) throw new Error(`No row for ${name}`);
  return row;
}

function nutrientButton(key: string): HTMLElement {
  return within(nutrientRow(key)).getAllByRole("button")[0] as HTMLElement;
}

describe("the page's content", () => {
  it("labels a USDA recipe and does not imply it is authentic", async () => {
    setup();
    await loaded();
    expect(screen.getByText("USDA survey recipe.")).toBeInTheDocument();
    expect(screen.getByText(/It is not an authentic recipe/)).toBeInTheDocument();
  });

  it("says when USDA gives no breakdown", async () => {
    setup(dish({ recipe: null, ingredients: [], contributions: [] }));
    await loaded();
    expect(screen.getByText(/USDA lists no ingredient breakdown/)).toBeInTheDocument();
  });

  it("offers the two clear profile actions from the plan, marked as not available yet", async () => {
    setup();
    await loaded();
    expect(screen.getByRole("button", { name: "I ate this" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add to my foods" })).toBeDisabled();
    expect(screen.getByText(/not available yet/)).toBeInTheDocument();
  });

  it("names every source behind the page", async () => {
    setup();
    await loaded();
    expect(screen.getByText(/U.S. Department of Agriculture/)).toBeInTheDocument();
    expect(screen.getByText(/Version 2024-10-31/)).toBeInTheDocument();
    expect(screen.getByText(/License: CC0-1.0/)).toBeInTheDocument();
  });

  it("keeps the educational notice on the page", async () => {
    setup();
    await loaded();
    expect(screen.getByText(/does not diagnose/)).toBeInTheDocument();
  });

  it("marks an additive and its documented consideration, as in the sketch's Red 40", async () => {
    const base = dish();
    setup(
      dish({
        ingredients: [
          ...base.ingredients,
          {
            component_id: 9,
            food_id: 109,
            name: "Red 40",
            kind: "additive",
            weight_g: 1,
            weight_share: null,
            has_own_recipe: false,
            excluded: false,
            considerations: ["artificial_color_red_40"],
          },
        ],
      }),
    );
    await loaded();
    const row = ingredientRow("Red 40");
    expect(within(row).getByText("Additive")).toBeInTheDocument();
    expect(within(row).getByText("Has a documented consideration")).toBeInTheDocument();
  });
});

describe("nutrient marks", () => {
  it("uses a different shape and label for each state, so color is never alone", async () => {
    setup();
    await loaded();

    const high = within(nutrientRow("sodium"));
    expect(high.getByText("High")).toBeVisible();
    expect(nutrientRow("sodium").querySelector("[data-mark=exclamation] path")).not.toBeNull();

    const green = nutrientRow("iron").querySelector("[data-mark=green]");
    expect(green).toHaveTextContent("Not flagged");
    const unknown = nutrientRow("vitamin_c").querySelector("[data-mark=question]");
    expect(unknown).toHaveTextContent("Unknown");
    expect(green?.innerHTML).not.toEqual(unknown?.innerHTML);
  });

  it("states the serving above the panel and defaults to the household measure", async () => {
    setup();
    await loaded();
    expect(screen.getByLabelText("Per serving")).toHaveDisplayValue("1 cup (200 g)");
  });

  it("changes the mark when the serving changes, without asking the API again", async () => {
    const api = setup();
    await loaded();
    const before = api.requests.length;
    expect(within(nutrientRow("sodium")).getByText("High")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Per serving"), "per-100g");

    expect(nutrientRow("sodium").querySelector("[data-mark=green]")).not.toBeNull();
    expect(nutrientRow("sodium")).toHaveTextContent("395 mg");
    expect(nutrientRow("sodium")).toHaveTextContent("17% DV");
    expect(api.requests.length).toBe(before);
  });

  it("says values are per 100 g when USDA lists no household serving", async () => {
    const base = dish();
    const per100g = base.servings[1];
    setup(
      dish({
        servings: per100g ? [{ ...per100g, is_default: true }] : [],
        evaluations: base.evaluations.filter((result) => result.serving_key === "per-100g"),
      }),
    );
    await loaded();
    expect(screen.getByText(/values are per 100 g/)).toBeInTheDocument();
    expect(screen.getByLabelText("Per serving")).toHaveDisplayValue("100 g");
  });

  it("says the floor crossed the line for a high lower bound", async () => {
    setup();
    await loaded();
    expect(nutrientRow("saturated_fat")).toHaveTextContent("at least 4 g");
    await userEvent.click(nutrientButton("saturated_fat"));
    expect(screen.getByText(/has at least 20% of the Daily Value/)).toBeInTheDocument();
  });

  it("calls a lower bound below the line undecided, not fine", async () => {
    setup();
    await loaded();
    await userEvent.selectOptions(screen.getByLabelText("Per serving"), "per-100g");

    const row = nutrientRow("saturated_fat");
    expect(row.querySelector("[data-mark=question]")).toHaveTextContent("Incomplete");
    await userEvent.click(nutrientButton("saturated_fat"));
    expect(screen.getByText(/it could still reach the 20%/)).toBeInTheDocument();
    expect(within(row).queryByText("This serving was not flagged.")).toBeNull();
  });
});

describe("unknown values", () => {
  it("shows unknown rather than zero, with an empty dashed meter", async () => {
    setup();
    await loaded();
    const row = nutrientRow("vitamin_c");
    // The printed value alone, since the mark's hidden label also says "Unknown".
    expect(row.querySelector(".nutrient__value")?.textContent?.trim()).toBe("Unknown");
    const meter = row.querySelector(".meter");
    expect(meter).toHaveAttribute("data-state", "unknown");
    expect(meter?.querySelector(".meter__fill")).toBeNull();
  });

  it("explains an unknown value and never says it was not flagged", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("vitamin_c"));
    const row = nutrientRow("vitamin_c");
    expect(within(row).getByText(/No source gives a value/)).toBeInTheDocument();
    expect(within(row).queryByText("This serving was not flagged.")).toBeNull();
  });

  it("shows a stated zero as zero and says how USDA knows", async () => {
    setup();
    await loaded();
    const row = nutrientRow("vitamin_d");
    expect(row).toHaveTextContent("0 µg");
    await userEvent.click(nutrientButton("vitamin_d"));
    expect(within(row).getByText(/USDA reports zero here/)).toBeInTheDocument();
  });

  it("separates a zero USDA assumed from one it reported", async () => {
    const base = dish();
    setup(
      dish({
        nutrients: base.nutrients.map((item) =>
          item.key === "vitamin_d" ? { ...item, value_kind: "assumed_zero" as const } : item,
        ),
      }),
    );
    await loaded();
    await userEvent.click(nutrientButton("vitamin_d"));
    expect(
      within(nutrientRow("vitamin_d")).getByText(/USDA assumes zero here/),
    ).toBeInTheDocument();
  });

  it("names the ingredients behind a gap", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("added_sugars"));
    const row = nutrientRow("added_sugars");
    expect(within(row).getByText("No data for")).toBeInTheDocument();
    expect(within(row).getByText("Salt, table")).toBeInTheDocument();
  });
});

describe("sugar", () => {
  it("shows total sugars in grams, with no meter because no Daily Value exists", async () => {
    setup();
    await loaded();
    const row = nutrientRow("total_sugars");
    expect(row).toHaveTextContent("5 g");
    expect(row).toHaveTextContent("No Daily Value");
    expect(row.querySelector(".meter")).toBeNull();
    await userEvent.click(nutrientButton("total_sugars"));
    expect(within(row).getByText(/not for total sugars/)).toBeInTheDocument();
  });

  it("shows added sugars as unknown against the 50 g Daily Value", async () => {
    setup();
    await loaded();
    const row = nutrientRow("added_sugars");
    expect(row).toHaveTextContent("Unknown");
    expect(row.querySelector(".meter")).toHaveAttribute("data-state", "unknown");
    await userEvent.click(nutrientButton("added_sugars"));
    expect(within(row).getByText(/The Daily Value is 50 g/)).toBeInTheDocument();
  });
});

describe("the meter", () => {
  it("draws the percent, with a tick at the FDA's high line", async () => {
    setup();
    await loaded();
    const meter = nutrientRow("sodium").querySelector<HTMLElement>(".meter");
    expect(meter?.querySelector<HTMLElement>(".meter__fill")?.style.width).toBe("34.3%");
    expect(meter?.querySelector<HTMLElement>(".meter__tick")?.style.left).toBe("20%");
    expect(meter).toHaveClass("meter--high");
  });

  it("caps at the end of the track and prints the true percent", async () => {
    setup();
    await loaded();
    const row = nutrientRow("vitamin_k");
    expect(row.querySelector<HTMLElement>(".meter__fill")?.style.width).toBe("100%");
    expect(row.querySelector(".meter__overflow")).not.toBeNull();
    expect(row).toHaveTextContent("167% DV");
  });

  it("draws a lower bound differently from a known value", async () => {
    setup();
    await loaded();
    expect(nutrientRow("manganese").querySelector(".meter")).toHaveAttribute(
      "data-state",
      "lower-bound",
    );
    expect(nutrientRow("iron").querySelector(".meter")).toHaveAttribute("data-state", "value");
  });
});

describe("two-way highlighting", () => {
  it("highlights a nutrient's contributors by strength, and prints the share", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));

    const salt = ingredientRow("Salt, table");
    expect(salt).toHaveAttribute("data-highlight", "strong");
    expect(salt).toHaveTextContent("91% of known sodium");
  });

  it("leaves contributors under 5% unmarked, so the large ones stand out", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    const tofu = ingredientRow("Tofu");
    expect(tofu).not.toHaveAttribute("data-highlight");
    expect(tofu).not.toHaveTextContent("known sodium");
  });

  it("marks an ingredient with no quantity for the dashed outline", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    const soy = ingredientRow("Soy sauce");
    expect(soy).toHaveAttribute("data-highlight", "no_quantity");
    expect(soy).toHaveTextContent("A source of sodium, amount not stated");
  });

  it("marks an ingredient with no data as unknown", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    const paste = ingredientRow("Doubanjiang");
    expect(paste).toHaveAttribute("data-highlight", "no_data");
    expect(paste).toHaveTextContent("No sodium data");
  });

  it("highlights the nutrients an ingredient supplies, and opens its replacement panel", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Tofu" }));

    expect(nutrientRow("iron")).toHaveAttribute("data-highlight", "strong");
    expect(nutrientRow("iron")).toHaveTextContent("80% of known iron");
    expect(nutrientRow("vitamin_k")).toHaveAttribute("data-highlight", "medium");
    // Tofu's 2% of sodium stays under the threshold.
    expect(nutrientRow("sodium")).not.toHaveAttribute("data-highlight");

    const panel = within(ingredientRow("Tofu"));
    expect(panel.getByText("Replacements")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: "Open Tofu" })).toHaveAttribute("href", "/foods/102");
  });

  it("shows top contributors and sources when a nutrient opens", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    const row = within(nutrientRow("sodium"));
    expect(row.getByText(/has 34% of the Daily Value/)).toBeInTheDocument();
    expect(row.getByText("Salt, table: 91%")).toBeInTheDocument();
    expect(row.getByRole("link", { name: /Lows and Highs/ })).toBeInTheDocument();
  });

  it("clears when the same row is clicked again", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    expect(ingredientRow("Salt, table")).toHaveAttribute("data-highlight");
    await userEvent.click(nutrientButton("sodium"));
    expect(ingredientRow("Salt, table")).not.toHaveAttribute("data-highlight");
  });

  it("selects one thing at a time", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    await userEvent.click(screen.getByRole("button", { name: "Tofu" }));
    expect(nutrientRow("sodium")).not.toHaveAttribute("data-selected");
    expect(ingredientRow("Tofu")).toHaveAttribute("data-selected");
    expect(ingredientRow("Salt, table")).not.toHaveAttribute("data-highlight");
  });

  it("works from the keyboard", async () => {
    setup();
    await loaded();
    nutrientButton("sodium").focus();
    await userEvent.keyboard("{Enter}");
    expect(ingredientRow("Salt, table")).toHaveAttribute("data-highlight", "strong");
    expect(nutrientButton("sodium")).toHaveAttribute("aria-expanded", "true");

    await userEvent.keyboard(" ");
    expect(ingredientRow("Salt, table")).not.toHaveAttribute("data-highlight");

    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Escape}");
    expect(ingredientRow("Salt, table")).not.toHaveAttribute("data-highlight");
    expect(nutrientButton("sodium")).toHaveAttribute("aria-expanded", "false");
  });

  it("announces selection to screen readers", async () => {
    setup();
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    expect(document.querySelector("[aria-live=polite]")).toHaveTextContent(
      "Sodium selected. 1 ingredients highlighted.",
    );
  });

  it("gives every ingredient a checkbox and a separate button", async () => {
    setup();
    await loaded();
    for (const name of ["Salt, table", "Tofu", "Doubanjiang", "Soy sauce"]) {
      const row = within(ingredientRow(name));
      expect(row.getByRole("checkbox", { name: `Include ${name} in this dish` })).toBeChecked();
      expect(row.getByRole("button", { name })).toBeInTheDocument();
    }
    expect([SALT, TOFU, PASTE, SOY_SAUCE]).toHaveLength(4);
  });
});

describe("excluding an ingredient", () => {
  it("unchecks at once, then shows the recalculated dish", async () => {
    let answer: (value: FoodComposition) => void = () => undefined;
    const pending = new Promise<FoodComposition>((resolve) => {
      answer = resolve;
    });
    setup(dish(), () => pending);
    await loaded();

    const box = screen.getByRole("checkbox", { name: /Salt, table/ });
    await userEvent.click(box);

    expect(box).not.toBeChecked();
    expect(screen.getByText(/Recalculating/)).toBeInTheDocument();

    answer(dishWithoutSalt());

    expect(await screen.findByText(/1 excluded/)).toBeInTheDocument();
    expect(nutrientRow("sodium")).toHaveTextContent("14 mg");
    expect(nutrientRow("sodium").querySelector("[data-mark=green]")).not.toBeNull();
  });

  it("asks the API for the edit and sends every excluded ingredient", async () => {
    const api = setup();
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    await screen.findByText(/1 excluded/);
    await userEvent.click(screen.getByRole("checkbox", { name: /Tofu/ }));

    await waitFor(() => {
      const posts = api.requests.filter((request) => request.method === "POST");
      expect(posts.at(-1)?.body).toEqual({
        edits: [
          { type: "remove", component_id: SALT },
          { type: "remove", component_id: TOFU },
        ],
      });
    });
  });

  it("shows how far the value moved, and hides changes too small to matter", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    await screen.findByText(/1 excluded/);
    expect(nutrientRow("sodium")).toHaveTextContent("−776 mg from the original");
    expect(nutrientRow("iron")).not.toHaveTextContent("from the original");
  });

  it("marks the ingredient as excluded", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    const row = ingredientRow("Salt, table");
    expect(row).toHaveAttribute("data-excluded");
    expect(row).toHaveTextContent("Excluded");
  });

  it("says the result is approximate when the recipe does not explain the value", async () => {
    const edited = dishWithoutSalt();
    setup(dish(), () => ({
      ...edited,
      nutrients: edited.nutrients.map((item) =>
        item.key === "sodium" ? { ...item, approximate: true } : item,
      ),
    }));
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    await screen.findByText(/1 excluded/);
    expect(nutrientRow("sodium")).toHaveTextContent("about 14 mg");
    await userEvent.click(nutrientButton("sodium"));
    expect(within(nutrientRow("sodium")).getByText(/change is approximate/)).toBeInTheDocument();
  });

  it("resets to the original without another request", async () => {
    const api = setup();
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    await screen.findByText(/1 excluded/);
    const before = api.requests.length;

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(screen.queryByText(/Modified version/)).toBeNull();
    expect(screen.getByRole("checkbox", { name: /Salt, table/ })).toBeChecked();
    expect(nutrientRow("sodium")).toHaveTextContent("790 mg");
    expect(api.requests.length).toBe(before);
  });

  it("returns to the original when the last excluded ingredient comes back", async () => {
    const api = setup();
    await loaded();
    const box = screen.getByRole("checkbox", { name: /Salt, table/ });
    await userEvent.click(box);
    await screen.findByText(/1 excluded/);
    const before = api.requests.length;

    await userEvent.click(box);

    expect(screen.queryByText(/Modified version/)).toBeNull();
    expect(api.requests.length).toBe(before);
  });

  it("goes back to the original and says so when the calculation fails", async () => {
    setup(dish(), () => jsonResponse({ code: "internal_error", message: "No." }, 500));
    await loaded();
    const box = screen.getByRole("checkbox", { name: /Salt, table/ });
    await userEvent.click(box);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be calculated/);
    expect(box).toBeChecked();
    expect(nutrientRow("sodium")).toHaveTextContent("790 mg");
  });

  it("uses only the newest answer when answers arrive out of order", async () => {
    const answers: ((value: FoodComposition) => void)[] = [];
    setup(
      dish(),
      () =>
        new Promise<FoodComposition>((resolve) => {
          answers.push(resolve);
        }),
    );
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Tofu/ }));
    await waitFor(() => expect(answers.length).toBe(2));

    const newest = dishWithoutSalt();
    answers[1]?.({
      ...newest,
      nutrients: newest.nutrients.map((item) =>
        item.key === "iron" ? { ...item, name: "Iron from the newest answer" } : item,
      ),
    });
    await screen.findByText("Iron from the newest answer");
    answers[0]?.(dish());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByText("Iron from the newest answer")).toBeInTheDocument();
  });

  it("drops the selection when the selected ingredient is excluded", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Salt, table" }));
    expect(ingredientRow("Salt, table")).toHaveAttribute("data-selected");
    await userEvent.click(screen.getByRole("checkbox", { name: /Salt, table/ }));
    expect(ingredientRow("Salt, table")).not.toHaveAttribute("data-selected");
  });
});

describe("failing and missing pages", () => {
  it("says a food does not exist", async () => {
    stubApi({});
    renderApp("/foods/404");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not find that food.");
    expect(screen.getByRole("link", { name: "Back to search" })).toHaveAttribute("href", "/");
  });

  it("treats an address that is not a food ID as not found, without asking", async () => {
    const api = stubApi({});
    renderApp("/foods/not-a-number");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not find that food.");
    expect(api.requests).toHaveLength(0);
  });

  it("offers a retry when the API fails, and the retry works", async () => {
    let failing = true;
    stubApi({
      "GET /v1/foods/7/composition": () =>
        failing ? jsonResponse({ code: "internal_error", message: "No." }, 500) : dish(),
      "GET /v1/foods/7/related": () => RELATED,
    });
    renderApp("/foods/7");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not load");

    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await loaded();
  });
});

describe("moving between foods", () => {
  it("starts fresh on each food", async () => {
    const other = dish({
      id: 8,
      name: "Tofu stew",
      nutrients: [nutrient("sodium", "Sodium", { direction: "limit", daily_value: 2300 })],
    });
    stubApi({
      "GET /v1/foods/7/composition": () => dish(),
      "GET /v1/foods/7/related": () => RELATED,
      "GET /v1/foods/8/composition": () => other,
      "GET /v1/foods/8/related": () => ({ similar: [], explore: [] }),
    });
    renderApp("/foods/7");
    await loaded();
    await userEvent.click(nutrientButton("sodium"));
    expect(nutrientRow("sodium")).toHaveAttribute("data-selected");

    await userEvent.click(await screen.findByRole("link", { name: /Tofu stew/ }));

    await screen.findByRole("heading", { level: 1, name: "Tofu stew" });
    expect(nutrientRow("sodium")).not.toHaveAttribute("data-selected");
  });
});
