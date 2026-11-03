import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchComposition, simulateWithout, type FoodComposition } from "../api/client";

export type FoodPageState =
  | { status: "loading" }
  | { status: "not_found" }
  | { status: "failed" }
  | { status: "ready"; base: FoodComposition; shown: FoodComposition };

export interface FoodPage {
  state: FoodPageState;
  excluded: ReadonlySet<number>;
  isSimulating: boolean;
  simulationFailed: boolean;
  setIncluded: (componentId: number, included: boolean) => void;
  reset: () => void;
  retry: () => void;
}

const NOTHING_EXCLUDED: ReadonlySet<number> = new Set();

/** Loads a food, and applies ingredient exclusions by asking the API. Nothing is saved. */
export function useFoodPage(foodId: number): FoodPage {
  const [state, setState] = useState<FoodPageState>({ status: "loading" });
  const [excluded, setExcluded] = useState(NOTHING_EXCLUDED);
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationFailed, setSimulationFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const simulation = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!Number.isInteger(foodId)) {
      setState({ status: "not_found" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    setExcluded(NOTHING_EXCLUDED);
    setSimulationFailed(false);
    fetchComposition(foodId, controller.signal)
      .then((composition) => {
        setState({ status: "ready", base: composition, shown: composition });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const notFound = error instanceof ApiError && error.status === 404;
        setState({ status: notFound ? "not_found" : "failed" });
      });
    return () => controller.abort();
  }, [foodId, attempt]);

  useEffect(() => () => simulation.current?.abort(), []);

  const showBase = useCallback(() => {
    simulation.current?.abort();
    setIsSimulating(false);
    setExcluded(NOTHING_EXCLUDED);
    setState((current) =>
      current.status === "ready" ? { ...current, shown: current.base } : current,
    );
  }, []);

  const setIncluded = useCallback(
    (componentId: number, included: boolean) => {
      const next = new Set(excluded);
      if (included) next.delete(componentId);
      else next.add(componentId);

      setSimulationFailed(false);
      if (next.size === 0) {
        showBase();
        return;
      }

      // Only the newest request may change the page, however the answers arrive.
      simulation.current?.abort();
      const controller = new AbortController();
      simulation.current = controller;
      setExcluded(next);
      setIsSimulating(true);
      simulateWithout(foodId, [...next], controller.signal)
        .then((composition) => {
          if (controller.signal.aborted) return;
          setState((current) =>
            current.status === "ready" ? { ...current, shown: composition } : current,
          );
          setIsSimulating(false);
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          showBase();
          setSimulationFailed(true);
        });
    },
    [excluded, foodId, showBase],
  );

  const reset = useCallback(() => {
    setSimulationFailed(false);
    showBase();
  }, [showBase]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return { state, excluded, isSimulating, simulationFailed, setIncluded, reset, retry };
}
