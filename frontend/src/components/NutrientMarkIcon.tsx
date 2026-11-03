import type { Mark } from "../api/client";
import { t, type MessageKey } from "../i18n";

function markLabel(mark: Mark, partial: boolean): MessageKey {
  if (mark === "question" && partial) return "mark.partial";
  return `mark.${mark}`;
}

interface Props {
  mark: Mark;
  /** The value is a lower bound rather than entirely absent. */
  partial?: boolean;
}

/**
 * Shape and text carry the meaning, so color is never the only signal: a triangle reading "High",
 * a check in a circle, or a question mark in a circle.
 */
export function NutrientMarkIcon({ mark, partial = false }: Props) {
  const label = t(markLabel(mark, partial));
  return (
    <span className={`mark mark--${mark}`} data-mark={mark} title={label}>
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
        {mark === "exclamation" && (
          <>
            <path d="M10 2 19 18H1Z" fill="currentColor" />
            <path d="M9 7.5h2v5.5H9zM9 14.2h2v2H9z" fill="var(--mark-ink)" />
          </>
        )}
        {mark === "green" && (
          <>
            <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="m6 10.4 2.7 2.7L14 7.6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        )}
        {mark === "question" && (
          <>
            <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M7.6 7.8a2.5 2.5 0 1 1 3.7 2.2c-.9.5-1.3 1-1.3 2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
            <circle cx="10" cy="14.6" r="1" fill="currentColor" />
          </>
        )}
      </svg>
      {mark === "exclamation" ? (
        <span className="mark__label">{label}</span>
      ) : (
        <span className="visually-hidden">{label}</span>
      )}
    </span>
  );
}
