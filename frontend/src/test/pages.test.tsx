import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider } from "@/lib/auth";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import { mockApi, renderWithProviders } from "./utils";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => localStorage.clear());

describe("Login", () => {
  it("offers owner registration on first run and validates password length", async () => {
    const fetchFn = mockApi({
      "GET /auth/setup-status": { needs_owner: true },
      "POST /auth/register": { access_token: "t", expires_in: 100 },
      "GET /auth/me": { id: 1, email: "a@b.co", display_name: "A" },
    });
    renderWithProviders(<AuthProvider><Login /></AuthProvider>);
    expect(await screen.findByText("Create the owner account")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText(/at least 10 characters/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Password"), "-and-longer");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(localStorage.getItem("rhymepilot.token")).toBe("t"));
    expect(fetchFn.mock.calls.some(([u]) => String(u).endsWith("/auth/register"))).toBe(true);
  });

  it("shows sign-in when an owner exists and surfaces errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/auth/setup-status")) return { ok: true, status: 200, json: async () => ({ needs_owner: false }) };
      return { ok: false, status: 401, statusText: "Unauthorized", json: async () => ({ detail: "Incorrect email or password" }) };
    }));
    renderWithProviders(<AuthProvider><Login /></AuthProvider>);
    expect(await screen.findByText("Sign in to RhymePilot AI")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpass");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Incorrect email or password")).toBeInTheDocument();
  });
});

const dashboard = {
  channel: { connected: false, title: null, subscriber_count: null, video_count: null },
  analytics: { has_data: false, totals: {}, last_collected_at: null, unavailable: ["impressions"] },
  jobs: { queued: 1, running: 0, failed_last_7_days: 2, succeeded: 5 },
  active_jobs: [], projects_by_status: {}, recent_videos: [], upcoming: [],
  automation: { enabled: false, paused: true, dry_run: true, auto_publish: false, private_test_passed_at: null },
  connections: { ai_providers: [{ provider: "grok", label: "Grok (xAI)", configured: false, model: null, key_source: null, key_hint: null }], ai_configured: false, youtube_oauth_configured: false, youtube_connected: false, worker_alive: true, worker_heartbeat: null },
};
const settings = { settings: { setup_completed: true, paused: true }, providers: [], tasks: [], youtube: {}, media: {} };

describe("Dashboard", () => {
  it("renders real data with explicit empty states and resumes automation", async () => {
    const fetchFn = mockApi({ "GET /dashboard": dashboard, "GET /settings": settings, "POST /automation/resume": { paused: false } });
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText("Automation is paused")).toBeInTheDocument();
    expect(screen.getByText("No analytics collected yet")).toBeInTheDocument();
    expect(screen.getByText("No videos yet")).toBeInTheDocument();
    expect(screen.getByText("0 / 1")).toBeInTheDocument();
    expect(screen.getByText(/No AI model configured/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run pipeline now/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Resume automation/ }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([u, i]) => String(u).endsWith("/automation/resume") && i?.method === "POST")).toBe(true));
  });
});
