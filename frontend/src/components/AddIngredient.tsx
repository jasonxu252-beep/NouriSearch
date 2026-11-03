import { useEffect, useId, useState, type FormEvent } from "react";

import { searchFoods, type FoodSearchResult, type IngredientEdit } from "../api/client";
import { t } from "../i18n";
import { formatGrams } from "../lib/format";

interface Props {
  /** The recipe's total, because a batch is far larger than a serving. */
  recipeWeightG: number | null;
  onAdd: (edit: IngredientEdit) => void;
}

const DEFAULT_GRAMS = "50";
const RESULTS = 6;
const MAX_GRAMS = 100_000;

/** Adds any food to the recipe. Whatever is added shows its allergens like any other ingredient. */
export function AddIngredient({ recipeWeightG, onAdd }: Props) {
  const queryId = useId();
  const gramsId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [grams, setGrams] = useState(DEFAULT_GRAMS);
  const [results, setResults] = useState<readonly FoodSearchResult[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!submitted) return;
    const controller = new AbortController();
    setFailed(false);
    setResults(null);
    searchFoods(submitted, "all", { limit: RESULTS, signal: controller.signal })
      .then((page) => setResults(page.results))
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [submitted]);

  if (!isOpen) {
    return (
      <button type="button" className="button add-ingredient__open" onClick={() => setIsOpen(true)}>
        {t("add.open")}
      </button>
    );
  }

  const weight = Number(grams);
  const isValidWeight = Number.isFinite(weight) && weight > 0 && weight <= MAX_GRAMS;

  function search(event: FormEvent) {
    event.preventDefault();
    setSubmitted(query.trim());
  }

  return (
    <div className="add-ingredient">
      <form onSubmit={search} className="add-ingredient__row">
        <label htmlFor={queryId}>{t("add.search")}</label>
        <input
          id={queryId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" className="button button--small">
          {t("add.find")}
        </button>
      </form>
      <p className="add-ingredient__row">
        <label htmlFor={gramsId}>{t("add.grams")}</label>
        <input
          id={gramsId}
          type="number"
          min="1"
          max={MAX_GRAMS}
          value={grams}
          aria-invalid={!isValidWeight}
          onChange={(event) => setGrams(event.target.value)}
        />
      </p>
      {recipeWeightG !== null && (
        <p className="panel__note">
          {t("add.recipeWeight", { grams: formatGrams(recipeWeightG) })}
        </p>
      )}
      {failed && (
        <p className="panel__note" role="alert">
          {t("add.failed")}
        </p>
      )}
      {results?.length === 0 && <p className="panel__note">{t("add.none")}</p>}
      {results && results.length > 0 && (
        <ul className="add-ingredient__results">
          {results.map((food) => (
            <li key={food.id}>
              <button
                type="button"
                className="button button--small"
                disabled={!isValidWeight}
                aria-label={t("add.addNamed", { food: food.name })}
                onClick={() => {
                  onAdd({ type: "add", food_id: food.id, weight_g: weight });
                  setIsOpen(false);
                  setResults(null);
                  setSubmitted("");
                  setQuery("");
                }}
              >
                {t("add.add")}
              </button>
              <span>{food.name}</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="button button--small" onClick={() => setIsOpen(false)}>
        {t("add.close")}
      </button>
    </div>
  );
}
