/** Typed fetch wrapper for the RhymePilot API. Secrets never reach the browser; only a short-lived JWT is stored. */

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "rhymepilot.token";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function apiUrl(path: string, query?: Query) {
  const url = new URL(`${BASE}/api/v1${path}`, window.location.origin);
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  return BASE ? url.toString() : url.pathname + url.search;
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let resp: Response;
  try {
    resp = await fetch(apiUrl(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the RhymePilot API. Is the backend running?");
  }
  if (resp.status === 204) return undefined as T;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 401 && token) onUnauthorized?.();
    const detail = typeof data.detail === "string" ? data.detail : resp.statusText || "Request failed";
    const errors = (data.details?.errors as { loc?: unknown[]; msg: string }[] | undefined) ?? [];
    const msg = errors.length ? `${detail}: ${errors.map((e) => `${(e.loc ?? []).slice(-1)[0] ?? ""} ${e.msg}`.trim()).join("; ")}` : detail;
    throw new ApiError(resp.status, data.error ?? "error", msg, data.details ?? {});
  }
  return data as T;
}
