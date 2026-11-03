import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "../App";

export type Handler = (url: URL, request: Request) => unknown | Promise<unknown>;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Answers the app's requests from a route table, and records what was asked. */
export function stubApi(routes: Record<string, Handler>) {
  const requests: { method: string; path: string; body: unknown }[] = [];
  const fetchStub = vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    const body = input.method === "POST" ? await input.clone().json() : undefined;
    requests.push({ method: input.method, path: url.pathname, body });
    const handler = routes[`${input.method} ${url.pathname}`];
    if (!handler) return jsonResponse({ code: "not_found", message: "No route." }, 404);
    const result = await handler(url, input);
    return result instanceof Response ? result : jsonResponse(result);
  });
  vi.stubGlobal("fetch", fetchStub);
  return { requests };
}

export function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}
