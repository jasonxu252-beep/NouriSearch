import type { Mark } from "../api/client";

interface Props {
  /** Percent of the Daily Value in this serving. Null when the amount is unknown. */
  percent: number | null;
  /** Where the FDA's "high" line sits, as a percent. */
  highAt: number;
  mark: Mark;
  /** The percent is a floor, so the bar trails off rather than ending. */
  isLowerBound: boolean;
}

/**
 * A meter from 0 to 100% of the Daily Value. The printed value beside it carries the number, so the
 * meter itself is decorative to assistive technology. An unknown value draws an empty dashed track,
 * so it can never read as a very short bar.
 */
export function DailyValueMeter({ percent, highAt, mark, isLowerBound }: Props) {
  const state = percent === null ? "unknown" : isLowerBound ? "lower-bound" : "value";
  const width = percent === null ? 0 : Math.min(percent, 100);
  return (
    <span
      className={`meter meter--${state} ${mark === "exclamation" ? "meter--high" : ""}`}
      data-state={state}
      aria-hidden="true"
    >
      <span className="meter__track">
        {percent !== null && (
          <span className="meter__fill" data-width={width} style={{ width: `${width}%` }} />
        )}
      </span>
      <span className="meter__tick" style={{ left: `${highAt}%` }} />
      {percent !== null && percent > 100 && <span className="meter__overflow">{"›"}</span>}
    </span>
  );
}
