import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CalendarPlus, Clapperboard, Download, ExternalLink, FlaskConical, ImageOff, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Page, Project, ProjectDetail, PublishingJob } from "@/lib/types";
import { formatDate, formatDuration, formatNumber, LANGUAGE_LABELS } from "@/lib/utils";
import { useMediaUrl } from "@/hooks/useMediaToken";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { JobProgress } from "@/components/JobProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Alert, EmptyState, Pager, Skeleton, Table, Td, Th } from "@/components/ui/misc";
import { Switch } from "@/components/ui/switch";

const STATUSES = ["PENDING", "SCRIPTING", "GENERATING_MEDIA", "RENDERING", "VALIDATING", "READY", "UPLOADING", "SCHEDULED", "PUBLISHED", "FAILED", "CANCELLED"];
const BUSY = new Set(["SCRIPTING", "RESEARCHING", "GENERATING_MEDIA", "RENDERING", "VALIDATING", "UPLOADING"]);

function Thumb({ project }: { project: Project }) {
  const url = useMediaUrl(project.id, project.has_thumbnail);
  const src = url("thumbnail");
  return (
    <div className="relative aspect-video overflow-hidden rounded-t-lg bg-muted">
      {project.has_thumbnail && src ? <img src={src} alt="" className="h-full w-full object-cover" loading="lazy" /> : (
        <div className="grid h-full place-items-center text-muted-foreground">{BUSY.has(project.status) ? <RefreshCw className="h-6 w-6 animate-spin" /> : <ImageOff className="h-6 w-6" />}</div>
      )}
      <Badge variant="secondary" className="absolute left-2 top-2 bg-white/90">{project.video_format === "short" ? "Short 9:16" : "Long 16:9"}</Badge>
    </div>
  );
}

export default function Videos() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [format, setFormat] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["videos", status, format, page],
    queryFn: () => api<Page<Project>>("/videos", { query: { status, video_format: format, page, page_size: 12 } }),
    refetchInterval: (query) => (query.state.data?.items.some((p) => BUSY.has(p.status)) ? 3000 : false),
  });
  const openId = params.get("open");

  return (
    <>
      <PageHeader title="Video Library" description="Every generated video with its pipeline status, validation results and publication state."
        actions={<Button asChild><Link to="/content"><Clapperboard />New rhyme</Link></Button>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Select aria-label="Status filter" className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").toLowerCase()}</option>)}
        </Select>
        <Select aria-label="Format filter" className="w-40" value={format} onChange={(e) => { setFormat(e.target.value); setPage(1); }}>
          <option value="">All formats</option><option value="short">Shorts</option><option value="long">Long-form</option>
        </Select>
      </div>
      {q.isLoading ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-64" />)}</div> :
        q.data?.total === 0 ? <EmptyState icon={Clapperboard} title="No videos yet" description="Generate a rhyme with “Render video automatically” or create a video from a script." /> : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {q.data?.items.map((p) => (
              <Card key={p.id} className="cursor-pointer overflow-hidden transition-shadow hover:shadow-md" onClick={() => setParams({ open: String(p.id) })} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") setParams({ open: String(p.id) }); }} aria-label={`Open ${p.title}`}>
                <Thumb project={p} />
                <CardContent className="grid gap-2 p-4">
                  <p className="line-clamp-2 font-medium">{p.title}</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <StatusBadge status={p.status} />
                    {p.publication && <StatusBadge status={p.publication.status} />}
                    <span>{p.language ? LANGUAGE_LABELS[p.language] : "—"}</span>·<span>{formatDuration(p.duration_seconds)}</span>
                  </div>
                  {p.error && <p className="line-clamp-2 text-xs text-red-700">{p.error}</p>}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      {q.data && <Pager page={page} pageSize={12} total={q.data.total} onPage={setPage} />}
      {openId && <VideoDetail id={Number(openId)} onClose={() => setParams({})} />}
    </>
  );
}

function VideoDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["video", id],
    queryFn: () => api<ProjectDetail>(`/videos/${id}`),
    refetchInterval: (query) => (query.state.data && (BUSY.has(query.state.data.status) || query.state.data.publishing_jobs.some((j) => ["QUEUED", "UPLOADING"].includes(j.status))) ? 2500 : false),
  });
  const media = useMediaUrl(id, !!q.data?.has_video || !!q.data?.has_thumbnail);
  const [jobId, setJobId] = useState<number | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");
  const [kids, setKids] = useState(true);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["video", id] }); qc.invalidateQueries({ queryKey: ["videos"] }); qc.invalidateQueries({ queryKey: ["calendar"] }); };
  const onErr = (e: Error) => toast.error(e.message);

  const render = useMutation({ mutationFn: () => api<{ id: number }>(`/videos/${id}/render`, { method: "POST" }), onSuccess: (j) => { setJobId(j.id); refresh(); }, onError: onErr });
  const retry = useMutation({ mutationFn: () => api<{ job: { id: number } | null }>(`/videos/${id}/retry`, { method: "POST" }), onSuccess: (r) => { if (r.job) setJobId(r.job.id); toast.success("Retry started"); refresh(); }, onError: onErr });
  const delMedia = useMutation({ mutationFn: () => api<{ deleted_bytes: number }>(`/videos/${id}/media`, { method: "DELETE", query: { confirm: true } }), onSuccess: (r) => { toast.success(`Deleted ${formatNumber(r.deleted_bytes / 1048576, 1)} MB of local media`); refresh(); }, onError: onErr });
  const testUpload = useMutation({ mutationFn: () => api<PublishingJob>(`/videos/${id}/upload`, { method: "POST", body: { test: true, made_for_kids: kids } }), onSuccess: (pj) => { toast.success(pj.dry_run ? "Dry-run test queued (no upload will happen)" : "Private test upload queued"); if (pj.job_id) setJobId(pj.job_id); refresh(); }, onError: onErr });
  const schedule = useMutation({ mutationFn: () => api<PublishingJob>(`/videos/${id}/schedule`, { method: "POST", body: { publish_at: scheduleAt ? new Date(scheduleAt).toISOString() : undefined, made_for_kids: kids } }), onSuccess: (pj) => { toast.success(`Scheduled for ${formatDate(pj.publish_at)}${pj.dry_run ? " (dry run)" : ""}`); if (pj.job_id) setJobId(pj.job_id); refresh(); }, onError: onErr });

  const p = q.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide>
        {!p ? <><DialogTitle className="sr-only">Loading video</DialogTitle><Skeleton className="h-96" /></> : (
          <>
            <div>
              <DialogTitle>{p.title}</DialogTitle>
              <DialogDescription className="mt-1 flex flex-wrap items-center gap-2"><StatusBadge status={p.status} /><span>{p.width}×{p.height} · {p.fps} fps · {formatDuration(p.duration_seconds)} · {p.file_size_bytes ? `${formatNumber(p.file_size_bytes / 1048576, 1)} MB` : "no file"}</span></DialogDescription>
            </div>
            <div className="grid gap-5 md:grid-cols-5">
              <div className="md:col-span-2">
                {p.has_video && media("video") ? (
                  <video key={media("video")} src={media("video")} controls poster={p.has_thumbnail ? media("thumbnail") : undefined} className={`w-full rounded-lg bg-black ${p.video_format === "short" ? "aspect-[9/16]" : "aspect-video"}`} />
                ) : <div className="grid aspect-[9/16] place-items-center rounded-lg bg-muted text-sm text-muted-foreground">{BUSY.has(p.status) ? "Rendering…" : "No rendered video"}</div>}
                <div className="mt-3 flex flex-wrap gap-2">
                  {p.has_video && <Button size="sm" variant="outline" asChild><a href={media("video", true)}><Download />Video</a></Button>}
                  {p.has_thumbnail && <Button size="sm" variant="outline" asChild><a href={media("thumbnail", true)}><Download />Thumbnail</a></Button>}
                  {p.has_video && <Button size="sm" variant="outline" asChild><a href={media("subtitles", true)}><Download />SRT</a></Button>}
                </div>
              </div>
              <div className="grid content-start gap-4 md:col-span-3">
                {jobId && <JobProgress jobId={jobId} invalidate={[["video", id], ["videos"]]} />}
                {p.error && <Alert variant="error" title="Last error">{p.error}</Alert>}
                {p.quality_warnings.length > 0 && <Alert variant="warning" title="Placeholder-quality media">{p.quality_warnings.map((w) => <p key={w}>• {w}</p>)}</Alert>}

                <div className="flex flex-wrap gap-2">
                  {p.script_id && <Button size="sm" variant="outline" asChild><Link to={`/content/${p.script_id}`}>Edit script</Link></Button>}
                  {["READY", "PENDING"].includes(p.status) && p.script_id && <Button size="sm" variant="outline" loading={render.isPending} onClick={() => render.mutate()}><RefreshCw />Re-render</Button>}
                  {["FAILED", "CANCELLED"].includes(p.status) && <Button size="sm" loading={retry.isPending} onClick={() => retry.mutate()}><RotateCcw />Retry</Button>}
                  {p.has_video && !BUSY.has(p.status) && <Button size="sm" variant="ghost" className="text-red-700" onClick={() => { if (confirm("Delete local video, images and audio for this project? The script and any YouTube upload are kept.")) delMedia.mutate(); }}><Trash2 />Delete local media</Button>}
                </div>

                {p.status === "READY" && (
                  <div className="grid gap-3 rounded-lg border p-3">
                    <p className="font-medium">Publish</p>
                    <label className="flex items-center gap-2 text-sm"><Switch checked={kids} onCheckedChange={setKids} />Made for Kids (recommended for children's content)</label>
                    <div className="flex flex-wrap items-end gap-2">
                      <Button size="sm" variant="outline" loading={testUpload.isPending} onClick={() => testUpload.mutate()}><FlaskConical />Private test upload</Button>
                      <Field label="Publish at (your local time)" htmlFor="pat" hint="Leave empty to use the next free slot in your publishing window."><Input id="pat" type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} /></Field>
                      <Button size="sm" loading={schedule.isPending} onClick={() => schedule.mutate()}><CalendarPlus />Schedule</Button>
                    </div>
                    <p className="text-xs text-muted-foreground">Scheduling requires a successful private test upload (unless dry-run mode is on). Status is only shown as scheduled/published after YouTube confirms it.</p>
                  </div>
                )}

                {p.publishing_jobs.length > 0 && (
                  <div>
                    <p className="mb-1 text-sm font-medium">Uploads</p>
                    <Table>
                      <thead><tr><Th>Type</Th><Th>Status</Th><Th>Publish at</Th><Th>YouTube</Th></tr></thead>
                      <tbody>{p.publishing_jobs.map((j) => (
                        <tr key={j.id}>
                          <Td>{j.is_test_upload ? "Test" : "Publish"}{j.dry_run && <Badge variant="secondary" className="ml-1">dry run</Badge>}</Td>
                          <Td><StatusBadge status={j.status} />{j.status === "UPLOADING" && <span className="ml-1 text-xs">{Math.round(j.upload_progress * 100)}%</span>}{j.last_error && <p className="text-xs text-red-700">{j.last_error}</p>}</Td>
                          <Td className="text-xs">{formatDate(j.publish_at)}</Td>
                          <Td>{j.youtube_video_id ? <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`https://studio.youtube.com/video/${j.youtube_video_id}/edit`} target="_blank" rel="noreferrer">{j.youtube_video_id}<ExternalLink className="h-3 w-3" /></a> : "—"}</Td>
                        </tr>))}</tbody>
                    </Table>
                  </div>
                )}

                {p.validation.checks && (
                  <details>
                    <summary className="cursor-pointer text-sm font-medium">Technical validation {p.validation.passed ? "✓ passed" : "✗ failed"}</summary>
                    <ul className="mt-2 grid gap-1 text-xs">{p.validation.checks.map((c) => <li key={c.name}>{c.passed ? "✓" : "✗"} {c.name}: <span className="text-muted-foreground">{c.detail}</span></li>)}</ul>
                  </details>
                )}
                <details>
                  <summary className="cursor-pointer text-sm font-medium">Status history</summary>
                  <ol className="mt-2 grid gap-1 text-xs">{p.status_history.map((h, i) => <li key={i}>{formatDate(h.at)} — {h.from} → <b>{h.to}</b>{h.note ? ` (${h.note})` : ""}</li>)}</ol>
                </details>
                <details>
                  <summary className="cursor-pointer text-sm font-medium">Assets ({p.assets.length})</summary>
                  <ul className="mt-2 grid gap-1 text-xs">{p.assets.map((a) => <li key={a.id}>{a.kind} · {a.provider}{a.is_placeholder ? " · placeholder" : ""} · {formatNumber(a.size_bytes / 1024)} KB</li>)}</ul>
                </details>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
