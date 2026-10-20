import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress, Alert } from "@/components/ui/misc";
import { StatusBadge } from "./StatusBadge";
import { useJob } from "@/hooks/useJob";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { formatDate } from "@/lib/utils";

export function JobProgress({ jobId, invalidate = [], compact = false }: { jobId: number; invalidate?: readonly (readonly unknown[])[]; compact?: boolean }) {
  const { job, isTerminal } = useJob(jobId, invalidate);
  if (!job) return <p className="text-sm text-muted-foreground">Loading job #{jobId}…</p>;
  const cancel = async () => {
    try {
      await api(`/jobs/${job.id}/cancel`, { method: "POST" });
      toast.info("Cancellation requested");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const retry = async () => {
    try {
      await api(`/jobs/${job.id}/retry`, { method: "POST" });
      toast.success("Job re-queued");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <div className="grid gap-3 rounded-lg border bg-muted/40 p-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Job #{job.id}</span>
        <span className="text-muted-foreground">{job.kind.replace("_", " ")}</span>
        <StatusBadge status={job.status} />
        {job.step && !isTerminal && <span className="text-muted-foreground">· {job.step.replace(/_/g, " ").toLowerCase()}</span>}
        <span className="ml-auto flex gap-2">
          {!isTerminal && <Button size="sm" variant="outline" onClick={cancel} disabled={job.cancel_requested}>{job.cancel_requested ? "Cancelling…" : "Cancel"}</Button>}
          {(job.status === "FAILED" || job.status === "CANCELLED") && <Button size="sm" variant="outline" onClick={retry}>Retry</Button>}
        </span>
      </div>
      {!isTerminal && <Progress value={job.status === "QUEUED" ? 0 : job.progress} />}
      {job.status === "QUEUED" && job.attempts > 0 && <p className="text-xs text-muted-foreground">Retry scheduled for {formatDate(job.run_after)} (attempt {job.attempts + 1} of {job.max_attempts}).</p>}
      {job.status === "QUEUED" && job.attempts === 0 && <p className="text-xs text-muted-foreground">Waiting for the worker to pick this up…</p>}
      {!compact && job.steps.length > 0 && (
        <ol className="grid gap-1 text-sm">
          {job.steps.map((s, i) => (
            <li key={i} className="flex items-start gap-2">
              {s.status === "succeeded" ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : s.status === "failed" ? <XCircle className="mt-0.5 h-4 w-4 text-red-600" /> : s.status === "running" ? <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-primary" /> : <CircleDashed className="mt-0.5 h-4 w-4 text-muted-foreground" />}
              <span className="capitalize">{s.step.replace(/_/g, " ").toLowerCase()}</span>
              <span className="text-xs text-muted-foreground">{s.status}{s.error ? ` — ${s.error}` : ""}</span>
            </li>
          ))}
        </ol>
      )}
      {job.error && job.status === "FAILED" && <Alert variant="error" title="Job failed">{job.error}</Alert>}
    </div>
  );
}
