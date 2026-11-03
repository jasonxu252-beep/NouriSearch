import { useCallback, useEffect, useState } from "react";

import {
  fetchSubstitutions,
  type Diet,
  type Goal,
  type IngredientEdit,
  type Substitutions,
} from "../api/client";

export type SubstitutionsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; results: Substitutions };

interface Request {
  foodId: number;
  componentId: number;
  goal: Goal;
  avoid: ReadonlySet<string>;
  diet: Diet;
  edits: readonly IngredientEdit[];
}

/** Asks for ranked replacements while a popup is open. The newest question wins. */
export function useSubstitutions(request: Request | null) {
  const [state, setState] = useState<SubstitutionsState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  const avoidKey = request ? [...request.avoid].sort().join(",") : "";
  const editsKey = request ? JSON.stringify(request.edits) : "";
  const foodId = request?.foodId ?? null;
  const componentId = request?.componentId ?? null;
  const goal = request?.goal ?? null;
  const diet = request?.diet ?? null;

  useEffect(() => {
    if (foodId === null || componentId === null || goal === null || diet === null) {
      setState({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    fetchSubstitutions(
      foodId,
      {
        component_id: componentId,
        goal,
        avoid_allergens: avoidKey ? avoidKey.split(",") : [],
        diet,
        edits: JSON.parse(editsKey) as IngredientEdit[],
      },
      controller.signal,
    )
      .then((results) => setState({ status: "ready", results }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "failed" });
      });
    return () => controller.abort();
  }, [foodId, componentId, goal, diet, avoidKey, editsKey, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { state, retry };
}
