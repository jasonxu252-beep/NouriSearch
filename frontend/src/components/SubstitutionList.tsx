import type {
  Goal,
  Ingredient,
  IngredientEdit,
  Nutrient,
  ScoreParts,
  Serving,
  Source,
  SubstitutionOption,
} from "../api/client";
import type { SubstitutionsState } from "../hooks/useSubstitutions";
import { t, translateKey } from "../i18n";
import { formatAmount, formatGrams, inSentence } from "../lib/format";

interface Props {
  ingredient: Ingredient;
  state: SubstitutionsState;
  nutrients: ReadonlyMap<string, Nutrient>;
  goal: Goal;
  /** Values read per serving, the same as the nutrient panel beside this list. */
  serving: Serving;
  onChoose: (edit: IngredientEdit) => void;
  onRetry: () => void;
}

function optionName(option: SubstitutionOption, ingredient: Ingredient): string {
  if (option.scale_factor !== null) {
    return t("substitution.scale", {
      percent: Math.round(option.scale_factor * 100),
      grams: formatGrams((ingredient.original_weight_g ?? 0) * option.scale_factor),
    });
  }
  return option.replacements
    .map((item) => t("substitution.part", { name: item.name, grams: formatGrams(item.weight_g) }))
    .join(t("substitution.partJoin"));
}

function nutrientName(nutrients: ReadonlyMap<string, Nutrient>, key: string | null): string {
  return inSentence(key ? (nutrients.get(key)?.name ?? key) : "");
}

function effectText(
  option: SubstitutionOption,
  nutrients: ReadonlyMap<string, Nutrient>,
  serving: Serving,
): string | null {
  const effect = option.goal_effect;
  if (!effect) return null;
  const perServing = (per100g: number) => (per100g * serving.grams) / 100;
  return t(effect.approximate ? "substitution.effectApproximate" : "substitution.effect", {
    nutrient: nutrients.get(effect.nutrient_key)?.name ?? effect.nutrient_key,
    serving: serving.label,
    before: formatAmount(perServing(effect.before_per_100g), effect.unit),
    after: formatAmount(perServing(effect.after_per_100g), effect.unit),
  });
}

function scorePart(value: number | null | undefined): string {
  return value === null || value === undefined
    ? t("substitution.score.noData")
    : String(Math.round(value * 100));
}

function ScoreDetails({ scores, sources }: { scores: ScoreParts; sources: readonly Source[] }) {
  return (
    <details className="option__details">
      <summary>{t("substitution.score.title")}</summary>
      <dl className="option__scores">
        {scores.nutrition !== null && (
          <>
            <dt>{t("substitution.score.nutrition")}</dt>
            <dd>{scorePart(scores.nutrition)}</dd>
          </>
        )}
        <dt>{t("substitution.score.flavor")}</dt>
        <dd>{scorePart(scores.flavor)}</dd>
        <dt>{t("substitution.score.texture")}</dt>
        <dd>{scorePart(scores.texture)}</dd>
        <dt>{t("substitution.score.fit")}</dt>
        <dd>{scorePart(scores.culinary_fit)}</dd>
        <dt>{t("substitution.score.total")}</dt>
        <dd>{scorePart(scores.total)}</dd>
        <dt>{t("substitution.score.completeness")}</dt>
        <dd>{t("substitution.score.percent", { percent: scorePart(scores.completeness) })}</dd>
      </dl>
      {sources.length > 0 && (
        <p className="menu__note">
          {t("substitution.sources", {
            sources: sources.map((source) => source.publisher).join(", "),
          })}
        </p>
      )}
    </details>
  );
}

function allergenLine(option: SubstitutionOption): string[] {
  const named = (relation: "contains" | "may_contain") =>
    option.allergens
      .filter((allergen) => allergen.relation === relation)
      .map((allergen) => translateKey(`allergen.${allergen.key}`))
      .join(", ");
  const lines: string[] = [];
  const contains = named("contains");
  const may = named("may_contain");
  if (contains) lines.push(t("allergens.contains", { allergens: contains }));
  if (may) lines.push(t("allergens.mayContain", { allergens: may }));
  return lines;
}

function OptionRow({
  option,
  ingredient,
  nutrients,
  serving,
  sources,
  onChoose,
}: {
  option: SubstitutionOption;
  ingredient: Ingredient;
  nutrients: ReadonlyMap<string, Nutrient>;
  serving: Serving;
  sources: readonly Source[];
  onChoose: (edit: IngredientEdit) => void;
}) {
  const name = optionName(option, ingredient);
  const effect = effectText(option, nutrients, serving);
  const cited = sources.filter((source) => option.source_keys.includes(source.key));
  return (
    <li className="option" data-option={option.key} data-origin={option.origin}>
      <button type="button" className="option__choose" onClick={() => onChoose(option.edit)}>
        <span className="option__name">{name}</span>
        {effect && <span className="option__effect">{effect}</span>}
      </button>
      <ul className="option__reasons">
        <li>{translateKey(`substitution.origin.${option.origin}`)}</li>
        {option.reasons.map((reason) => (
          <li key={`${reason.code}-${reason.nutrient_key ?? ""}`}>
            {translateKey(`substitution.reason.${reason.code}`, {
              nutrient: nutrientName(nutrients, reason.nutrient_key),
            })}
          </li>
        ))}
        {allergenLine(option).map((line) => (
          <li key={line} className="option__allergens">
            {line}
          </li>
        ))}
      </ul>
      {option.note && <p className="menu__note">{option.note}</p>}
      <ScoreDetails scores={option.scores} sources={cited} />
    </li>
  );
}

/** The ranked replacements in the wrench popup, or why there are none. */
export function SubstitutionList({
  ingredient,
  state,
  nutrients,
  goal,
  serving,
  onChoose,
  onRetry,
}: Props) {
  if (state.status === "idle") return null;
  if (state.status === "loading") {
    return (
      <p className="menu__note" role="status">
        {t("substitution.loading")}
      </p>
    );
  }
  if (state.status === "failed") {
    return (
      <div role="alert">
        <p className="menu__note">{t("substitution.failed")}</p>
        <button type="button" className="button button--small" onClick={onRetry}>
          {t("page.retry")}
        </button>
      </div>
    );
  }

  const { results } = state;
  if (results.unavailable_reason) {
    return (
      <p className="menu__note">
        {translateKey(`substitution.unavailable.${results.unavailable_reason}`, {
          nutrient: nutrientName(nutrients, results.nutrient_key),
        })}
      </p>
    );
  }
  return (
    <>
      {results.options.length === 0 ? (
        <p className="menu__note">
          {translateKey(goal === "closest_match" ? "substitution.noneClose" : "substitution.none", {
            nutrient: nutrientName(nutrients, results.nutrient_key),
          })}
        </p>
      ) : (
        <ol className="option-list">
          {results.options.map((option) => (
            <OptionRow
              key={option.key}
              option={option}
              ingredient={ingredient}
              nutrients={nutrients}
              serving={serving}
              sources={results.sources}
              onChoose={onChoose}
            />
          ))}
        </ol>
      )}
      {results.could_not_evaluate.length > 0 && (
        <p className="menu__note">
          {t("substitution.couldNotEvaluate", {
            names: results.could_not_evaluate.join(", "),
          })}
        </p>
      )}
      {results.hidden_for_allergens > 0 && (
        <p className="menu__note">
          {t("substitution.hiddenAllergens", { count: results.hidden_for_allergens })}
        </p>
      )}
      {results.hidden_for_diet > 0 && (
        <p className="menu__note">
          {t("substitution.hiddenDiet", { count: results.hidden_for_diet })}
        </p>
      )}
    </>
  );
}
