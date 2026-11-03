import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";

import { fetchRelated, type RelatedFood, type RelatedFoods } from "../api/client";
import { t, translateKey } from "../i18n";

type Tab = "similar" | "explore";
const TABS: readonly Tab[] = ["similar", "explore"];

function reasonText(food: RelatedFood): string {
  switch (food.reason) {
    case "shares_ingredients":
      // USDA's names are long and full of commas, so only the rarest shared one reads clearly.
      return t("related.sharesIngredient", { ingredient: food.shared_ingredients[0] ?? "" });
    case "uses_this_food":
      return t("related.usesThisFood");
    case "similar_name":
      return t("related.similarName");
    case "same_group":
      return t("related.sameGroup", {
        group: translateKey(`group.${food.food_group ?? "other"}`),
      });
  }
}

/** The sketch's Similar panel with its Explore tab. Opening a card is recorded in milestone 8. */
export function RelatedPanel({ foodId }: { foodId: number }) {
  const baseId = useId();
  const [tab, setTab] = useState<Tab>("similar");
  const [related, setRelated] = useState<RelatedFoods | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setRelated(null);
    setFailed(false);
    fetchRelated(foodId, controller.signal)
      .then(setRelated)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [foodId]);

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = tab === "similar" ? "explore" : "similar";
    setTab(next);
    document.getElementById(`${baseId}-tab-${next}`)?.focus();
  }

  const foods = related?.[tab] ?? [];

  return (
    <section className="panel panel--related" aria-label={t("related.tabs")}>
      <div className="related-tabs" role="tablist" aria-label={t("related.tabs")}>
        {TABS.map((name) => (
          <button
            key={name}
            id={`${baseId}-tab-${name}`}
            type="button"
            role="tab"
            className="related-tabs__tab"
            aria-selected={tab === name}
            aria-controls={`${baseId}-panel`}
            tabIndex={tab === name ? 0 : -1}
            onClick={() => setTab(name)}
            onKeyDown={onTabKey}
          >
            {t(`related.${name}`)}
          </button>
        ))}
      </div>
      <div
        id={`${baseId}-panel`}
        role="tabpanel"
        aria-labelledby={`${baseId}-tab-${tab}`}
        className="related-list"
      >
        {related === null && !failed && <p className="panel__empty">{t("related.loading")}</p>}
        {(failed || (related !== null && foods.length === 0)) && (
          <p className="panel__empty">{t("related.none")}</p>
        )}
        {foods.length > 0 && (
          <ul>
            {foods.map((food) => (
              <li key={food.id} className="related-card">
                <Link to={`/foods/${food.id}`} className="related-card__link">
                  <span className="related-card__image" aria-hidden="true">
                    {food.name.charAt(0)}
                  </span>
                  <span className="related-card__text">
                    <span className="related-card__name">{food.name}</span>
                    <span className="related-card__reason">{reasonText(food)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
