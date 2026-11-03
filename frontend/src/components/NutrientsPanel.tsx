import { useId, type Ref } from "react";

import type {
  Conclusion,
  FoodComposition,
  Ingredient,
  Nutrient,
  Serving,
  ServingEvaluation,
  ServingNutrient,
  Source,
} from "../api/client";
import { t } from "../i18n";
import { ContributionIndex, HIGHLIGHT_MIN_SHARE, strengthOf } from "../lib/contributions";
import {
  formatAmount,
  formatDelta,
  formatGrams,
  formatPercent,
  formatShare,
  inSentence,
} from "../lib/format";
import { sectionsOf } from "../lib/nutrientSections";
import { DailyValueMeter } from "./DailyValueMeter";
import { NutrientDetail } from "./NutrientDetail";
import { NutrientMarkIcon } from "./NutrientMarkIcon";
import { PanelTab } from "./PanelTab";

interface Props {
  food: FoodComposition;
  serving: Serving;
  evaluation: ServingEvaluation;
  contributions: ContributionIndex;
  ingredients: ReadonlyMap<number, Ingredient>;
  sources: ReadonlyMap<string, Source>;
  selectedNutrient: string | null;
  selectedComponent: number | null;
  onSelectNutrient: (key: string | null) => void;
  onSelectServing: (key: string) => void;
  listRef?: Ref<HTMLDivElement>;
}

function servingOption(serving: Serving): string {
  if (serving.label === t("nutrients.per100g")) return serving.label;
  return t("nutrients.servingOption", { label: serving.label, grams: formatGrams(serving.grams) });
}

function valueText(nutrient: Nutrient, value: ServingNutrient | undefined): string {
  if (nutrient.status === "unknown" || !value || value.amount === null) {
    return t("nutrients.unknown");
  }
  const amount = formatAmount(value.amount, nutrient.unit);
  if (nutrient.status === "lower_bound") return t("nutrients.atLeast", { amount });
  if (nutrient.approximate) return t("nutrients.about", { amount });
  return amount;
}

function percentText(nutrient: Nutrient, value: ServingNutrient | undefined): string {
  if (nutrient.daily_value === null) return t("nutrients.noDailyValue");
  if (!value || value.percent_daily_value === null) return "";
  return t("nutrients.percentDv", { percent: formatPercent(value.percent_daily_value) });
}

/**
 * Removing an ingredient shrinks the batch, which nudges every other nutrient up a little. That is
 * not worth a line, so only changes as large as the highlight threshold are shown.
 */
function visibleDelta(nutrient: Nutrient, grams: number): number | null {
  const delta = nutrient.delta_per_100g;
  const before = nutrient.base_amount_per_100g;
  if (delta === null || before === null || before === 0) return null;
  return Math.abs(delta) / before >= HIGHLIGHT_MIN_SHARE ? (delta * grams) / 100 : null;
}

export function NutrientsPanel({
  food,
  serving,
  evaluation,
  contributions,
  ingredients,
  sources,
  selectedNutrient,
  selectedComponent,
  onSelectNutrient,
  onSelectServing,
  listRef,
}: Props) {
  const headingId = useId();
  const servingId = useId();
  const baseId = useId();
  const values = new Map(evaluation.nutrients.map((value) => [value.key, value]));
  const conclusions = new Map<string, Conclusion>(
    evaluation.conclusions.map((conclusion) => [conclusion.subject, conclusion]),
  );
  const onlyPer100g = food.servings.length === 1;
  const selectedName = selectedComponent === null ? null : ingredients.get(selectedComponent)?.name;

  return (
    <section className="panel panel--nutrients" aria-labelledby={headingId}>
      <PanelTab />
      <header className="panel__header">
        <h2 id={headingId} className="panel__title">
          {t("nutrients.title")}
        </h2>
        <div className="serving">
          <label htmlFor={servingId} className="serving__label">
            {t("nutrients.serving")}
          </label>
          <select
            id={servingId}
            className="serving__select"
            value={serving.key}
            onChange={(event) => onSelectServing(event.target.value)}
          >
            {food.servings.map((option) => (
              <option key={option.key} value={option.key}>
                {servingOption(option)}
              </option>
            ))}
          </select>
        </div>
        {onlyPer100g && <p className="panel__note">{t("nutrients.noServing")}</p>}
        <p className="meter-key">
          <span className="meter-key__tick" aria-hidden="true" />
          {t("nutrients.scale", { threshold: food.high_percent_daily_value })}
        </p>
      </header>

      <div className="panel__scroll" ref={listRef} tabIndex={-1}>
        {sectionsOf(food.nutrients).map((section) => (
          <div key={section.id} className="nutrient-section">
            <h3 className="nutrient-section__title">{t(section.title)}</h3>
            <ul className="nutrient-list">
              {section.nutrients.map((nutrient) => {
                const value = values.get(nutrient.key);
                const mark = value?.mark ?? "question";
                const isSelected = selectedNutrient === nutrient.key;
                const detailId = `${baseId}-${nutrient.key}`;
                const cell =
                  selectedComponent === null
                    ? undefined
                    : contributions.cell(nutrient.key, selectedComponent);
                const strength = strengthOf(cell?.share);
                const percent = percentText(nutrient, value);
                const delta = visibleDelta(nutrient, serving.grams);
                return (
                  <li
                    key={nutrient.key}
                    className="nutrient"
                    data-nutrient={nutrient.key}
                    data-highlight={strength ?? undefined}
                    data-selected={isSelected || undefined}
                  >
                    <button
                      type="button"
                      className="nutrient__button"
                      aria-expanded={isSelected}
                      aria-controls={isSelected ? detailId : undefined}
                      onClick={() => onSelectNutrient(isSelected ? null : nutrient.key)}
                    >
                      <span className="nutrient__line">
                        <span className="nutrient__name">{nutrient.name}</span>
                        <span className="nutrient__value">
                          {valueText(nutrient, value)}
                          {percent && <span className="nutrient__percent"> {percent}</span>}
                        </span>
                        <NutrientMarkIcon mark={mark} partial={nutrient.status === "lower_bound"} />
                      </span>
                      {nutrient.daily_value !== null && (
                        <DailyValueMeter
                          percent={value?.percent_daily_value ?? null}
                          highAt={food.high_percent_daily_value}
                          mark={mark}
                          isLowerBound={nutrient.status === "lower_bound"}
                        />
                      )}
                      {delta !== null && (
                        <span className="nutrient__delta">
                          {t("nutrients.change", { delta: formatDelta(delta, nutrient.unit) })}
                        </span>
                      )}
                      {strength !== null && cell?.share != null && selectedName && (
                        <span className="nutrient__share">
                          {t("ingredients.contribution", {
                            share: formatShare(cell.share),
                            nutrient: inSentence(nutrient.name),
                          })}
                        </span>
                      )}
                    </button>
                    {isSelected && (
                      <NutrientDetail
                        id={detailId}
                        nutrient={nutrient}
                        mark={mark}
                        conclusion={conclusions.get(nutrient.key)}
                        contributors={contributions.contributorsTo(nutrient.key)}
                        gaps={contributions.gapsIn(nutrient.key)}
                        ingredients={ingredients}
                        sources={sources}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
