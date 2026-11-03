import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import type { Ingredient } from "../api/client";
import { t } from "../i18n";

interface Props {
  ingredient: Ingredient;
  isExcluded: boolean;
  isOpen: boolean;
  /** A dish needs at least one ingredient, so the last one cannot leave. */
  canRemove: boolean;
  /** What this ingredient matters for, to help decide. */
  note: string | null;
  onOpenChange: (open: boolean) => void;
  onRemove: () => void;
  onPutBack: () => void;
}

const GAP = 4;
const EDGE = 8;

/**
 * The wrench from the owner's sketch, and the small popup it opens. The popup is positioned against
 * the window, because the ingredient list scrolls and would otherwise cut it off.
 */
export function IngredientMenu({
  ingredient,
  isExcluded,
  isOpen,
  canRemove,
  note,
  onOpenChange,
  onRemove,
  onPutBack,
}: Props) {
  const popupId = useId();
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
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [isOpen]);

  // Focus waits until the popup is placed, because a browser cannot focus something hidden.
  const isPlaced = position !== null;
  useEffect(() => {
    if (!isOpen || !isPlaced) return;
    const first = popup.current?.querySelector<HTMLButtonElement>("button:not(:disabled)");
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
          <h3 className="menu__heading">{t("ingredients.replacements")}</h3>
          <p className="menu__note">{t("ingredients.noReplacements")}</p>
          {isExcluded ? (
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
          ) : (
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
