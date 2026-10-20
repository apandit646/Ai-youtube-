import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { PublishingJob, SettingsResponse } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Alert, EmptyState, Table, Td, Th } from "@/components/ui/misc";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLORS: Record<string, string> = {
  SCHEDULED: "bg-emerald-100 text-emerald-900 border-emerald-200", PUBLISHED: "bg-emerald-200 text-emerald-900 border-emerald-300",
  QUEUED: "bg-amber-100 text-amber-900 border-amber-200", UPLOADING: "bg-violet-100 text-violet-900 border-violet-200",
  FAILED: "bg-red-100 text-red-800 border-red-200", DRY_RUN: "bg-slate-100 text-slate-700 border-slate-200",
  CANCELLED: "bg-slate-50 text-slate-500 border-slate-200 line-through", UPLOADED_PRIVATE: "bg-sky-100 text-sky-900 border-sky-200",
};

function toLocalInput(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function CalendarPage() {
  const qc = useQueryClient();
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const gridStart = useMemo(() => { const d = new Date(month); const offset = (d.getDay() + 6) % 7; d.setDate(d.getDate() - offset); return d; }, [month]);
  const gridEnd = useMemo(() => { const d = new Date(gridStart); d.setDate(d.getDate() + 42); return d; }, [gridStart]);
  const cal = useQuery({ queryKey: ["calendar", gridStart.toISOString()], queryFn: () => api<{ items: PublishingJob[] }>("/publishing/calendar", { query: { start: gridStart.toISOString(), end: gridEnd.toISOString() } }) });
  const queue = useQuery({ queryKey: ["publishing-queue"], queryFn: () => api<PublishingJob[]>("/publishing/queue") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const nextSlot = useQuery({ queryKey: ["next-slot"], queryFn: () => api<{ publish_at: string; timezone: string }>("/publishing/next-slot"), retry: false });
  const [editing, setEditing] = useState<PublishingJob | null>(null);
  const [when, setWhen] = useState("");
  const refresh = () => { ["calendar", "publishing-queue", "next-slot", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); };

  const reschedule = useMutation({
    mutationFn: () => api(`/publishing/${editing!.id}`, { method: "PUT", body: { publish_at: new Date(when).toISOString() } }),
    onSuccess: () => { toast.success("Rescheduled"); setEditing(null); refresh(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => api(`/publishing/${id}/cancel`, { method: "POST" }),
    onSuccess: () => { toast.success("Upload cancelled"); setEditing(null); refresh(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const pause = useMutation({
    mutationFn: (p: boolean) => api<{ note?: string }>(`/automation/${p ? "pause" : "resume"}`, { method: "POST" }),
    onSuccess: (r, p) => { toast.success(p ? "Publishing paused" : "Publishing resumed", { description: r.note }); qc.invalidateQueries({ queryKey: ["settings"] }); refresh(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const paused = settings.data?.settings.paused;
  const byDay = new Map<string, PublishingJob[]>();
  cal.data?.items.forEach((j) => { const key = new Date(j.date ?? j.publish_at ?? j.created_at).toDateString(); byDay.set(key, [...(byDay.get(key) ?? []), j]); });
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(gridStart); d.setDate(d.getDate() + i); return d; });
  const failures = queue.data?.filter((j) => j.status === "FAILED") ?? [];

  return (
    <>
      <PageHeader title="Publishing Calendar" description={`Scheduled and attempted uploads. Times shown in your browser's time zone; publishing windows use ${settings.data?.settings.timezone ?? "your configured zone"}.`}
        actions={<Button variant={paused ? "default" : "outline"} loading={pause.isPending} onClick={() => pause.mutate(!paused)}>{paused ? <><Play />Resume scheduling</> : <><Pause />Pause scheduling</>}</Button>} />
      {paused && <Alert variant="warning" className="mb-4" title="Scheduling paused">Queued uploads were cancelled. Videos already scheduled on YouTube keep their time; change those in YouTube Studio.</Alert>}
      {settings.data?.settings.dry_run && <Alert className="mb-4" title="Dry-run mode">Uploads are validated and recorded but never sent to YouTube.</Alert>}

      <div className="grid gap-6 lg:grid-cols-4">
        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>{month.toLocaleString(undefined, { month: "long", year: "numeric" })}</CardTitle>
            <div className="flex gap-1">
              <Button size="icon" variant="outline" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft /></Button>
              <Button size="sm" variant="outline" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); }}>Today</Button>
              <Button size="icon" variant="outline" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight /></Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border bg-border text-xs">
              {WEEKDAYS.map((d) => <div key={d} className="bg-muted px-2 py-1.5 font-medium text-muted-foreground">{d}</div>)}
              {days.map((d) => {
                const items = byDay.get(d.toDateString()) ?? [];
                const today = d.toDateString() === new Date().toDateString();
                return (
                  <div key={d.toISOString()} className={cn("min-h-[92px] bg-card p-1.5", d.getMonth() !== month.getMonth() && "bg-muted/40 text-muted-foreground")}>
                    <span className={cn("inline-grid h-5 w-5 place-items-center rounded-full", today && "bg-primary text-white")}>{d.getDate()}</span>
                    <div className="mt-1 grid gap-1">
                      {items.map((j) => (
                        <button key={j.id} onClick={() => { setEditing(j); setWhen(toLocalInput(j.publish_at)); }} className={cn("truncate rounded border px-1.5 py-0.5 text-left", COLORS[j.status] ?? "bg-secondary")} title={`${j.project_title} — ${j.status}`}>
                          {j.publish_at ? new Date(j.publish_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""} {j.is_test_upload ? "🧪 " : ""}{j.project_title}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <div className="grid content-start gap-6">
          <Card>
            <CardHeader><CardTitle>Next free slot</CardTitle><CardDescription>Window {settings.data?.settings.publish_window_start_hour}:00–{settings.data?.settings.publish_window_end_hour}:00 · max {settings.data?.settings.max_uploads_per_day}/day</CardDescription></CardHeader>
            <CardContent className="text-sm">{nextSlot.data ? formatDate(nextSlot.data.publish_at) : nextSlot.isError ? (nextSlot.error as Error).message : "…"}
              <p className="mt-2 text-xs text-muted-foreground">Change the window and cap in <Link className="underline" to="/settings">Settings</Link>.</p></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Upload failures</CardTitle></CardHeader>
            <CardContent>
              {failures.length === 0 ? <p className="text-sm text-muted-foreground">No failed uploads.</p> : (
                <ul className="grid gap-2 text-sm">{failures.map((f) => (
                  <li key={f.id} className="rounded border border-red-200 bg-red-50 p-2"><Link className="font-medium hover:underline" to={`/videos?open=${f.project_id}`}>{f.title}</Link><p className="text-xs text-red-800">{f.last_error}</p></li>
                ))}</ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>Upload queue</CardTitle><CardDescription>Items waiting to be sent to YouTube.</CardDescription></CardHeader>
        <CardContent>
          {queue.data?.length === 0 ? <EmptyState title="Queue is empty" description="Schedule a READY video from the Video Library." /> : (
            <Table>
              <thead><tr><Th>Video</Th><Th>Status</Th><Th>Publish at</Th><Th>Attempts</Th><Th /></tr></thead>
              <tbody>{queue.data?.map((j) => (
                <tr key={j.id}><Td><Link className="hover:underline" to={`/videos?open=${j.project_id}`}>{j.title}</Link></Td><Td><StatusBadge status={j.status} /></Td><Td>{formatDate(j.publish_at)}</Td><Td>{j.attempts}</Td>
                  <Td className="text-right">{["QUEUED", "FAILED"].includes(j.status) && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.id)}>Cancel</Button>}</Td></tr>
              ))}</tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          {editing && (
            <>
              <DialogTitle>{editing.title}</DialogTitle>
              <DialogDescription className="flex items-center gap-2"><StatusBadge status={editing.status} />{editing.youtube_video_id && <span>YouTube ID {editing.youtube_video_id}</span>}</DialogDescription>
              {editing.last_error && <Alert variant={editing.status === "FAILED" ? "error" : "warning"}>{editing.last_error}</Alert>}
              {editing.status === "QUEUED" ? (
                <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); reschedule.mutate(); }}>
                  <Field label="New publish time (your local time)" htmlFor="when"><Input id="when" type="datetime-local" required value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
                  <div className="flex gap-2"><Button type="submit" loading={reschedule.isPending}>Save time</Button><Button type="button" variant="outline" onClick={() => cancel.mutate(editing.id)}>Cancel upload</Button></div>
                </form>
              ) : (
                <p className="text-sm text-muted-foreground">{editing.status === "SCHEDULED" ? "This video is already on YouTube with a scheduled publish time. Change it in YouTube Studio." : "This item can no longer be edited here."}</p>
              )}
              <Button variant="link" asChild className="justify-self-start px-0"><Link to={`/videos?open=${editing.project_id}`}>Open video</Link></Button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
