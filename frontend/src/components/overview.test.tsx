import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { RelatedFoods } from "../api/client";
import { RELATED } from "../test/fixtures";
import { jsonResponse, stubApi } from "../test/render";
import { ImageCarousel } from "./ImageCarousel";
import { RelatedPanel } from "./RelatedPanel";

const IMAGES = [
  { url: "https://example.org/a.jpg", license: "CC-BY-4.0", attribution: "A photographer" },
  { url: "https://example.org/b.jpg", license: "CC0-1.0", attribution: "Another photographer" },
];

describe("the image carousel", () => {
  it("says plainly when a food has no image", () => {
    render(<ImageCarousel foodName="Bibimbap" images={[]} />);
    expect(screen.getByText("No image yet")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("credits every image", () => {
    render(<ImageCarousel foodName="Bibimbap" images={IMAGES.slice(0, 1)} />);
    expect(screen.getByRole("img", { name: "Bibimbap" })).toHaveAttribute(
      "src",
      "https://example.org/a.jpg",
    );
    expect(screen.getByText(/A photographer. License: CC-BY-4.0/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("moves through several images in both directions and wraps around", async () => {
    render(<ImageCarousel foodName="Bibimbap" images={IMAGES} />);
    await userEvent.click(screen.getByRole("button", { name: "Next image" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "https://example.org/b.jpg");
    expect(screen.getByText(/Image 2 of 2/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next image" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "https://example.org/a.jpg");
    await userEvent.click(screen.getByRole("button", { name: "Previous image" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "https://example.org/b.jpg");
  });
});

function renderRelated(related: RelatedFoods | Response = RELATED) {
  stubApi({ "GET /v1/foods/7/related": () => related });
  render(
    <MemoryRouter>
      <RelatedPanel foodId={7} />
    </MemoryRouter>,
  );
}

describe("the Similar panel", () => {
  it("links each similar food and says why it is related", async () => {
    renderRelated();
    const link = await screen.findByRole("link", { name: /Tofu stew/ });
    expect(link).toHaveAttribute("href", "/foods/8");
    expect(within(link).getByText("Shares Doubanjiang")).toBeInTheDocument();
  });

  it("switches to the Explore tab, as in the sketch", async () => {
    renderRelated();
    await screen.findByRole("link", { name: /Tofu stew/ });
    await userEvent.click(screen.getByRole("tab", { name: "Explore" }));
    const link = screen.getByRole("link", { name: /Fried rice/ });
    expect(within(link).getByText("Also in Mixed dishes")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Tofu stew/ })).toBeNull();
  });

  it("moves between tabs with the arrow keys", async () => {
    renderRelated();
    await screen.findByRole("link", { name: /Tofu stew/ });
    screen.getByRole("tab", { name: "Similar" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Explore" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Explore" })).toHaveAttribute("aria-selected", "true");
  });

  it.each([
    ["uses_this_food", "Uses this food"],
    ["similar_name", "Similar name"],
  ] as const)("explains the reason %s", async (reason, text) => {
    renderRelated({
      similar: [
        {
          id: 8,
          slug: "x-8",
          name: "Food",
          kind: "basic",
          food_group: null,
          reason,
          shared_ingredients: [],
        },
      ],
      explore: [],
    });
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("says when nothing is related, and survives a failed request", async () => {
    renderRelated({ similar: [], explore: [] });
    expect(await screen.findByText(/Nothing related/)).toBeInTheDocument();
  });

  it("does not break the page when the request fails", async () => {
    renderRelated(jsonResponse({ code: "internal_error", message: "No." }, 500));
    expect(await screen.findByText(/Nothing related/)).toBeInTheDocument();
  });
});
