import { useId, type Ref } from "react";
import { Link } from "react-router";

import type { Ingredient, Nutrient } from "../api/client";
import { t } from "../i18n";
import { ContributionIndex, highlightOf, type IngredientHighlight } from "../lib/contributions";
import { formatGrams, formatShare, inSentence } from "../lib/format";
import { PanelTab } from "./PanelTab";

interface Props {
  ingredients: readonly Ingredient[];
  /** What the person has excluded, which can be ahead of the API's latest answer. */
  excluded: ReadonlySet<number>;
  nutrients: ReadonlyMap<string, Nutrient>;
  contributions: ContributionIndex;
  recipeLabel: string | null;
  selectedNutrient: string | null;
  selectedComponent: number | null;
  isModified: boolean;
  isSimulating: boolean;
  simulationFailed: boolean;
  onSelectComponent: (componentId: number | null) => void;
  onToggle: (componentId: number, included: boolean) => void;
  onReset: () => void;
  listRef?: Ref<HTMLDivElement>;
}

function highlightText(highlight: IngredientHighlight, nutrient: string): string {
  switch (highlight.kind) {
    case "share":
      return t(
        highlight.partial ? "ingredients.partialShareOfNutrient" : "ingredients.shareOfNutrient",
        {
          share: formatShare(highlight.share),
          nutrient,
        },
      );
    case "no_quantity":
      return t("ingredients.noQuantity", { nutrient });
    case "no_data":
      return t("ingredients.noData", { nutrient });
  }
}

function highlightAttribute(highlight: IngredientHighlight | null): string | undefined {
  if (highlight === null) return undefined;
  return highlight.kind === "share" ? highlight.strength : highlight.kind;
}

export function IngredientsPanel({
  ingredients,
  excluded,
  nutrients,
  contributions,
  recipeLabel,
  selectedNutrient,
  selectedComponent,
  isModified,
  isSimulating,
  simulationFailed,
  onSelectComponent,
  onToggle,
  onReset,
  listRef,
}: Props) {
  const headingId = useId();
  const baseId = useId();
  const nutrientName = inSentence(
    selectedNutrient ? (nutrients.get(selectedNutrient)?.name ?? "") : "",
  );

  return (
    <section className="panel panel--ingredients" aria-labelledby={headingId}>
      <PanelTab />
      <header className="panel__header">
        <h2 id={headingId} className="panel__title">
          {t("ingredients.title")}
        </h2>
        {recipeLabel && (
          <p className="panel__note">
            <strong>{recipeLabel}.</strong> {t("recipe.surveyNote")}
          </p>
        )}
      </header>

      {simulationFailed && (
        <p className="notice notice--error" role="alert">
          {t("modified.failed")}
        </p>
      )}
      {isModified && (
        <div className="notice notice--modified">
          <p>
            <strong>{t("modified.title")}.</strong>{" "}
            {isSimulating ? t("modified.updating") : t("modified.count", { count: excluded.size })}
          </p>
          <button type="button" className="button" onClick={onReset}>
            {t("modified.reset")}
          </button>
        </div>
      )}

      <div className="panel__scroll" ref={listRef} tabIndex={-1} aria-busy={isSimulating}>
        {ingredients.length === 0 ? (
          <p className="panel__empty">{t("ingredients.none")}</p>
        ) : (
          <ul className="ingredient-list">
            {ingredients.map((ingredient) => {
              const isSelected = selectedComponent === ingredient.component_id;
              const isExcluded = excluded.has(ingredient.component_id);
              const detailId = `${baseId}-${ingredient.component_id}`;
              const cell =
                selectedNutrient === null
                  ? undefined
                  : contributions.cell(selectedNutrient, ingredient.component_id);
              const highlight = cell && !isExcluded ? highlightOf(cell) : null;
              const supplied = isSelected ? contributions.suppliedBy(ingredient.component_id) : [];
              return (
                <li
                  key={ingredient.component_id}
                  className="ingredient"
                  data-ingredient={ingredient.name}
                  data-highlight={highlightAttribute(highlight)}
                  data-selected={isSelected || undefined}
                  data-excluded={isExcluded || undefined}
                >
                  <div className="ingredient__line">
                    <input
                      type="checkbox"
                      className="ingredient__check"
                      checked={!isExcluded}
                      onChange={(event) => onToggle(ingredient.component_id, event.target.checked)}
                      aria-label={t("ingredients.include", { ingredient: ingredient.name })}
                    />
                    <button
                      type="button"
                      className="ingredient__name"
                      aria-expanded={isSelected}
                      aria-controls={isSelected ? detailId : undefined}
                      onClick={() => onSelectComponent(isSelected ? null : ingredient.component_id)}
                    >
                      {ingredient.name}
                      {ingredient.kind === "additive" && (
                        <span className="tag tag--warning">{t("ingredients.additive")}</span>
                      )}
                      {ingredient.considerations.length > 0 && (
                        <span className="tag tag--warning" title={t("ingredients.consideration")}>
                          <span aria-hidden="true">{"⚠"}</span>
                          <span className="visually-hidden">{t("ingredients.consideration")}</span>
                        </span>
                      )}
                    </button>
                    <span className="ingredient__weight">
                      {isExcluded
                        ? t("ingredients.excluded")
                        : ingredient.weight_g === null
                          ? t("ingredients.noWeight")
                          : t("ingredients.weight", { amount: formatGrams(ingredient.weight_g) })}
                    </span>
                  </div>
                  {highlight && (
                    <p className="ingredient__share">
                      {highlight.kind === "no_data" && (
                        <span className="ingredient__unknown" aria-hidden="true">
                          ?
                        </span>
                      )}
                      {highlightText(highlight, nutrientName)}
                    </p>
                  )}
                  {isSelected && (
                    <div id={detailId} className="detail" role="group" aria-label={ingredient.name}>
                      <h3 className="detail__heading">{t("ingredients.contributesTo")}</h3>
                      {supplied.length === 0 ? (
                        <p className="detail__note">{t("ingredients.contributesNothing")}</p>
                      ) : (
                        <ul className="detail__list">
                          {supplied.slice(0, 6).map((suppliedCell) => (
                            <li key={suppliedCell.nutrient_key}>
                              {t("ingredients.contribution", {
                                share: formatShare(suppliedCell.share ?? 0),
                                nutrient: inSentence(
                                  nutrients.get(suppliedCell.nutrient_key)?.name ?? "",
                                ),
                              })}
                            </li>
                          ))}
                        </ul>
                      )}
                      <h3 className="detail__heading">{t("ingredients.replacements")}</h3>
                      <p className="detail__note">{t("ingredients.noReplacements")}</p>
                      <p className="detail__note">
                        <Link to={`/foods/${ingredient.food_id}`}>
                          {t("ingredients.open", { ingredient: ingredient.name })}
                        </Link>
                      </p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
