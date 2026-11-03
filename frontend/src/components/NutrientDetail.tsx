import type {
  Conclusion,
  ContributionCell,
  Ingredient,
  Mark,
  Nutrient,
  ReferencePopulation,
  ReferenceValue,
  Source,
} from "../api/client";
import { t, translateKey, type MessageParams } from "../i18n";
import { formatAmount, formatPercent, formatShare } from "../lib/format";
import { GENERAL_POPULATION } from "../lib/references";

interface Props {
  id: string;
  nutrient: Nutrient;
  mark: Mark;
  conclusion: Conclusion | undefined;
  contributors: readonly ContributionCell[];
  gaps: readonly ContributionCell[];
  ingredients: ReadonlyMap<number, Ingredient>;
  sources: ReadonlyMap<string, Source>;
  population: ReferencePopulation;
  reference: ReferenceValue | null;
}

function conclusionParams(conclusion: Conclusion): MessageParams {
  const params: MessageParams = { ...conclusion.message_params };
  const percent = conclusion.message_params.percent;
  if (typeof percent === "number") params.percent = formatPercent(percent);
  return params;
}

function referenceNote(
  population: ReferencePopulation,
  reference: ReferenceValue | null,
): string | null {
  if (!reference || population === GENERAL_POPULATION) return null;
  const amount = formatAmount(reference.amount, reference.unit);
  const group = translateKey(`population.${population}`);
  if (reference.is_general) return t("detail.reference.general", { amount, group });
  if (reference.kind === "rda") return t("detail.reference.rda", { amount, group });
  if (reference.kind === "ai") return t("detail.reference.ai", { amount, group });
  return t("detail.reference.cdrr", { amount, group });
}

function provenanceNotes(nutrient: Nutrient): string[] {
  const notes: string[] = [];
  if (nutrient.key === "energy") notes.push(t("detail.energyNote"));
  if (nutrient.key === "protein") notes.push(t("detail.proteinNote"));
  if (nutrient.key === "total_sugars") notes.push(t("detail.totalSugarsNote"));
  if (nutrient.key === "added_sugars" && nutrient.status === "unknown") {
    notes.push(t("detail.addedSugarsNote", { dailyValue: nutrient.daily_value ?? 50 }));
  }
  if (nutrient.status === "unknown" && nutrient.key !== "added_sugars") {
    notes.push(t("detail.unknownValue"));
  }
  if (nutrient.status === "estimated") notes.push(t("detail.estimated"));
  if (nutrient.status === "calculated") notes.push(t("detail.calculated"));
  if (nutrient.status === "lower_bound") notes.push(t("detail.lowerBound"));
  if (nutrient.approximate) notes.push(t("detail.approximate"));
  if (nutrient.amount_per_100g === 0 && nutrient.status === "known") {
    notes.push(
      t(nutrient.value_kind === "assumed_zero" ? "detail.zeroAssumed" : "detail.zeroReported"),
    );
  }
  if (nutrient.daily_value === null && !["total_sugars", "energy"].includes(nutrient.key)) {
    notes.push(t("detail.noDailyValue"));
  }
  return notes;
}

/**
 * What clicking a nutrient shows. Effects of excess and nutrient functions join this in milestone
 * 6, once that content has citations and the owner has reviewed it.
 */
export function NutrientDetail({
  id,
  nutrient,
  mark,
  conclusion,
  contributors,
  gaps,
  ingredients,
  sources,
  population,
  reference,
}: Props) {
  const citedKeys = new Set([
    ...nutrient.source_keys,
    ...(conclusion?.sources ?? []),
    ...(nutrient.daily_value_source_key ? [nutrient.daily_value_source_key] : []),
    ...(reference ? [reference.source_key] : []),
  ]);
  const cited = [...citedKeys].flatMap((key) => {
    const source = sources.get(key);
    return source ? [source] : [];
  });
  const missing = new Set(nutrient.missing_ingredients);
  for (const gap of gaps) {
    const name = ingredients.get(gap.component_id)?.name;
    if (name) missing.add(name);
  }
  const compared = referenceNote(population, reference);

  return (
    <div id={id} className="detail" role="group" aria-label={nutrient.name}>
      {conclusion && (
        <p className="detail__conclusion">
          {translateKey(conclusion.message_key, conclusionParams(conclusion))}
        </p>
      )}
      {mark === "green" && <p className="detail__note">{t("detail.notFlagged")}</p>}
      {compared && <p className="detail__note">{compared}</p>}
      {provenanceNotes(nutrient).map((note) => (
        <p key={note} className="detail__note">
          {note}
        </p>
      ))}

      {contributors.length > 0 && (
        <>
          <h4 className="detail__heading">{t("detail.topContributors")}</h4>
          <ul className="detail__list">
            {contributors.slice(0, 5).map((cell) => (
              <li key={cell.component_id}>
                {t("detail.contributor", {
                  ingredient: ingredients.get(cell.component_id)?.name ?? "",
                  share: formatShare(cell.share ?? 0),
                })}
              </li>
            ))}
          </ul>
        </>
      )}

      {missing.size > 0 && (
        <>
          <h4 className="detail__heading">{t("detail.missing")}</h4>
          <ul className="detail__list">
            {[...missing].map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </>
      )}

      {cited.length > 0 && (
        <>
          <h4 className="detail__heading">{t("detail.sources")}</h4>
          <ul className="detail__list detail__list--sources">
            {cited.map((source) => (
              <li key={source.key}>
                {source.url ? <a href={source.url}>{source.title}</a> : source.title}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
