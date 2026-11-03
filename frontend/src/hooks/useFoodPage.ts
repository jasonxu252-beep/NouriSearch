import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  fetchComposition,
  simulateEdits,
  type FoodComposition,
  type IngredientEdit,
} from "../api/client";
import {
  excludedComponents,
  withEdit,
  withoutComponentEdit,
  withoutNewIngredient,
} from "../lib/edits";

export type FoodPageState =
  | { status: "loading" }
  | { status: "not_found" }
  | { status: "failed" }
  | { status: "ready"; base: FoodComposition; shown: FoodComposition };

export interface FoodPage {
  state: FoodPageState;
  edits: readonly IngredientEdit[];
  excluded: ReadonlySet<number>;
  isSimulating: boolean;
  simulationFailed: boolean;
  applyEdit: (edit: IngredientEdit) => void;
  undoComponent: (componentId: number) => void;
  undoNewIngredient: (ingredient: {
    replaces_component_id: number | null;
    food_id: number;
  }) => void;
  reset: () => void;
  retry: () => void;
}

const NO_EDITS: readonly IngredientEdit[] = [];

/** Loads a food, and applies ingredient edits by asking the API. Nothing is saved. */
export function useFoodPage(foodId: number): FoodPage {
  const [state, setState] = useState<FoodPageState>({ status: "loading" });
  const [edits, setEdits] = useState(NO_EDITS);
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
    setEdits(NO_EDITS);
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
    setEdits(NO_EDITS);
    setState((current) =>
      current.status === "ready" ? { ...current, shown: current.base } : current,
    );
  }, []);

  const applyEdits = useCallback(
    (next: readonly IngredientEdit[]) => {
      setSimulationFailed(false);
      if (next.length === 0) {
        showBase();
        return;
      }

      // Only the newest request may change the page, however the answers arrive.
      simulation.current?.abort();
      const controller = new AbortController();
      simulation.current = controller;
      setEdits(next);
      setIsSimulating(true);
      simulateEdits(foodId, next, controller.signal)
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
    [foodId, showBase],
  );

  const applyEdit = useCallback(
    (edit: IngredientEdit) => applyEdits(withEdit(edits, edit)),
    [applyEdits, edits],
  );
  const undoComponent = useCallback(
    (componentId: number) => applyEdits(withoutComponentEdit(edits, componentId)),
    [applyEdits, edits],
  );
  const undoNewIngredient = useCallback(
    (ingredient: { replaces_component_id: number | null; food_id: number }) =>
      applyEdits(withoutNewIngredient(edits, ingredient)),
    [applyEdits, edits],
  );

  const reset = useCallback(() => {
    setSimulationFailed(false);
    showBase();
  }, [showBase]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    state,
    edits,
    excluded: excludedComponents(edits),
    isSimulating,
    simulationFailed,
    applyEdit,
    undoComponent,
    undoNewIngredient,
    reset,
    retry,
  };
}
