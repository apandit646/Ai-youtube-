import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusBadge } from "@/components/StatusBadge";
import { JobProgress } from "@/components/JobProgress";
import { mockApi, renderWithProviders } from "./utils";

afterEach(() => vi.unstubAllGlobals());

const job = (over = {}) => ({
  id: 7, kind: "render", status: "RUNNING", project_id: 1, payload: {}, result: null, step: "RENDERING", progress: 0.4,
  steps: [{ step: "GENERATING_MEDIA", status: "succeeded", started_at: "" }, { step: "RENDERING", status: "running", started_at: "" }],
  error: null, attempts: 1, max_attempts: 3, cancel_requested: false, run_after: "", started_at: null, finished_at: null, created_at: "", ...over,
});

describe("StatusBadge", () => {
  it("renders human labels", () => {
    renderWithProviders(<StatusBadge status="UPLOADED_PRIVATE" />);
    expect(screen.getByText("Uploaded (private)")).toBeInTheDocument();
  });
});

describe("JobProgress", () => {
  it("shows steps and lets the user cancel a running job", async () => {
    const fetchFn = mockApi({ "GET /jobs/7": job(), "POST /jobs/7/cancel": job({ cancel_requested: true }) });
    renderWithProviders(<JobProgress jobId={7} />);
    expect(await screen.findByText("Job #7")).toBeInTheDocument();
    expect(screen.getByText(/generating media/i)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([u, i]) => String(u).endsWith("/jobs/7/cancel") && i?.method === "POST")).toBe(true));
  });

  it("shows the error and a retry button for failed jobs", async () => {
    mockApi({ "GET /jobs/7": job({ status: "FAILED", error: "FFmpeg failed: boom", steps: [] }) });
    renderWithProviders(<JobProgress jobId={7} />);
    expect(await screen.findByText("FFmpeg failed: boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
