import { useCallback, useState } from "react";

import type { Diet } from "../api/client";

const ALLERGENS_KEY = "nourisearch.avoid-allergens";
const DIET_KEY = "nourisearch.diet";

/** The FDA's nine major allergens, in the order the FDA lists them. */
export const ALLERGEN_KEYS = [
  "milk",
  "eggs",
  "fish",
  "crustacean_shellfish",
  "tree_nuts",
  "peanuts",
  "wheat",
  "soybeans",
  "sesame",
] as const;

export const DIETS: readonly Diet[] = ["any", "vegetarian", "vegan"];

const KNOWN_ALLERGENS = new Set<string>(ALLERGEN_KEYS);

function readAllergens(): ReadonlySet<string> {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(ALLERGENS_KEY) ?? "[]");
    if (!Array.isArray(saved)) return new Set();
    return new Set(saved.filter((key): key is string => KNOWN_ALLERGENS.has(key as string)));
  } catch {
    return new Set();
  }
}

function readDiet(): Diet {
  try {
    const saved = window.localStorage.getItem(DIET_KEY);
    return DIETS.find((diet) => diet === saved) ?? "any";
  } catch {
    return "any";
  }
}

function save(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private browsing can refuse storage. The choice still applies to this page.
  }
}

/** What someone avoids, kept in this browser only until accounts exist. */
export function useAvoidList() {
  const [avoid, setAvoid] = useState<ReadonlySet<string>>(readAllergens);
  const [diet, setDietState] = useState<Diet>(readDiet);

  const setAvoided = useCallback((key: string, avoided: boolean) => {
    setAvoid((current) => {
      const next = new Set(current);
      if (avoided) next.add(key);
      else next.delete(key);
      save(ALLERGENS_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const setDiet = useCallback((next: Diet) => {
    setDietState(next);
    save(DIET_KEY, next);
  }, []);

  return { avoid, setAvoided, diet, setDiet };
}
