import type {
  Conclusion,
  ContributionCell,
  Ingredient,
  Mark,
  Nutrient,
  Source,
} from "../api/client";
import { t, translateKey, type MessageParams } from "../i18n";
import { formatPercent, formatShare } from "../lib/format";

interface Props {
  id: string;
  nutrient: Nutrient;
  mark: Mark;
  conclusion: Conclusion | undefined;
  contributors: readonly ContributionCell[];
  gaps: readonly ContributionCell[];
  ingredients: ReadonlyMap<number, Ingredient>;
  sources: ReadonlyMap<string, Source>;
}

function conclusionParams(conclusion: Conclusion): MessageParams {
  const params: MessageParams = { ...conclusion.message_params };
  const percent = conclusion.message_params.percent;
  if (typeof percent === "number") params.percent = formatPercent(percent);
  return params;
}

function provenanceNotes(nutrient: Nutrient): string[] {
  const notes: string[] = [];
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
  if (nutrient.daily_value === null && nutrient.key !== "total_sugars") {
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
}: Props) {
  const citedKeys = new Set([
    ...nutrient.source_keys,
    ...(conclusion?.sources ?? []),
    ...(nutrient.daily_value_source_key ? [nutrient.daily_value_source_key] : []),
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

  return (
    <div id={id} className="detail" role="group" aria-label={nutrient.name}>
      {conclusion && (
        <p className="detail__conclusion">
          {translateKey(conclusion.message_key, conclusionParams(conclusion))}
        </p>
      )}
      {mark === "green" && <p className="detail__note">{t("detail.notFlagged")}</p>}
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
