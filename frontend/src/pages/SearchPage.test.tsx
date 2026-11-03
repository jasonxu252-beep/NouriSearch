import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FoodSearchResult } from "../api/client";
import { dish, RELATED } from "../test/fixtures";
import { jsonResponse, renderApp, stubApi } from "../test/render";

function food(
  id: number,
  name: string,
  overrides: Partial<FoodSearchResult> = {},
): FoodSearchResult {
  return {
    id,
    slug: `food-${id}`,
    name,
    kind: "basic",
    food_group: "vegetables",
    processing_level: "whole",
    source_key: "usda-fdc-fndds-2024-10",
    match: "prefix",
    ...overrides,
  };
}

function searchRoutes(results: FoodSearchResult[], hasMore = false) {
  return {
    "GET /v1/foods/search": (url: URL) => ({
      query: url.searchParams.get("q"),
      results,
      has_more: hasMore,
    }),
  };
}

describe("the search page", () => {
  it("starts with a hint and no results", () => {
    stubApi({});
    renderApp("/");
    expect(screen.getByText(/Try bibimbap/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("shows results from the address, with what tells each record apart", async () => {
    stubApi(
      searchRoutes([
        food(1, "Broccoli, raw", { source_key: "usda-fdc-foundation-2026-10" }),
        food(2, "Broccoli, raw", { source_key: "usda-fdc-sr-legacy-2018-04" }),
      ]),
    );
    renderApp("/?q=broccoli");
    const links = await screen.findAllByRole("link", { name: "Broccoli, raw" });
    expect(links[0]).toHaveAttribute("href", "/foods/1");
    expect(screen.getByText("USDA Foundation")).toBeInTheDocument();
    expect(screen.getByText("USDA SR Legacy")).toBeInTheDocument();
    expect(screen.getAllByText("Whole food")).toHaveLength(2);
  });

  it("is honest that a result only matched approximately", async () => {
    stubApi(searchRoutes([food(1, "Broccoli, raw", { match: "similar" })]));
    renderApp("/?q=brocoli");
    expect(await screen.findByText("Similar spelling")).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    stubApi(searchRoutes([]));
    renderApp("/?q=zzzz");
    expect(await screen.findByText(/No foods match "zzzz"/)).toBeInTheDocument();
  });

  it("offers a retry when search fails", async () => {
    let failing = true;
    stubApi({
      "GET /v1/foods/search": (url: URL) =>
        failing
          ? jsonResponse({ code: "internal_error", message: "No." }, 500)
          : { query: url.searchParams.get("q"), results: [food(1, "Rice")], has_more: false },
    });
    renderApp("/?q=rice");
    expect(await screen.findByRole("alert")).toHaveTextContent("not responding");
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Rice" })).toBeInTheDocument();
  });

  it("loads more results onto the same page", async () => {
    stubApi({
      "GET /v1/foods/search": (url: URL) => {
        const offset = Number(url.searchParams.get("offset"));
        return offset === 0
          ? { query: "rice", results: [food(1, "Rice one")], has_more: true }
          : { query: "rice", results: [food(2, "Rice two")], has_more: false };
      },
    });
    renderApp("/?q=rice");
    await screen.findByRole("link", { name: "Rice one" });
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    await screen.findByRole("link", { name: "Rice two" });
    expect(screen.getByRole("link", { name: "Rice one" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });
});

describe("the search bar", () => {
  it("goes to the results on submit", async () => {
    const api = stubApi(searchRoutes([food(1, "Rice")]));
    renderApp("/");
    await userEvent.type(
      screen.getByRole("combobox", { name: "Search for a food" }),
      "rice{Enter}",
    );
    expect(await screen.findByRole("link", { name: "Rice" })).toBeInTheDocument();
    expect(api.requests.at(-1)?.path).toBe("/v1/foods/search");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent('Results for "rice"');
  });

  it("suggests foods while typing, without asking for one letter", async () => {
    const api = stubApi(searchRoutes([food(1, "Rice, white")]));
    renderApp("/");
    const box = screen.getByRole("combobox", { name: "Search for a food" });
    await userEvent.type(box, "r");
    await new Promise((resolve) => setTimeout(resolve, 260));
    expect(api.requests).toHaveLength(0);

    await userEvent.type(box, "i");
    const list = await screen.findByRole("listbox");
    expect(within(list).getByRole("option", { name: /Rice, white/ })).toBeInTheDocument();
    expect(box).toHaveAttribute("aria-expanded", "true");
  });

  it("chooses a suggestion from the keyboard", async () => {
    stubApi({
      ...searchRoutes([food(7, "Mapo tofu"), food(8, "Tofu")]),
      "GET /v1/foods/7/composition": () => dish(),
      "GET /v1/foods/7/related": () => RELATED,
    });
    renderApp("/");
    const box = screen.getByRole("combobox", { name: "Search for a food" });
    await userEvent.click(box);
    await userEvent.paste("tofu");
    const list = await screen.findByRole("listbox");

    await userEvent.keyboard("{ArrowDown}");
    const first = within(list).getAllByRole("option")[0];
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(box).toHaveAttribute("aria-activedescendant", first?.id);

    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "Mapo tofu" })).toBeInTheDocument();
  });

  it("closes suggestions on Escape", async () => {
    stubApi(searchRoutes([food(1, "Rice")]));
    renderApp("/");
    const box = screen.getByRole("combobox", { name: "Search for a food" });
    await userEvent.type(box, "rice");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  });

  it("offers every filter from the plan, with All chosen first", () => {
    stubApi({});
    renderApp("/");
    const names = screen.getAllByRole("radio").map((radio) => radio.closest("label")?.textContent);
    expect(names).toEqual([
      "All",
      "Whole foods",
      "Fruits",
      "Vegetables",
      "Proteins",
      "Grains",
      "Dishes",
      "Ingredients",
    ]);
    expect(screen.getByRole("radio", { name: "All" })).toBeChecked();
  });

  it("applies a filter to the search and keeps it in the address", async () => {
    const seen: (string | null)[] = [];
    stubApi({
      "GET /v1/foods/search": (url: URL) => {
        seen.push(url.searchParams.get("type"));
        return { query: "apple", results: [food(1, "Apple, raw")], has_more: false };
      },
    });
    renderApp("/?q=apple");
    await screen.findByRole("link", { name: "Apple, raw" });

    await userEvent.click(screen.getByRole("radio", { name: "Whole foods" }));

    await waitFor(() => expect(seen.at(-1)).toBe("whole_foods"));
    expect(screen.getByRole("radio", { name: "Whole foods" })).toBeChecked();
  });

  it("reads a filter from the address, and ignores one it does not know", async () => {
    stubApi(searchRoutes([]));
    renderApp("/?q=apple&type=fruits");
    expect(screen.getByRole("radio", { name: "Fruits" })).toBeChecked();
    await screen.findByText(/No foods match/);
  });

  it("falls back to All for a filter it does not know", async () => {
    stubApi(searchRoutes([]));
    renderApp("/?q=apple&type=nonsense");
    expect(screen.getByRole("radio", { name: "All" })).toBeChecked();
    await screen.findByText(/No foods match/);
  });
});

describe("controls for later milestones", () => {
  it("are present, as in the sketches, and say they are not available yet", () => {
    stubApi({});
    renderApp("/");
    expect(screen.getByRole("button", { name: /Search with a photo/ })).toBeDisabled();
    expect(screen.getByLabelText("Cuisine")).toBeDisabled();
    expect(screen.getByLabelText("Cuisine")).toHaveDisplayValue("All cuisines");
  });

  it("explains that the profile will not use searches", async () => {
    stubApi({});
    renderApp("/profile");
    expect(screen.getByText(/not your searches/)).toBeInTheDocument();
  });
});
