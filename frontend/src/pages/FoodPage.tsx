import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import type { FoodComposition, Ingredient, IngredientEdit, Nutrient, Source } from "../api/client";
import { ImageCarousel } from "../components/ImageCarousel";
import { IngredientsPanel } from "../components/IngredientsPanel";
import { NutrientsPanel } from "../components/NutrientsPanel";
import { ProfileActions } from "../components/ProfileActions";
import { RelatedPanel } from "../components/RelatedPanel";
import { useAvoidList } from "../hooks/useAvoidList";
import { useFoodPage } from "../hooks/useFoodPage";
import { useReferenceIntakes } from "../hooks/useReferenceIntakes";
import { t, translateKey } from "../i18n";
import { ContributionIndex } from "../lib/contributions";
import { editedComponent } from "../lib/edits";

type Selection =
  { type: "nutrient"; key: string } | { type: "ingredient"; componentId: number } | null;

// Below this the panels stack, and the other one can be far away on the page.
const PANELS_SIDE_BY_SIDE = "(min-width: 721px)";

/**
 * Highlighting something off screen would look like nothing happened, so the largest contributor
 * comes into view. On a phone the page stays put, because jumping would lose the person's place.
 */
function revealFirstHighlight(panel: HTMLElement | null): void {
  if (!window.matchMedia?.(PANELS_SIDE_BY_SIDE).matches) return;
  const first =
    panel?.querySelector(
      '[data-highlight="strong"], [data-highlight="medium"], [data-highlight="weak"]',
    ) ?? panel?.querySelector("[data-highlight]");
  first?.scrollIntoView?.({ block: "nearest" });
}

/** Details open under the row, and may land below the fold. */
function revealSelection(panel: HTMLElement | null): void {
  panel?.querySelector("[data-selected]")?.scrollIntoView?.({ block: "nearest" });
}

function FoodOverview({ food }: { food: FoodComposition }) {
  return (
    <div className="overview">
      <ImageCarousel foodName={food.name} images={food.images} />
      <section className="panel panel--description" aria-labelledby="description-title">
        <h2 id="description-title" className="panel__title">
          {t("overview.description")}
        </h2>
        {food.description && <p>{food.description}</p>}
        <ul className="facts">
          {food.food_group_key && <li>{translateKey(`group.${food.food_group_key}`)}</li>}
          <li>{t(`level.${food.processing_level}`)}</li>
          <li>{translateKey(`dataset.${food.source_key}`)}</li>
        </ul>
        <p className="panel__note">{t("overview.processingCredit")}</p>
      </section>
      <RelatedPanel foodId={food.id} />
    </div>
  );
}

function SourcesList({ sources }: { sources: readonly Source[] }) {
  return (
    <details className="sources">
      <summary>{t("sources.title")}</summary>
      <ul>
        {sources.map((source) => (
          <li key={source.key}>
            {source.url ? (
              <a href={source.url}>
                {t("sources.item", { publisher: source.publisher, title: source.title })}
              </a>
            ) : (
              t("sources.item", { publisher: source.publisher, title: source.title })
            )}{" "}
            {source.version && t("sources.version", { version: source.version })}{" "}
            {source.license && t("sources.license", { license: source.license })}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function FoodPage({ foodId }: { foodId: number }) {
  const page = useFoodPage(foodId);
  const { population, setPopulation, intakes, failed: referencesFailed } = useReferenceIntakes();
  const { avoid, setAvoided, diet, setDiet } = useAvoidList();
  const [selection, setSelection] = useState<Selection>(null);
  const [servingChoice, setServingChoice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const ingredientList = useRef<HTMLDivElement>(null);
  const nutrientList = useRef<HTMLDivElement>(null);

  const shown = page.state.status === "ready" ? page.state.shown : null;
  const contributions = useMemo(() => new ContributionIndex(shown?.contributions ?? []), [shown]);
  const ingredients = useMemo(
    () => new Map<number, Ingredient>((shown?.ingredients ?? []).map((i) => [i.component_id, i])),
    [shown],
  );
  const nutrients = useMemo(
    () => new Map<string, Nutrient>((shown?.nutrients ?? []).map((n) => [n.key, n])),
    [shown],
  );
  const sources = useMemo(() => {
    const known = new Map<string, Source>((shown?.sources ?? []).map((s) => [s.key, s]));
    for (const source of intakes?.sources ?? []) {
      if (!known.has(source.key))
        known.set(source.key, { ...source, version: null, license: null });
    }
    return known;
  }, [shown, intakes]);
  const references = useMemo(
    () => new Map((intakes?.values ?? []).map((value) => [value.nutrient_key, value])),
    [intakes],
  );

  useEffect(() => {
    function clearOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelection((current) => {
          if (current !== null) setAnnouncement(t("selection.cleared"));
          return null;
        });
      }
    }
    window.addEventListener("keydown", clearOnEscape);
    return () => window.removeEventListener("keydown", clearOnEscape);
  }, []);

  useEffect(() => {
    if (selection?.type === "nutrient") {
      revealFirstHighlight(ingredientList.current);
      revealSelection(nutrientList.current);
    }
    if (selection?.type === "ingredient") {
      revealFirstHighlight(nutrientList.current);
      revealSelection(ingredientList.current);
    }
  }, [selection]);

  if (page.state.status === "loading") {
    return (
      <p className="page-message" role="status">
        {t("page.loading")}
      </p>
    );
  }
  if (page.state.status === "not_found") {
    return (
      <div className="page-message" role="alert">
        <p>{t("page.notFound")}</p>
        <Link to="/">{t("page.backToSearch")}</Link>
      </div>
    );
  }
  if (page.state.status === "failed") {
    return (
      <div className="page-message" role="alert">
        <p>{t("page.failed")}</p>
        <button type="button" className="button" onClick={page.retry}>
          {t("page.retry")}
        </button>
      </div>
    );
  }

  const food = page.state.shown;
  const serving =
    food.servings.find((option) => option.key === servingChoice) ??
    food.servings.find((option) => option.is_default) ??
    food.servings[0];
  const evaluation = food.evaluations.find((result) => result.serving_key === serving?.key);
  if (!serving || !evaluation) return null;

  const selectedNutrient = selection?.type === "nutrient" ? selection.key : null;
  const selectedComponent = selection?.type === "ingredient" ? selection.componentId : null;

  function selectNutrient(key: string | null) {
    setSelection(key === null ? null : { type: "nutrient", key });
    setAnnouncement(
      key === null
        ? t("selection.cleared")
        : t("selection.nutrient", {
            nutrient: nutrients.get(key)?.name ?? "",
            count: contributions.contributorsTo(key).length,
          }),
    );
  }

  function selectComponent(componentId: number | null) {
    setSelection(componentId === null ? null : { type: "ingredient", componentId });
    setAnnouncement(
      componentId === null
        ? t("selection.cleared")
        : t("selection.ingredient", {
            ingredient: ingredients.get(componentId)?.name ?? "",
            count: contributions.suppliedBy(componentId).length,
          }),
    );
  }

  /** A new ingredient's ID lasts for one answer, and an edited one may no longer be there. */
  function clearStaleSelection(componentId: number | null) {
    if (
      selectedComponent !== null &&
      (selectedComponent < 0 || selectedComponent === componentId)
    ) {
      setSelection(null);
    }
  }

  function applyEdit(edit: IngredientEdit) {
    clearStaleSelection(editedComponent(edit));
    page.applyEdit(edit);
  }

  function undoComponent(componentId: number) {
    clearStaleSelection(null);
    page.undoComponent(componentId);
  }

  function undoNewIngredient(ingredient: Ingredient) {
    clearStaleSelection(null);
    page.undoNewIngredient(ingredient);
  }

  function reset() {
    clearStaleSelection(null);
    page.reset();
  }

  return (
    <article className="food">
      <title>{`${food.name} | ${t("app.name")}`}</title>
      <h1 className="food__title">{food.name}</h1>
      <div className="visually-hidden" aria-live="polite">
        {announcement}
      </div>
      <div className="food__grid">
        <FoodOverview food={food} />
        <div className="food__ingredients">
          <IngredientsPanel
            foodId={food.id}
            ingredients={food.ingredients}
            allergens={food.allergens}
            edits={page.edits}
            excluded={page.excluded}
            avoid={avoid}
            diet={diet}
            recipeWeightG={food.recipe?.raw_weight_g ?? null}
            serving={serving}
            nutrients={nutrients}
            contributions={contributions}
            recipeLabel={food.recipe?.label ?? null}
            selectedNutrient={selectedNutrient}
            selectedComponent={selectedComponent}
            isModified={food.is_modified || page.edits.length > 0}
            isSimulating={page.isSimulating}
            simulationFailed={page.simulationFailed}
            onSelectComponent={selectComponent}
            onApplyEdit={applyEdit}
            onUndoComponent={undoComponent}
            onUndoNewIngredient={undoNewIngredient}
            onAvoidChange={setAvoided}
            onDietChange={setDiet}
            onReset={reset}
            listRef={ingredientList}
          />
          <ProfileActions />
        </div>
        <NutrientsPanel
          food={food}
          serving={serving}
          evaluation={evaluation}
          contributions={contributions}
          ingredients={ingredients}
          sources={sources}
          population={population}
          references={references}
          referencesFailed={referencesFailed}
          onSelectPopulation={setPopulation}
          selectedNutrient={selectedNutrient}
          selectedComponent={selectedComponent}
          onSelectNutrient={selectNutrient}
          onSelectServing={setServingChoice}
          listRef={nutrientList}
        />
      </div>
      <SourcesList sources={food.sources} />
    </article>
  );
}
