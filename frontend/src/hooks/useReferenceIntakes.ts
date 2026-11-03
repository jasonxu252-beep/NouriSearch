import { useCallback, useEffect, useState } from "react";

import {
  fetchReferenceIntakes,
  type ReferenceIntakes,
  type ReferencePopulation,
} from "../api/client";
import { parsePopulation } from "../lib/references";

const STORAGE_KEY = "nourisearch.reference-population";

function readSaved(): ReferencePopulation {
  try {
    return parsePopulation(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return parsePopulation(null);
  }
}

/**
 * The chosen age and sex group, kept in this browser only until accounts exist. If the values cannot
 * load, the page says so and keeps the FDA Daily Values it already has.
 */
export function useReferenceIntakes() {
  const [population, setPopulationState] = useState<ReferencePopulation>(readSaved);
  const [intakes, setIntakes] = useState<ReferenceIntakes | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    fetchReferenceIntakes(population, controller.signal)
      .then(setIntakes)
      .catch(() => {
        if (controller.signal.aborted) return;
        setIntakes(null);
        setFailed(true);
      });
    return () => controller.abort();
  }, [population]);

  const setPopulation = useCallback((next: ReferencePopulation) => {
    setPopulationState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private browsing can refuse storage. The choice still applies to this page.
    }
  }, []);

  return { population, setPopulation, intakes, failed };
}
