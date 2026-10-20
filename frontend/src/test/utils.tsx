import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export function renderWithProviders(ui: React.ReactElement, route = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{ui}</MemoryRouter></QueryClientProvider>);
}

/** Route-based fetch mock: keys are "METHOD /path" (path without /api/v1 and query). */
export function mockApi(routes: Record<string, unknown | ((body: any) => unknown)>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/v1", "");
    const key = `${init.method ?? "GET"} ${path}`;
    if (!(key in routes)) return { ok: false, status: 404, statusText: "Not Found", json: async () => ({ detail: `no mock for ${key}` }) };
    const handler = routes[key];
    const body = typeof handler === "function" ? (handler as (b: unknown) => unknown)(init.body ? JSON.parse(init.body as string) : undefined) : handler;
    return { ok: true, status: 200, statusText: "OK", json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
