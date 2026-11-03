import { useId, useState, type Ref } from "react";
import { Link } from "react-router";

import type {
  Diet,
  DishAllergen,
  Goal,
  Ingredient,
  IngredientEdit,
  Nutrient,
  Serving,
} from "../api/client";
import { useSubstitutions } from "../hooks/useSubstitutions";
import { t, translateKey } from "../i18n";
import { ContributionIndex, highlightOf, type IngredientHighlight } from "../lib/contributions";
import { defaultGoal } from "../lib/edits";
import { formatGrams, formatShare, inSentence } from "../lib/format";
import { AddIngredient } from "./AddIngredient";
import { AllergenPanel } from "./AllergenPanel";
import { IngredientMenu } from "./IngredientMenu";
import { PanelTab } from "./PanelTab";

interface Props {
  foodId: number;
  ingredients: readonly Ingredient[];
  allergens: readonly DishAllergen[];
  /** What the person has changed, which can be ahead of the API's latest answer. */
  edits: readonly IngredientEdit[];
  excluded: ReadonlySet<number>;
  avoid: ReadonlySet<string>;
  diet: Diet;
  recipeWeightG: number | null;
  serving: Serving;
  nutrients: ReadonlyMap<string, Nutrient>;
  contributions: ContributionIndex;
  recipeLabel: string | null;
  selectedNutrient: string | null;
  selectedComponent: number | null;
  isModified: boolean;
  isSimulating: boolean;
  simulationFailed: boolean;
  onSelectComponent: (componentId: number | null) => void;
  onApplyEdit: (edit: IngredientEdit) => void;
  onUndoComponent: (componentId: number) => void;
  onUndoNewIngredient: (ingredient: Ingredient) => void;
  onAvoidChange: (key: string, avoided: boolean) => void;
  onDietChange: (diet: Diet) => void;
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

/** An avoided allergen stands out on the row holding it, and never by color alone. */
function AvoidedTags({
  ingredient,
  avoid,
}: {
  ingredient: Ingredient;
  avoid: ReadonlySet<string>;
}) {
  return ingredient.allergens
    .filter((allergen) => avoid.has(allergen.key))
    .map((allergen) => (
      <span key={allergen.key} className="tag tag--warning">
        <span aria-hidden="true">{"⚠ "}</span>
        {t(allergen.relation === "contains" ? "ingredients.has" : "ingredients.mayHave", {
          allergen: translateKey(`allergen.${allergen.key}`),
        })}
      </span>
    ));
}

function openingGoal(
  ingredient: Ingredient,
  choice: { goal: Goal; componentId: number } | null,
  contributions: ContributionIndex,
  avoid: ReadonlySet<string>,
): Goal {
  const suggested = defaultGoal(ingredient, contributions, avoid);
  if (!choice) return suggested;
  if (choice.componentId === ingredient.component_id) return choice.goal;
  return suggested === "closest_match" ? suggested : choice.goal;
}

export function IngredientsPanel({
  foodId,
  ingredients,
  allergens,
  edits,
  excluded,
  avoid,
  diet,
  recipeWeightG,
  serving,
  nutrients,
  contributions,
  recipeLabel,
  selectedNutrient,
  selectedComponent,
  isModified,
  isSimulating,
  simulationFailed,
  onSelectComponent,
  onApplyEdit,
  onUndoComponent,
  onUndoNewIngredient,
  onAvoidChange,
  onDietChange,
  onReset,
  listRef,
}: Props) {
  const headingId = useId();
  const baseId = useId();
  const [openMenu, setOpenMenu] = useState<number | null>(null);
  // Once someone picks a goal it stays for this page, until they pick another. An ingredient holding
  // something they avoid still opens on its closest match, unless that is the one they chose it for.
  const [goalChoice, setGoalChoice] = useState<{ goal: Goal; componentId: number } | null>(null);
  const openIngredient = ingredients.find((item) => item.component_id === openMenu) ?? null;
  const goal = openIngredient
    ? openingGoal(openIngredient, goalChoice, contributions, avoid)
    : "more_protein";
  const substitutions = useSubstitutions(
    openMenu === null ? null : { foodId, componentId: openMenu, goal, avoid, diet, edits },
  );
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
            {isSimulating ? t("modified.updating") : t("modified.count", { count: edits.length })}
          </p>
          <button type="button" className="button" onClick={onReset}>
            {t("modified.reset")}
          </button>
        </div>
      )}

      <AllergenPanel
        allergens={allergens}
        avoid={avoid}
        diet={diet}
        onAvoidChange={onAvoidChange}
        onDietChange={onDietChange}
      />

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
              const supplied = contributions.suppliedBy(ingredient.component_id);
              const main = supplied[0];
              const remaining = ingredients.length - excluded.size;
              const isNew = ingredient.edit === "added";
              const isChanged = isExcluded || ingredient.edit === "scaled";
              return (
                <li
                  key={ingredient.component_id}
                  className="ingredient"
                  data-ingredient={ingredient.name}
                  data-highlight={highlightAttribute(highlight)}
                  data-selected={isSelected || undefined}
                  data-excluded={isExcluded || undefined}
                  data-edit={ingredient.edit === "none" ? undefined : ingredient.edit}
                >
                  <div className="ingredient__line">
                    {isNew ? (
                      <span className="ingredient__new">{t("ingredients.added")}</span>
                    ) : (
                      <IngredientMenu
                        ingredient={ingredient}
                        isChanged={isChanged}
                        isExcluded={isExcluded}
                        isOpen={openMenu === ingredient.component_id}
                        canRemove={remaining > 1}
                        note={
                          main
                            ? t("ingredients.supplies", {
                                share: formatShare(main.share ?? 0),
                                nutrient: inSentence(nutrients.get(main.nutrient_key)?.name ?? ""),
                              })
                            : null
                        }
                        goal={goal}
                        substitutions={substitutions.state}
                        nutrients={nutrients}
                        serving={serving}
                        onOpenChange={(open) => setOpenMenu(open ? ingredient.component_id : null)}
                        onGoalChange={(next) =>
                          setGoalChoice({ goal: next, componentId: ingredient.component_id })
                        }
                        onChoose={onApplyEdit}
                        onRetrySubstitutions={substitutions.retry}
                        onRemove={() =>
                          onApplyEdit({ type: "remove", component_id: ingredient.component_id })
                        }
                        onPutBack={() => onUndoComponent(ingredient.component_id)}
                      />
                    )}
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
                    {isNew && (
                      <button
                        type="button"
                        className="button button--small"
                        aria-label={t("ingredients.takeOutNamed", { ingredient: ingredient.name })}
                        onClick={() => onUndoNewIngredient(ingredient)}
                      >
                        {t("ingredients.takeOut")}
                      </button>
                    )}
                    {isChanged ? (
                      <button
                        type="button"
                        className="button button--small"
                        aria-label={t("ingredients.putBackNamed", { ingredient: ingredient.name })}
                        onClick={() => onUndoComponent(ingredient.component_id)}
                      >
                        {t("ingredients.putBackShort")}
                      </button>
                    ) : (
                      <span className="ingredient__weight">
                        {ingredient.weight_g === null
                          ? t("ingredients.noWeight")
                          : t("ingredients.weight", { amount: formatGrams(ingredient.weight_g) })}
                      </span>
                    )}
                  </div>
                  <AvoidedTags ingredient={ingredient} avoid={avoid} />
                  {isExcluded && (
                    <p className="ingredient__share">
                      {t(
                        ingredient.edit === "replaced"
                          ? "ingredients.replaced"
                          : "ingredients.removed",
                      )}
                    </p>
                  )}
                  {ingredient.edit === "scaled" && ingredient.original_weight_g !== null && (
                    <p className="ingredient__share">
                      {t("ingredients.weight", { amount: formatGrams(ingredient.weight_g ?? 0) })}{" "}
                      {t("ingredients.scaled", {
                        amount: formatGrams(ingredient.original_weight_g),
                      })}
                    </p>
                  )}
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
        {recipeWeightG !== null && (
          <AddIngredient recipeWeightG={recipeWeightG} onAdd={onApplyEdit} />
        )}
      </div>
    </section>
  );
}
