import { useId } from "react";

import type { Diet, DishAllergen } from "../api/client";
import { ALLERGEN_KEYS, DIETS } from "../hooks/useAvoidList";
import { t, translateKey } from "../i18n";

interface Props {
  allergens: readonly DishAllergen[];
  avoid: ReadonlySet<string>;
  diet: Diet;
  onAvoidChange: (key: string, avoided: boolean) => void;
  onDietChange: (diet: Diet) => void;
}

function names(allergens: readonly DishAllergen[]): string {
  return allergens.map((allergen) => translateKey(`allergen.${allergen.key}`)).join(", ");
}

/**
 * What names and recipes reveal about this dish, and what someone wants kept out of suggestions.
 * USDA lists no allergens, so this can only ever say what was found. It never says a food has none.
 */
export function AllergenPanel({ allergens, avoid, diet, onAvoidChange, onDietChange }: Props) {
  const dietId = useId();
  const contains = allergens.filter((allergen) => allergen.relation === "contains");
  const may = allergens.filter((allergen) => allergen.relation === "may_contain");
  const avoidedHere = allergens.filter((allergen) => avoid.has(allergen.key));

  return (
    <section className="allergens" aria-label={t("allergens.title")}>
      {avoidedHere.map((allergen) => (
        <p key={allergen.key} className="notice notice--warning" role="status">
          <span aria-hidden="true">{"⚠ "}</span>
          {t(allergen.relation === "contains" ? "allergens.avoidedHas" : "allergens.avoidedMay", {
            allergen: translateKey(`allergen.${allergen.key}`),
          })}
          {allergen.ingredient_names.length > 0 &&
            ` ${t("allergens.through", { ingredients: allergen.ingredient_names.join(", ") })}`}
        </p>
      ))}
      <p className="allergens__found">
        <strong>{t("allergens.title")}.</strong>{" "}
        {contains.length > 0 && `${t("allergens.contains", { allergens: names(contains) })} `}
        {may.length > 0 && `${t("allergens.mayContain", { allergens: names(may) })} `}
        {allergens.length === 0 && `${t("allergens.noneFound")} `}
        {t("allergens.disclaimer")}
      </p>
      <details className="allergens__details">
        <summary>
          {t("allergens.choices")}
          {avoid.size > 0 && ` ${t("allergens.avoidingCount", { count: avoid.size })}`}
        </summary>
        <fieldset className="allergens__choices">
          <legend>{t("allergens.avoidTitle")}</legend>
          {ALLERGEN_KEYS.map((key) => (
            <label key={key} className="allergens__choice">
              <input
                type="checkbox"
                checked={avoid.has(key)}
                onChange={(event) => onAvoidChange(key, event.target.checked)}
              />
              {translateKey(`allergen.${key}`)}
            </label>
          ))}
        </fieldset>
        <p className="allergens__diet">
          <label htmlFor={dietId}>{t("diet.label")}</label>
          <select
            id={dietId}
            value={diet}
            onChange={(event) => onDietChange(event.target.value as Diet)}
          >
            {DIETS.map((option) => (
              <option key={option} value={option}>
                {translateKey(`diet.${option}`)}
              </option>
            ))}
          </select>
        </p>
        <p className="panel__note">{t("allergens.storedHere")}</p>
      </details>
    </section>
  );
}
