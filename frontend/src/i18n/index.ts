/**
 * Interface text comes from translation files, and conclusions from translated templates. The API
 * sends message keys, never sentences. Milestone 7 adds more languages beside en.json.
 */

import en from "./en.json";

export type MessageKey = keyof typeof en;
export type MessageParams = Record<string, string | number>;

function interpolate(template: string, params: MessageParams): string {
  return template.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    name in params ? String(params[name]) : placeholder,
  );
}

export function t(key: MessageKey, params: MessageParams = {}): string {
  return interpolate(en[key], params);
}

/** For keys that arrive from the API or are built at runtime. An unknown key is shown as is. */
export function translateKey(key: string, params: MessageParams = {}): string {
  const template = (en as Record<string, string>)[key];
  return template === undefined ? key : interpolate(template, params);
}

export const messageCatalog: Readonly<Record<string, string>> = en;
