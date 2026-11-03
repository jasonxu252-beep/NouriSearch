import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { searchFoods, type FoodSearchResult } from "../api/client";
import { parseFoodType } from "../components/SearchBar";
import { t, translateKey } from "../i18n";

const PAGE_SIZE = 20;

type Results =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; foods: FoodSearchResult[]; hasMore: boolean };

/** Search results. Recent searches join this page in milestone 8, along with history. */
export function SearchPage() {
  const [params] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const foodType = parseFoodType(params.get("type"));
  const [results, setResults] = useState<Results>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!query) {
      setResults({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setResults({ status: "loading" });
    searchFoods(query, foodType, { limit: PAGE_SIZE, signal: controller.signal })
      .then((response) => {
        setResults({ status: "ready", foods: response.results, hasMore: response.has_more });
      })
      .catch(() => {
        if (!controller.signal.aborted) setResults({ status: "failed" });
      });
    return () => controller.abort();
  }, [query, foodType, attempt]);

  async function loadMore() {
    if (results.status !== "ready") return;
    try {
      const response = await searchFoods(query, foodType, {
        limit: PAGE_SIZE,
        offset: results.foods.length,
      });
      setResults({
        status: "ready",
        foods: [...results.foods, ...response.results],
        hasMore: response.has_more,
      });
    } catch {
      setResults({ status: "failed" });
    }
  }

  if (results.status === "idle") {
    return (
      <section className="page-message">
        <title>{t("app.name")}</title>
        <h1 className="visually-hidden">{t("search.pageTitle")}</h1>
        <p>{t("search.hint")}</p>
      </section>
    );
  }
  if (results.status === "loading") {
    return (
      <p className="page-message" role="status">
        {t("search.loading")}
      </p>
    );
  }
  if (results.status === "failed") {
    return (
      <div className="page-message" role="alert">
        <p>{t("search.failed")}</p>
        <button type="button" className="button" onClick={() => setAttempt(attempt + 1)}>
          {t("page.retry")}
        </button>
      </div>
    );
  }

  return (
    <section className="results">
      <title>{`${query} | ${t("app.name")}`}</title>
      <h1 className="results__title">{t("search.resultsFor", { query })}</h1>
      {results.foods.length === 0 ? (
        <p className="page-message">{t("search.noResults", { query })}</p>
      ) : (
        <ul className="results__list">
          {results.foods.map((food) => (
            <li key={food.id} className="result">
              <Link to={`/foods/${food.id}`} className="result__name">
                {food.name}
              </Link>
              <ul className="facts">
                {food.food_group && <li>{translateKey(`group.${food.food_group}`)}</li>}
                <li>{t(`level.${food.processing_level}`)}</li>
                <li>{translateKey(`dataset.${food.source_key}`)}</li>
                {food.match === "similar" && <li>{t("search.similarMatch")}</li>}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {results.hasMore && (
        <button type="button" className="button" onClick={loadMore}>
          {t("search.loadMore")}
        </button>
      )}
    </section>
  );
}
