import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import type { Goal, Ingredient, IngredientEdit, Nutrient, Serving } from "../api/client";
import type { SubstitutionsState } from "../hooks/useSubstitutions";
import { t, translateKey } from "../i18n";
import { GOALS } from "../lib/edits";
import { SubstitutionList } from "./SubstitutionList";

interface Props {
  ingredient: Ingredient;
  /** Removed, replaced, or using a different amount, so it can go back to how it was. */
  isChanged: boolean;
  isExcluded: boolean;
  isOpen: boolean;
  /** A dish needs at least one ingredient, so the last one cannot leave. */
  canRemove: boolean;
  /** What this ingredient matters for, to help decide. */
  note: string | null;
  goal: Goal;
  substitutions: SubstitutionsState;
  nutrients: ReadonlyMap<string, Nutrient>;
  serving: Serving;
  onOpenChange: (open: boolean) => void;
  onGoalChange: (goal: Goal) => void;
  onChoose: (edit: IngredientEdit) => void;
  onRetrySubstitutions: () => void;
  onRemove: () => void;
  onPutBack: () => void;
}

const GAP = 4;
const EDGE = 8;
const FOCUSABLE = "select, button:not(:disabled)";

/**
 * The wrench from the owner's sketch, and the small popup it opens. The popup is positioned against
 * the window, because the ingredient list scrolls and would otherwise cut it off.
 */
export function IngredientMenu({
  ingredient,
  isChanged,
  isExcluded,
  isOpen,
  canRemove,
  note,
  goal,
  substitutions,
  nutrients,
  serving,
  onOpenChange,
  onGoalChange,
  onChoose,
  onRetrySubstitutions,
  onRemove,
  onPutBack,
}: Props) {
  const popupId = useId();
  const goalId = useId();
  const wrench = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  const close = useCallback(
    (returnFocus: boolean) => {
      onOpenChange(false);
      if (returnFocus) wrench.current?.focus();
    },
    [onOpenChange],
  );

  useLayoutEffect(() => {
    if (!isOpen) {
      setPosition(null);
      return;
    }
    function place() {
      if (!wrench.current || !popup.current) return;
      const anchor = wrench.current.getBoundingClientRect();
      const size = popup.current.getBoundingClientRect();
      const fitsBelow = anchor.bottom + GAP + size.height <= window.innerHeight - EDGE;
      setPosition({
        top: fitsBelow ? anchor.bottom + GAP : Math.max(EDGE, anchor.top - GAP - size.height),
        left: Math.max(EDGE, Math.min(anchor.left, window.innerWidth - size.width - EDGE)),
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    // The list arrives after the popup opens, and may no longer fit where it was placed.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    if (popup.current) observer?.observe(popup.current);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      observer?.disconnect();
    };
  }, [isOpen]);

  // Focus waits until the popup is placed, because a browser cannot focus something hidden.
  const isPlaced = position !== null;
  useEffect(() => {
    if (!isOpen || !isPlaced) return;
    const first = popup.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? popup.current)?.focus({ preventScroll: true });
  }, [isOpen, isPlaced]);

  useEffect(() => {
    if (!isOpen) return;

    function isInside(target: EventTarget | null): boolean {
      return (
        target instanceof Node &&
        Boolean(popup.current?.contains(target) || wrench.current?.contains(target))
      );
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // Escape closes only this popup. It must not also clear what is selected on the page.
      event.stopPropagation();
      close(true);
    }
    function onPointerDown(event: PointerEvent) {
      if (!isInside(event.target)) close(false);
    }
    function onFocusIn(event: FocusEvent) {
      if (!isInside(event.target)) close(false);
    }
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [isOpen, close]);

  const label = t("ingredients.change", { ingredient: ingredient.name });

  return (
    <>
      <button
        ref={wrench}
        type="button"
        className="ingredient__wrench"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? popupId : undefined}
        title={label}
        onClick={() => onOpenChange(!isOpen)}
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
          <path
            d="M15.5 3.5a5 5 0 0 0-4.7 6.7l-7.2 7.2a2.1 2.1 0 0 0 3 3l7.2-7.2a5 5 0 0 0 6.7-4.7l-.3-1.3-3 3-2.6-.7-.7-2.6 3-3z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {isOpen && (
        <div
          ref={popup}
          id={popupId}
          className="menu"
          role="dialog"
          aria-label={label}
          tabIndex={-1}
          style={
            position
              ? { top: position.top, left: position.left }
              : { visibility: "hidden", top: 0, left: 0 }
          }
        >
          <p className="menu__title">{ingredient.name}</p>
          {note && <p className="menu__note">{note}</p>}
          <p className="menu__goal">
            <label htmlFor={goalId}>{t("substitution.goalLabel")}</label>
            <select
              id={goalId}
              value={goal}
              onChange={(event) => onGoalChange(event.target.value as Goal)}
            >
              {GOALS.map((option) => (
                <option key={option} value={option}>
                  {translateKey(`substitution.goal.${option}`)}
                </option>
              ))}
            </select>
          </p>
          <h3 className="menu__heading">{t("ingredients.replacements")}</h3>
          <div className="menu__scroll">
            <SubstitutionList
              ingredient={ingredient}
              state={substitutions}
              nutrients={nutrients}
              goal={goal}
              serving={serving}
              onChoose={(edit) => {
                onChoose(edit);
                close(true);
              }}
              onRetry={onRetrySubstitutions}
            />
            <p className="menu__note menu__disclaimer">{t("allergens.disclaimer")}</p>
          </div>
          {isChanged && (
            <button
              type="button"
              className="button menu__action"
              onClick={() => {
                onPutBack();
                close(true);
              }}
            >
              {t("ingredients.putBack")}
            </button>
          )}
          {!isExcluded && (
            <button
              type="button"
              className="button menu__action"
              disabled={!canRemove}
              onClick={() => {
                onRemove();
                close(true);
              }}
            >
              {t("ingredients.remove")}
            </button>
          )}
          {!isExcluded && !canRemove && <p className="menu__note">{t("ingredients.lastOne")}</p>}
        </div>
      )}
    </>
  );
}
