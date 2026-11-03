import { useId, type Ref } from "react";

import type {
  Conclusion,
  FoodComposition,
  Ingredient,
  Nutrient,
  ReferencePopulation,
  ReferenceValue,
  Serving,
  ServingEvaluation,
  ServingNutrient,
  Source,
} from "../api/client";
import { t, translateKey } from "../i18n";
import { ContributionIndex, HIGHLIGHT_MIN_SHARE, strengthOf } from "../lib/contributions";
import {
  formatAmount,
  formatDelta,
  formatGrams,
  formatPercent,
  formatShare,
  inSentence,
} from "../lib/format";
import { isKeyNutrient, sectionsOf } from "../lib/nutrientSections";
import {
  compareWithReference,
  GENERAL_POPULATION,
  POPULATION_GROUPS,
  parsePopulation,
  type Comparison,
} from "../lib/references";
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
  population: ReferencePopulation;
  references: ReadonlyMap<string, ReferenceValue>;
  referencesFailed: boolean;
  onSelectPopulation: (population: ReferencePopulation) => void;
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

function percentText(nutrient: Nutrient, comparison: Comparison): string {
  const { reference, percent } = comparison;
  if (!reference) return t("nutrients.noDailyValue");
  if (percent === null) return "";
  if (reference.kind === "dv") {
    return t("nutrients.percentDv", { percent: formatPercent(percent) });
  }
  return t("nutrients.percentOf", {
    percent: formatPercent(percent),
    reference: formatAmount(reference.amount, nutrient.unit),
  });
}

/** The API's own Daily Value, which keeps the page right if the reference values cannot load. */
function dailyValueReference(nutrient: Nutrient): ReferenceValue | undefined {
  if (nutrient.daily_value === null) return undefined;
  return {
    nutrient_key: nutrient.key,
    amount: nutrient.daily_value,
    unit: nutrient.unit,
    kind: "dv",
    source_key: nutrient.daily_value_source_key ?? "",
    is_general: true,
  };
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
  population,
  references,
  referencesFailed,
  onSelectPopulation,
  selectedNutrient,
  selectedComponent,
  onSelectNutrient,
  onSelectServing,
  listRef,
}: Props) {
  const headingId = useId();
  const servingId = useId();
  const populationId = useId();
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
        <div className="serving">
          <label htmlFor={populationId} className="serving__label">
            {t("nutrients.compareWith")}
          </label>
          <select
            id={populationId}
            className="serving__select"
            value={population}
            onChange={(event) => onSelectPopulation(parsePopulation(event.target.value))}
          >
            <option value={GENERAL_POPULATION}>{t("population.general_label")}</option>
            {POPULATION_GROUPS.map((group) => (
              <optgroup key={group.label} label={t(group.label)}>
                {group.populations.map((option) => (
                  <option key={option} value={option}>
                    {translateKey(`population.${option}`)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        {onlyPer100g && <p className="panel__note">{t("nutrients.noServing")}</p>}
        {referencesFailed && (
          <p className="notice notice--error" role="alert">
            {t("nutrients.referenceFailed")}
          </p>
        )}
        <p className="meter-key">
          <span className="meter-key__tick" aria-hidden="true" />
          {population === GENERAL_POPULATION
            ? t("nutrients.scale", { threshold: food.high_percent_daily_value })
            : t("nutrients.scalePersonal", {
                group: translateKey(`population.${population}`),
                threshold: food.high_percent_daily_value,
              })}
        </p>
        <p className="meter-key">
          <span className="meter-key__swatch" aria-hidden="true" />
          {t("nutrients.keyNote")}
        </p>
        <p className="panel__note">{t("nutrients.compareNote")}</p>
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
                const comparison = compareWithReference(
                  nutrient,
                  value?.amount,
                  references.get(nutrient.key) ?? dailyValueReference(nutrient),
                );
                const percent = percentText(nutrient, comparison);
                const delta = visibleDelta(nutrient, serving.grams);
                const isKey = isKeyNutrient(nutrient);
                return (
                  <li
                    key={nutrient.key}
                    className="nutrient"
                    data-nutrient={nutrient.key}
                    data-key={isKey || undefined}
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
                        <span className="nutrient__name">
                          {nutrient.name}
                          {isKey && (
                            <span className="visually-hidden">, {t("nutrients.keyNutrient")}</span>
                          )}
                        </span>
                        <span className="nutrient__value">
                          {valueText(nutrient, value)}
                          {percent && <span className="nutrient__percent"> {percent}</span>}
                        </span>
                        <NutrientMarkIcon mark={mark} partial={nutrient.status === "lower_bound"} />
                      </span>
                      {comparison.reference && (
                        <DailyValueMeter
                          percent={comparison.percent}
                          highAt={comparison.showHighLine ? food.high_percent_daily_value : null}
                          mark={mark}
                          isLowerBound={nutrient.status === "lower_bound"}
                          isKey={isKey}
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
                        population={population}
                        reference={comparison.reference}
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
