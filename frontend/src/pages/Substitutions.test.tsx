import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FoodComposition, IngredientEdit, Substitutions } from "../api/client";
import { dish, option, RELATED, SALT, substitutions, TOFU } from "../test/fixtures";
import { jsonResponse, renderApp, stubApi } from "../test/render";

type Handler = () => unknown;

function setup({
  food = dish(),
  ranked = () => substitutions(),
  simulate = () => dish(),
  search = () => ({ query: "", results: [], has_more: false }),
}: {
  food?: FoodComposition;
  ranked?: Handler;
  simulate?: Handler;
  search?: Handler;
} = {}) {
  const api = stubApi({
    "GET /v1/foods/7/composition": () => food,
    "GET /v1/foods/7/related": () => RELATED,
    "POST /v1/foods/7/simulations": () => simulate(),
    "POST /v1/foods/7/substitutions": () => ranked(),
    "GET /v1/foods/search": () => search(),
    "GET /v1/reference-intakes": () => ({ population: "general_label", values: [], sources: [] }),
  });
  renderApp("/foods/7");
  return api;
}

async function openWrench(name = "Salt, table") {
  await screen.findByRole("heading", { level: 1 });
  await userEvent.click(screen.getByRole("button", { name: `Change ${name}` }));
  return screen.findByRole("dialog", { name: `Change ${name}` });
}

function row(name: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-ingredient="${name}"]`);
  if (!found) throw new Error(`No ingredient row for ${name}.`);
  return found;
}

function rankRequests(api: ReturnType<typeof setup>) {
  return api.requests.filter((request) => request.path.endsWith("/substitutions"));
}

function simulationEdits(api: ReturnType<typeof setup>): IngredientEdit[] {
  const requests = api.requests.filter((request) => request.path.endsWith("/simulations"));
  return (requests.at(-1)?.body as { edits: IngredientEdit[] } | undefined)?.edits ?? [];
}

describe("choosing a goal in the wrench popup", () => {
  it("opens on what this ingredient most contributes to, and asks for that", async () => {
    const api = setup();
    await openWrench();
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));
    expect(rankRequests(api)[0]?.body).toMatchObject({
      component_id: SALT,
      goal: "less_sodium",
      avoid_allergens: [],
      diet: "any",
      edits: [],
    });
    expect(screen.getByRole("combobox", { name: "Goal" })).toHaveValue("less_sodium");
  });

  it("opens on protein when the ingredient supplies nothing notable to limit", async () => {
    const api = setup();
    await openWrench("Tofu");
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));
    expect(rankRequests(api)[0]?.body).toMatchObject({ component_id: TOFU, goal: "more_protein" });
  });

  it("asks again when the goal changes, and keeps that goal for the next ingredient", async () => {
    const api = setup();
    const popup = await openWrench();
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));

    await userEvent.selectOptions(
      within(popup).getByRole("combobox", { name: "Goal" }),
      "More fiber",
    );

    await waitFor(() => expect(rankRequests(api)).toHaveLength(2));
    expect(rankRequests(api)[1]?.body).toMatchObject({ goal: "more_fiber" });

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Change Tofu" }));
    await waitFor(() => expect(rankRequests(api)).toHaveLength(3));
    expect(rankRequests(api)[2]?.body).toMatchObject({ component_id: TOFU, goal: "more_fiber" });
  });

  it("offers every goal, including the owner's protein and calories", async () => {
    setup();
    const popup = await openWrench();
    const goals = within(within(popup).getByRole("combobox", { name: "Goal" }))
      .getAllByRole("option")
      .map((item) => item.textContent);
    expect(goals).toEqual([
      "Less sodium",
      "Less saturated fat",
      "Less sugar",
      "Fewer calories",
      "More protein",
      "More fiber",
      "Closest match",
    ]);
  });

  it("opens on the closest match when the person avoids what the ingredient holds", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["soybeans"]');
    const base = dish();
    const api = setup({
      food: dish({
        ingredients: base.ingredients.map((item) =>
          item.component_id === TOFU
            ? {
                ...item,
                allergens: [{ key: "soybeans", relation: "contains", verification: "typical" }],
              }
            : item,
        ),
      }),
    });
    await openWrench("Tofu");
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));
    expect(rankRequests(api)[0]?.body).toMatchObject({
      goal: "closest_match",
      avoid_allergens: ["soybeans"],
    });
  });
});

describe("the ranked options", () => {
  it("shows the name, weight, and change in the dish, and marks an approximate one", async () => {
    setup({
      ranked: () =>
        substitutions({
          options: [
            option(),
            option({
              key: "option-2",
              replacements: [
                { food_id: 502, name: "Soy sauce, low sodium", ratio: 5, weight_g: 5 },
              ],
              goal_effect: {
                nutrient_key: "sodium",
                unit: "mg",
                before_per_100g: 395,
                after_per_100g: 214,
                approximate: true,
              },
            }),
          ],
        }),
    });
    const popup = await openWrench();

    const first = await within(popup).findByRole("button", { name: /Lemon juice \(1 g\)/ });
    // The default serving here is 1 cup of 200 g, matching the panel beside it.
    expect(first).toHaveTextContent("Sodium per 1 cup: 790 mg to 400 mg");
    const second = within(popup).getByRole("button", { name: /Soy sauce, low sodium \(5 g\)/ });
    expect(second).toHaveTextContent("to about 428 mg");
    expect(second).toHaveTextContent("Approximate");
  });

  it("names both parts of a one-to-many replacement", async () => {
    setup({
      ranked: () =>
        substitutions({
          options: [
            option({
              replacements: [
                { food_id: 101, name: "Salt, table", ratio: 0.5, weight_g: 0.5 },
                { food_id: 501, name: "Lemon juice", ratio: 0.5, weight_g: 0.5 },
              ],
            }),
          ],
        }),
    });
    const popup = await openWrench();
    expect(
      await within(popup).findByRole("button", {
        name: /Salt, table \(0\.5 g\) \+ Lemon juice \(0\.5 g\)/,
      }),
    ).toBeInTheDocument();
  });

  it("states using less plainly, with the resulting weight", async () => {
    setup({
      ranked: () =>
        substitutions({
          options: [
            option({
              key: "scale-0.5",
              origin: "use_less",
              scale_factor: 0.5,
              replacements: [],
              edit: { type: "scale", component_id: SALT, factor: 0.5 },
            }),
          ],
        }),
    });
    const popup = await openWrench();
    expect(
      await within(popup).findByRole("button", { name: /Use 50% of the amount \(0\.5 g\)/ }),
    ).toBeInTheDocument();
    expect(within(popup).getByText("The same ingredient, less of it.")).toBeInTheDocument();
  });

  it("gives reasons, including what changes for the worse, and each is in words", async () => {
    setup({
      ranked: () =>
        substitutions({
          options: [
            option({
              note: "Acid brings out flavor.",
              reasons: [
                { code: "mark_cleared", nutrient_key: "sodium" },
                { code: "mark_raised", nutrient_key: "saturated_fat" },
                { code: "side_effect", nutrient_key: "saturated_fat" },
                { code: "flavor_close", nutrient_key: null },
                { code: "texture_different", nutrient_key: null },
              ],
            }),
          ],
        }),
      food: dish(),
    });
    const popup = await openWrench();
    await within(popup).findByRole("button", { name: /Lemon juice/ });
    expect(within(popup).getByText("A swap on our reviewed list.")).toBeInTheDocument();
    expect(within(popup).getByText("Clears the high sodium mark.")).toBeInTheDocument();
    expect(within(popup).getByText(/Close in flavor/)).toBeInTheDocument();
    expect(within(popup).getByText(/Different in texture/)).toBeInTheDocument();
    expect(within(popup).getByText("Acid brings out flavor.")).toBeInTheDocument();
  });

  it("says when nobody has reviewed a pairing", async () => {
    setup({
      ranked: () => substitutions({ options: [option({ origin: "same_role" })] }),
    });
    const popup = await openWrench();
    expect(await within(popup).findByText(/Nobody has reviewed this swap/)).toBeInTheDocument();
  });

  it("exposes every part of the score, and a missing part reads as no data, never zero", async () => {
    setup();
    const popup = await openWrench();
    await within(popup).findByRole("button", { name: /Lemon juice/ });
    const details = within(popup).getByText("How this ranked").closest("details");
    expect(details).not.toBeNull();
    const scores = within(details as HTMLElement);
    expect(scores.getByText("Nutrition change").nextElementSibling).toHaveTextContent("90");
    expect(scores.getByText("Flavor match").nextElementSibling).toHaveTextContent("31");
    expect(scores.getByText("Texture match").nextElementSibling).toHaveTextContent("No data");
    expect(scores.getByText("Fit in a dish").nextElementSibling).toHaveTextContent("75");
    expect(scores.getByText("Overall").nextElementSibling).toHaveTextContent("80");
    expect(scores.getByText("Data behind this").nextElementSibling).toHaveTextContent("100%");
  });

  it("lists what an option contains, by name and relation", async () => {
    setup({
      ranked: () =>
        substitutions({
          options: [
            option({
              allergens: [
                {
                  key: "soybeans",
                  name: "Soybeans",
                  relation: "contains",
                  verification: "typical",
                },
                { key: "wheat", name: "Wheat", relation: "contains", verification: "typical" },
                {
                  key: "sesame",
                  name: "Sesame",
                  relation: "may_contain",
                  verification: "estimated",
                },
              ],
            }),
          ],
        }),
    });
    const popup = await openWrench();
    expect(await within(popup).findByText("Contains: Soybeans, Wheat.")).toBeInTheDocument();
    expect(within(popup).getByText("May contain: Sesame.")).toBeInTheDocument();
  });

  it("says what was hidden and could not be evaluated, without naming hidden foods", async () => {
    setup({
      ranked: () =>
        substitutions({
          hidden_for_allergens: 2,
          hidden_for_diet: 1,
          could_not_evaluate: ["Coconut aminos"],
        }),
    });
    const popup = await openWrench();
    expect(await within(popup).findByText("2 hidden by your allergen list.")).toBeInTheDocument();
    expect(within(popup).getByText("1 hidden by your diet choice.")).toBeInTheDocument();
    expect(within(popup).getByText(/no value to compare for: Coconut aminos/)).toBeInTheDocument();
  });

  it("always reminds the person that only a label can confirm an allergen", async () => {
    setup();
    const popup = await openWrench();
    expect(within(popup).getByText(/only reliable source/)).toBeInTheDocument();
  });

  it.each<[string, Partial<Substitutions>, RegExp]>([
    ["no option", { options: [] }, /Nothing we know of moves sodium/],
    ["no weight", { options: [], unavailable_reason: "no_weight" }, /states no amount/],
    ["no value", { options: [], unavailable_reason: "goal_unknown" }, /gives no sodium value/],
  ])("explains %s rather than showing an empty list", async (_case, overrides, message) => {
    setup({ ranked: () => substitutions(overrides) });
    const popup = await openWrench();
    expect(await within(popup).findByText(message)).toBeInTheDocument();
    expect(within(popup).getByRole("button", { name: "Remove from this dish" })).toBeEnabled();
  });

  it("says when there is no close match", async () => {
    setup({ ranked: () => substitutions({ options: [], goal: "closest_match" }) });
    const popup = await openWrench();
    await userEvent.selectOptions(
      within(popup).getByRole("combobox", { name: "Goal" }),
      "Closest match",
    );
    expect(await within(popup).findByText(/no close replacement/)).toBeInTheDocument();
  });

  it("recovers from a failed request, and removal still works meanwhile", async () => {
    let attempts = 0;
    setup({
      ranked: () => {
        attempts += 1;
        return attempts === 1
          ? jsonResponse({ code: "x", message: "Down." }, 500)
          : substitutions();
      },
    });
    const popup = await openWrench();
    expect(await within(popup).findByRole("alert")).toHaveTextContent(
      "Replacements could not load.",
    );
    expect(within(popup).getByRole("button", { name: "Remove from this dish" })).toBeEnabled();
    await userEvent.click(within(popup).getByRole("button", { name: "Try again" }));
    expect(await within(popup).findByRole("button", { name: /Lemon juice/ })).toBeInTheDocument();
  });
});

describe("the ranked options and the chosen serving", () => {
  it("follow the serving chosen in the nutrient panel", async () => {
    setup();
    await screen.findByRole("heading", { level: 1 });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Per serving" }), "100 g");
    const popup = await openWrench();
    expect(await within(popup).findByRole("button", { name: /Lemon juice/ })).toHaveTextContent(
      "Sodium per 100 g: 395 mg to 200 mg",
    );
  });

  it("keep a chosen goal for later ingredients, except one holding something avoided", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["soybeans"]');
    const base = dish();
    const api = setup({
      food: dish({
        ingredients: base.ingredients.map((item) =>
          item.component_id === TOFU
            ? {
                ...item,
                allergens: [{ key: "soybeans", relation: "contains", verification: "typical" }],
              }
            : item,
        ),
      }),
    });
    let popup = await openWrench();
    await userEvent.selectOptions(
      within(popup).getByRole("combobox", { name: "Goal" }),
      "More fiber",
    );
    await waitFor(() =>
      expect(rankRequests(api).at(-1)?.body).toMatchObject({ goal: "more_fiber" }),
    );
    await userEvent.keyboard("{Escape}");

    popup = await openWrench("Tofu");
    await waitFor(() =>
      expect(rankRequests(api).at(-1)?.body).toMatchObject({
        component_id: TOFU,
        goal: "closest_match",
      }),
    );

    await userEvent.selectOptions(
      within(popup).getByRole("combobox", { name: "Goal" }),
      "More protein",
    );
    await waitFor(() =>
      expect(rankRequests(api).at(-1)?.body).toMatchObject({
        component_id: TOFU,
        goal: "more_protein",
      }),
    );
  });
});

describe("choosing an option", () => {
  it("sends the option's own edit, closes the popup, and returns focus to the wrench", async () => {
    const api = setup();
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));

    await waitFor(() =>
      expect(simulationEdits(api)).toEqual([
        { type: "replace", component_id: SALT, replacements: [{ food_id: 501, ratio: 1 }] },
      ]),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change Salt, table" })).toHaveFocus();
  });

  it("shows the swapped dish: the old row replaced, the new row, and updated values", async () => {
    const base = dish();
    const swapped = dish({
      is_modified: true,
      ingredients: base.ingredients.flatMap((item) =>
        item.component_id === SALT
          ? [
              { ...item, excluded: true, edit: "replaced" as const },
              {
                ...item,
                component_id: -1,
                food_id: 501,
                name: "Lemon juice",
                edit: "added" as const,
                original_weight_g: null,
                replaces_component_id: SALT,
              },
            ]
          : [item],
      ),
    });
    setup({ simulate: () => swapped });
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));

    expect(await screen.findByText(/1 changed/)).toBeInTheDocument();
    expect(row("Salt, table")).toHaveTextContent("Replaced");
    expect(row("Salt, table")).toHaveAttribute("data-excluded");
    expect(row("Lemon juice")).toHaveTextContent("New");
    expect(row("Lemon juice")).toHaveAttribute("data-edit", "added");
    expect(
      within(row("Lemon juice")).queryByRole("button", { name: "Change Lemon juice" }),
    ).not.toBeInTheDocument();
  });

  it("taking out a new ingredient undoes the replacement that brought it", async () => {
    const base = dish();
    const swapped = dish({
      is_modified: true,
      ingredients: [
        ...base.ingredients.map((item) =>
          item.component_id === SALT
            ? { ...item, excluded: true, edit: "replaced" as const }
            : item,
        ),
        {
          ...base.ingredients[0]!,
          component_id: -1,
          food_id: 501,
          name: "Lemon juice",
          edit: "added" as const,
          original_weight_g: null,
          replaces_component_id: SALT,
        },
      ],
    });
    setup({ simulate: () => swapped });
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));
    await screen.findByText(/1 changed/);

    await userEvent.click(screen.getByRole("button", { name: "Take out Lemon juice" }));

    await waitFor(() => expect(screen.queryByText(/1 changed/)).not.toBeInTheDocument());
    expect(row("Salt, table")).not.toHaveAttribute("data-excluded");
  });

  it("a replaced ingredient can go back from its row or from its wrench", async () => {
    const base = dish();
    const swapped = dish({
      is_modified: true,
      ingredients: base.ingredients.map((item) =>
        item.component_id === SALT ? { ...item, excluded: true, edit: "replaced" as const } : item,
      ),
    });
    setup({ simulate: () => swapped });
    let popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));
    await screen.findByText(/1 changed/);

    await userEvent.click(screen.getByRole("button", { name: "Change Salt, table" }));
    popup = await screen.findByRole("dialog");
    expect(
      within(popup).queryByRole("button", { name: "Remove from this dish" }),
    ).not.toBeInTheDocument();
    await userEvent.click(within(popup).getByRole("button", { name: "Put back in this dish" }));

    await waitFor(() => expect(screen.queryByText(/1 changed/)).not.toBeInTheDocument());
  });

  it("shows a scaled ingredient's new and old weight, and it can go back", async () => {
    const base = dish();
    const scaled = dish({
      is_modified: true,
      ingredients: base.ingredients.map((item) =>
        item.component_id === SALT
          ? { ...item, edit: "scaled" as const, weight_g: 0.5, original_weight_g: 1 }
          : item,
      ),
    });
    const api = setup({
      simulate: () => scaled,
      ranked: () =>
        substitutions({
          options: [
            option({
              key: "scale-0.5",
              origin: "use_less",
              scale_factor: 0.5,
              replacements: [],
              edit: { type: "scale", component_id: SALT, factor: 0.5 },
            }),
          ],
        }),
    });
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Use 50%/ }));
    await screen.findByText(/1 changed/);

    expect(row("Salt, table")).toHaveTextContent("0.5 g Was 1 g");
    expect(row("Salt, table")).not.toHaveAttribute("data-excluded");
    expect(simulationEdits(api)).toEqual([{ type: "scale", component_id: SALT, factor: 0.5 }]);

    await userEvent.click(screen.getByRole("button", { name: "Put back Salt, table" }));
    await waitFor(() => expect(screen.queryByText(/1 changed/)).not.toBeInTheDocument());
  });

  it("keeps earlier edits, and sends them when ranking the next ingredient", async () => {
    const api = setup();
    let popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));
    await screen.findByText(/1 changed/);

    popup = await openWrench("Tofu");
    await waitFor(() => expect(rankRequests(api)).toHaveLength(2));
    expect(rankRequests(api)[1]?.body).toMatchObject({
      component_id: TOFU,
      edits: [{ type: "replace", component_id: SALT }],
    });

    await userEvent.click(within(popup).getByRole("button", { name: "Remove from this dish" }));
    await waitFor(() => expect(simulationEdits(api)).toHaveLength(2));
    expect(simulationEdits(api)[0]).toMatchObject({ type: "replace", component_id: SALT });
    expect(simulationEdits(api)[1]).toEqual({ type: "remove", component_id: TOFU });
  });

  it("a second choice for one ingredient replaces the first", async () => {
    const api = setup({
      ranked: () =>
        substitutions({
          options: [
            option(),
            option({
              key: "scale-0.5",
              origin: "use_less",
              scale_factor: 0.5,
              replacements: [],
              edit: { type: "scale", component_id: SALT, factor: 0.5 },
            }),
          ],
        }),
    });
    let popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));
    await screen.findByText(/1 changed/);

    popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Use 50%/ }));

    await waitFor(() =>
      expect(simulationEdits(api)).toEqual([{ type: "scale", component_id: SALT, factor: 0.5 }]),
    );
  });

  it("reset clears every kind of edit", async () => {
    const api = setup();
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));
    await screen.findByText(/1 changed/);
    const before = api.requests.length;

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => expect(screen.queryByText(/changed/)).not.toBeInTheDocument());
    expect(api.requests).toHaveLength(before);
  });

  it("a failed swap returns the dish to how it was, and says so", async () => {
    setup({ simulate: () => jsonResponse({ code: "x", message: "Down." }, 500) });
    const popup = await openWrench();
    await userEvent.click(await within(popup).findByRole("button", { name: /Lemon juice/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be calculated");
    expect(row("Salt, table")).not.toHaveAttribute("data-excluded");
    expect(screen.queryByText(/1 changed/)).not.toBeInTheDocument();
  });
});

describe("the allergen panel", () => {
  async function openPanel() {
    await screen.findByRole("heading", { level: 1 });
    await userEvent.click(screen.getByText(/^Avoid list and diet/));
  }

  it("lists what was found, by relation", async () => {
    setup({
      food: dish({
        allergens: [
          {
            key: "soybeans",
            name: "Soybeans",
            relation: "contains",
            verification: "estimated",
            ingredient_names: ["Tofu"],
          },
          {
            key: "wheat",
            name: "Wheat",
            relation: "may_contain",
            verification: "estimated",
            ingredient_names: [],
          },
        ],
      }),
    });
    // Visible without opening anything, because someone may not know to look.
    await screen.findByRole("heading", { level: 1 });
    const found = screen.getByText(/Contains: Soybeans\./);
    expect(found).toHaveTextContent("May contain: Wheat.");
    expect(found).toHaveTextContent("only reliable source");
    expect(found.closest("details")).toBeNull();
  });

  it("finding nothing is never presented as having none", async () => {
    setup();
    await openPanel();
    expect(screen.getByText(/That does not mean it has none/)).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/allergen[- ]free|free of|free from/i);
  });

  it("offers the FDA's nine, and sends the avoided ones with the next ranking", async () => {
    const api = setup();
    await openPanel();
    const boxes = within(screen.getByRole("group", { name: "Keep out of suggestions" }));
    expect(boxes.getAllByRole("checkbox")).toHaveLength(9);
    await userEvent.click(boxes.getByRole("checkbox", { name: "Peanuts" }));
    await userEvent.click(boxes.getByRole("checkbox", { name: "Crustacean shellfish" }));

    await openWrench();
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));
    const body = rankRequests(api)[0]?.body as { avoid_allergens: string[] };
    expect(body.avoid_allergens.sort()).toEqual(["crustacean_shellfish", "peanuts"]);
  });

  it("asks again at once when the list changes while a popup is open", async () => {
    const api = setup();
    await openPanel();
    const boxes = within(screen.getByRole("group", { name: "Keep out of suggestions" }));
    await userEvent.click(boxes.getByRole("checkbox", { name: "Wheat" }));
    expect(window.localStorage.getItem("nourisearch.avoid-allergens")).toBe('["wheat"]');
    await userEvent.click(boxes.getByRole("checkbox", { name: "Wheat" }));
    expect(window.localStorage.getItem("nourisearch.avoid-allergens")).toBe("[]");
    expect(rankRequests(api)).toHaveLength(0);
  });

  it("remembers the list and the diet in this browser, and ignores unknown values", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["milk","not-an-allergen",3]');
    window.localStorage.setItem("nourisearch.diet", "vegan");
    const api = setup();
    await openPanel();
    expect(screen.getByRole("checkbox", { name: "Milk" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Diet" })).toHaveValue("vegan");

    await openWrench();
    await waitFor(() => expect(rankRequests(api)).toHaveLength(1));
    expect(rankRequests(api)[0]?.body).toMatchObject({ avoid_allergens: ["milk"], diet: "vegan" });
  });

  it("survives saved data that is not valid", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", "{not json");
    window.localStorage.setItem("nourisearch.diet", "carnivore");
    setup();
    await openPanel();
    expect(screen.getByRole("checkbox", { name: "Milk" })).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Diet" })).toHaveValue("any");
  });

  it("warns in words and marks the row when a dish has something avoided", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["soybeans"]');
    const base = dish();
    setup({
      food: dish({
        allergens: [
          {
            key: "soybeans",
            name: "Soybeans",
            relation: "contains",
            verification: "estimated",
            ingredient_names: ["Tofu"],
          },
        ],
        ingredients: base.ingredients.map((item) =>
          item.component_id === TOFU
            ? {
                ...item,
                allergens: [{ key: "soybeans", relation: "contains", verification: "estimated" }],
              }
            : item,
        ),
      }),
    });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(
      "You avoid Soybeans, and this dish has it. Found in: Tofu.",
    );
    expect(row("Tofu")).toHaveTextContent("Has Soybeans");
    expect(row("Salt, table")).not.toHaveTextContent("Has Soybeans");
  });

  it("tags a row only for what the person avoids", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["peanuts"]');
    const base = dish();
    setup({
      food: dish({
        ingredients: base.ingredients.map((item) =>
          item.component_id === TOFU
            ? {
                ...item,
                allergens: [{ key: "soybeans", relation: "contains", verification: "estimated" }],
              }
            : item,
        ),
      }),
    });
    await screen.findByRole("heading", { level: 1 });
    expect(row("Tofu")).not.toHaveTextContent("Has Soybeans");
  });

  it("says may have for a possible finding", async () => {
    window.localStorage.setItem("nourisearch.avoid-allergens", '["wheat"]');
    const base = dish();
    setup({
      food: dish({
        allergens: [
          {
            key: "wheat",
            name: "Wheat",
            relation: "may_contain",
            verification: "estimated",
            ingredient_names: [],
          },
        ],
        ingredients: base.ingredients.map((item) =>
          item.component_id === TOFU
            ? {
                ...item,
                allergens: [{ key: "wheat", relation: "may_contain", verification: "estimated" }],
              }
            : item,
        ),
      }),
    });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText(/this dish may have it/)).toBeInTheDocument();
    expect(row("Tofu")).toHaveTextContent("May have Wheat");
  });
});

describe("adding an ingredient", () => {
  const RESULT = {
    id: 900,
    slug: "egg-900",
    name: "Egg, whole, raw, fresh",
    kind: "basic",
    food_group: "Eggs",
    processing_level: "whole",
    source_key: "usda-fdc-sr-legacy-2018-04",
    match: "name",
  };

  it("finds a food and adds the stated amount, saying how big the recipe is", async () => {
    const api = setup({
      search: () => ({ query: "egg", results: [RESULT], has_more: false }),
    });
    await screen.findByRole("heading", { level: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Add an ingredient" }));
    expect(screen.getByText(/whole recipe weighs 100 g/)).toBeInTheDocument();

    await userEvent.type(screen.getByRole("searchbox", { name: "Food" }), "egg");
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    const grams = screen.getByRole("spinbutton", { name: "Amount in grams" });
    await userEvent.clear(grams);
    await userEvent.type(grams, "25");
    await userEvent.click(await screen.findByRole("button", { name: `Add ${RESULT.name}` }));

    await waitFor(() =>
      expect(simulationEdits(api)).toEqual([{ type: "add", food_id: 900, weight_g: 25 }]),
    );
    expect(screen.queryByRole("searchbox", { name: "Food" })).not.toBeInTheDocument();
  });

  it.each(["0", "-5", "100001", ""])("will not add an amount of %j", async (amount) => {
    setup({ search: () => ({ query: "egg", results: [RESULT], has_more: false }) });
    await screen.findByRole("heading", { level: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Add an ingredient" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Food" }), "egg");
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    const button = await screen.findByRole("button", { name: `Add ${RESULT.name}` });
    const grams = screen.getByRole("spinbutton", { name: "Amount in grams" });
    await userEvent.clear(grams);
    if (amount) await userEvent.type(grams, amount);
    expect(button).toBeDisabled();
  });

  it("says when nothing matches and when a search fails", async () => {
    let fail = false;
    setup({
      search: () =>
        fail
          ? jsonResponse({ code: "x", message: "Down." }, 500)
          : { query: "zzz", results: [], has_more: false },
    });
    await screen.findByRole("heading", { level: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Add an ingredient" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Food" }), "zzz");
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    expect(await screen.findByText("No foods match that.")).toBeInTheDocument();

    fail = true;
    await userEvent.type(screen.getByRole("searchbox", { name: "Food" }), "y");
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not finish");
  });

  it("is not offered for a food with no recipe to add to", async () => {
    setup({ food: dish({ ingredients: [], contributions: [], recipe: null }) });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Add an ingredient" })).not.toBeInTheDocument();
  });
});
