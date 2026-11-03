/** Number formatting, with the rule that a rounded figure must not contradict the mark beside it. */

const HIGH_LINE = 20;

function round(value: number, maximumFractionDigits: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(value);
}

/** Enough digits to read the value, and no false precision on large ones. */
export function formatNumber(value: number): string {
  const size = Math.abs(value);
  if (size === 0) return "0";
  if (size >= 100) return round(value, 0);
  if (size >= 10) return round(value, 1);
  if (size >= 1) return round(value, 2);
  if (size >= 0.01) return round(value, 2);
  return `<${round(0.01, 2)}`;
}

export function formatAmount(value: number, unit: string): string {
  return `${formatNumber(value)} ${unit}`;
}

export function formatGrams(value: number): string {
  return round(value, value >= 100 ? 0 : 1);
}

/**
 * Whole percents, except that 19.6% must not read as 20%, because that is the line the FDA treats
 * as high and the mark beside it would say otherwise.
 */
export function formatPercent(value: number): string {
  if (value === 0) return "0%";
  if (value > 0 && value < 1) return "<1%";
  const rounded = Math.round(value);
  if (value < HIGH_LINE && rounded >= HIGH_LINE) {
    return `${(Math.floor(value * 10) / 10).toFixed(1)}%`;
  }
  return `${round(rounded, 0)}%`;
}

export function formatShare(share: number): string {
  if (share > 0 && share < 0.01) return "<1%";
  return `${Math.round(share * 100)}%`;
}

/** For a nutrient's name mid-sentence: "known sodium", "known vitamin C". */
export function inSentence(name: string): string {
  return name.charAt(0).toLowerCase() + name.slice(1);
}

export function formatDelta(value: number, unit: string): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatAmount(Math.abs(value), unit)}`;
}
