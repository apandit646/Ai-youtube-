import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, apiUrl, setUnauthorizedHandler, tokenStore } from "@/lib/api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: status < 400, status, statusText: "x", json: () => Promise.resolve(body) });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("sends the bearer token and JSON body", async () => {
    tokenStore.set("tok123");
    const fetchFn = mockFetch(200, { ok: true });
    await api("/settings", { method: "PUT", body: { a: 1 } });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/v1/settings");
    expect(init.headers.Authorization).toBe("Bearer tok123");
    expect(init.body).toBe('{"a":1}');
  });

  it("builds query strings and skips empty values", () => {
    expect(apiUrl("/videos", { page: 2, status: "", q: undefined, ok: true })).toBe("/api/v1/videos?page=2&ok=true");
  });

  it("raises ApiError with validation details", async () => {
    mockFetch(422, { error: "validation_error", detail: "Invalid request", details: { errors: [{ loc: ["body", "password"], msg: "too short" }] } });
    await expect(api("/auth/register", { method: "POST", body: {} })).rejects.toMatchObject({ status: 422, code: "validation_error", message: "Invalid request: password too short" });
  });

  it("calls the unauthorized handler on 401 when logged in", async () => {
    tokenStore.set("expired");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(401, { detail: "Invalid or expired token" });
    await expect(api("/dashboard")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalled();
  });

  it("reports network failures clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api("/health")).rejects.toMatchObject({ code: "network_error" });
  });
});
