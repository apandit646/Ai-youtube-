import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Clapperboard, Plus, RefreshCw, Save, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Job, Script, SettingsResponse } from "@/lib/types";
import { formatDate, LANGUAGE_LABELS } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { JobProgress } from "@/components/JobProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Alert, Skeleton } from "@/components/ui/misc";

const BACKGROUNDS = ["meadow", "sky", "night", "ocean", "forest", "farm", "classroom", "space", "garden", "beach"];
type SceneDraft = { description: string; lyric_text: string; duration_seconds: number; visual: { background?: string; characters?: string[]; objects?: string[]; mood?: string } };

export default function ScriptEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["script", id], queryFn: () => api<Script>(`/content/${id}`) });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const [title, setTitle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [seo, setSeo] = useState<Script["seo"]>({});
  const [scenes, setScenes] = useState<SceneDraft[]>([]);
  const [regenJob, setRegenJob] = useState<number | null>(null);
  const [renderJob, setRenderJob] = useState<{ job: number; project: number } | null>(null);
  const [instructions, setInstructions] = useState("");

  useEffect(() => {
    if (!q.data) return;
    setTitle(q.data.title);
    setLyrics(q.data.lyrics);
    setSeo(q.data.seo);
    setScenes(q.data.scenes.map((s) => ({ description: s.description, lyric_text: s.lyric_text, duration_seconds: s.duration_seconds, visual: s.visual })));
  }, [q.data]);

  const save = useMutation({
    mutationFn: (extra: Record<string, unknown> = {}) => api<Script>(`/content/${id}`, { method: "PUT", body: { title, lyrics, seo: { ...seo, hashtags: seo.hashtags ?? [], keywords: seo.keywords ?? [] }, scenes, ...extra } }),
    onSuccess: (s) => { qc.setQueryData(["script", id], s); toast.success(s.originality_report.passed ? "Saved — checks passed" : "Saved — checks failing, see report"); },
    onError: (e: Error) => toast.error(e.message),
  });
  const approve = useMutation({
    mutationFn: (approved: boolean) => api<Script>(`/content/${id}`, { method: "PUT", body: { approved } }),
    onSuccess: (s) => { qc.setQueryData(["script", id], s); qc.invalidateQueries({ queryKey: ["scripts"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const regen = useMutation({
    mutationFn: (section: string) => api<Job>(`/content/${id}/regenerate`, { method: "POST", body: { section, instructions } }),
    onSuccess: (j) => setRegenJob(j.id),
    onError: (e: Error) => toast.error(e.message),
  });
  const createVideo = useMutation({
    mutationFn: () => api<{ project: { id: number }; job: Job }>("/videos", { method: "POST", body: { script_id: Number(id), render: true } }),
    onSuccess: (r) => { setRenderJob({ job: r.job.id, project: r.project.id }); toast.success("Rendering started"); },
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({
    mutationFn: () => api(`/content/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Script deleted"); qc.invalidateQueries({ queryKey: ["scripts"] }); navigate("/content?tab=scripts"); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError || !q.data) return <Alert variant="error" title="Script not found">{(q.error as Error)?.message}</Alert>;
  const s = q.data;
  const report = s.originality_report;
  const aiConfigured = settings.data?.providers.some((p) => p.configured);
  const updateScene = (i: number, patch: Partial<SceneDraft>) => setScenes(scenes.map((sc, j) => (j === i ? { ...sc, ...patch } : sc)));

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2"><Link to="/content"><ArrowLeft />Content Studio</Link></Button>
      <PageHeader title={s.title} description={`${LANGUAGE_LABELS[s.language]} · ${s.video_format === "short" ? "Short 9:16" : "Long-form 16:9"} · theme ${s.theme} · ages ${s.target_age}`}
        actions={<>
          <Button variant="outline" onClick={() => save.mutate({})} loading={save.isPending}><Save />Save</Button>
          {s.approved ? <Button variant="outline" onClick={() => approve.mutate(false)}>Unapprove</Button> : <Button variant="accent" onClick={() => approve.mutate(true)} disabled={!report.passed}><CheckCircle2 />Approve</Button>}
          <Button onClick={() => createVideo.mutate()} loading={createVideo.isPending} disabled={!report.passed}><Clapperboard />Create video</Button>
        </>} />

      <div className="mb-4 flex flex-wrap gap-2">
        {s.is_fallback ? <Badge variant="warning">Local fallback template — not AI generated</Badge> : <Badge>Generated by {s.provider} · {s.model}</Badge>}
        {s.approved && <Badge variant="success">Approved</Badge>}
        {s.safety_flags.map((f) => <Badge key={f} variant="destructive">{f}</Badge>)}
        <span className="text-xs text-muted-foreground">Updated {formatDate(s.updated_at)}</span>
      </div>
      {renderJob && <div className="mb-4 grid gap-2"><JobProgress jobId={renderJob.job} invalidate={[["videos"]]} /><Button variant="outline" size="sm" asChild className="justify-self-start"><Link to={`/videos?open=${renderJob.project}`}>Open in Video Library</Link></Button></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="grid content-start gap-6 lg:col-span-2">
          <Card>
            <CardHeader className="flex-row items-center justify-between"><CardTitle>Lyrics</CardTitle>
              <Button size="sm" variant="outline" disabled={!aiConfigured} loading={regen.isPending} onClick={() => regen.mutate("lyrics")}><RefreshCw />Regenerate</Button></CardHeader>
            <CardContent className="grid gap-3">
              <Field label="Title" htmlFor="t"><Input id="t" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} /></Field>
              <Textarea aria-label="Lyrics" className="min-h-[260px] font-medium leading-7" value={lyrics} onChange={(e) => setLyrics(e.target.value)} />
              <p className="text-xs text-muted-foreground">One line per row. Edits re-run the originality checks and reset approval.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between"><div><CardTitle>Storyboard</CardTitle><CardDescription>{scenes.length} scenes · {scenes.reduce((a, b) => a + Number(b.duration_seconds), 0).toFixed(0)}s planned</CardDescription></div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={!aiConfigured} onClick={() => regen.mutate("storyboard")}><RefreshCw />Regenerate</Button>
                <Button size="sm" variant="outline" disabled={scenes.length >= 20} onClick={() => setScenes([...scenes, { description: "New scene", lyric_text: "", duration_seconds: 5, visual: { background: "meadow", characters: [], objects: [], mood: "happy" } }])}><Plus />Scene</Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3">
              {scenes.map((sc, i) => (
                <div key={i} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-6">
                  <div className="flex items-center gap-2 sm:col-span-6"><Badge variant="secondary">Scene {i + 1}</Badge>
                    <Button size="icon" variant="ghost" className="ml-auto h-7 w-7" aria-label={`Remove scene ${i + 1}`} disabled={scenes.length <= 1} onClick={() => setScenes(scenes.filter((_, j) => j !== i))}><Trash2 /></Button></div>
                  <Field label="Description" htmlFor={`d${i}`} className="sm:col-span-3"><Input id={`d${i}`} value={sc.description} onChange={(e) => updateScene(i, { description: e.target.value })} /></Field>
                  <Field label="Seconds" htmlFor={`s${i}`}><Input id={`s${i}`} type="number" min={2} max={30} step={0.5} value={sc.duration_seconds} onChange={(e) => updateScene(i, { duration_seconds: Number(e.target.value) })} /></Field>
                  <Field label="Background" htmlFor={`b${i}`} className="sm:col-span-2"><Select id={`b${i}`} value={sc.visual.background ?? "meadow"} onChange={(e) => updateScene(i, { visual: { ...sc.visual, background: e.target.value } })}>{BACKGROUNDS.map((b) => <option key={b}>{b}</option>)}</Select></Field>
                  <Field label="On-screen lyrics" htmlFor={`l${i}`} className="sm:col-span-3"><Textarea id={`l${i}`} className="min-h-[60px]" value={sc.lyric_text} onChange={(e) => updateScene(i, { lyric_text: e.target.value })} /></Field>
                  <Field label="Characters" htmlFor={`c${i}`} className="sm:col-span-3" hint="cat, dog, elephant, rabbit, bird, fish, cow, lion, monkey, duck, frog, bear, owl, child, sun, moon">
                    <Input id={`c${i}`} value={(sc.visual.characters ?? []).join(", ")} onChange={(e) => updateScene(i, { visual: { ...sc.visual, characters: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} /></Field>
                  <Field label="Objects" htmlFor={`o${i}`} className="sm:col-span-6" hint="apple, balloon, star… or number:3, letter:A, shape:circle, color:red">
                    <Input id={`o${i}`} value={(sc.visual.objects ?? []).join(", ")} onChange={(e) => updateScene(i, { visual: { ...sc.visual, objects: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} /></Field>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="grid content-start gap-6">
          <Card>
            <CardHeader><CardTitle>Originality & safety</CardTitle></CardHeader>
            <CardContent className="grid gap-2 text-sm">
              {report.passed ? <Alert title="All blocking checks passed" /> : <Alert variant="error" title="Checks failing — cannot render until fixed" />}
              <ul className="grid gap-1.5">
                {(report.checks ?? []).map((c) => (
                  <li key={c.name} className="flex gap-2">{c.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <XCircle className={`mt-0.5 h-4 w-4 shrink-0 ${c.blocking === false ? "text-amber-600" : "text-red-600"}`} />}
                    <span><span className="font-medium">{c.name.replace(/_/g, " ")}</span><br /><span className="text-xs text-muted-foreground">{c.detail}</span></span></li>
                ))}
              </ul>
              {s.review && (
                <div className="mt-2 rounded-lg bg-muted p-3">
                  {s.review.skipped ? <p className="text-xs text-muted-foreground">Cross-model review skipped: {s.review.reason}</p> : (
                    <>
                      <p className="font-medium">Independent review by {s.review.provider}: {s.review.approved ? "approved" : "not approved"} · originality {s.review.originality_score}/10</p>
                      {(s.review.issues ?? []).length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{s.review.issues!.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                      {(s.review.suggestions ?? []).length > 0 && <p className="mt-1 text-xs text-muted-foreground">Suggestions: {s.review.suggestions!.join("; ")}</p>}
                    </>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between"><CardTitle>Metadata & SEO</CardTitle>
              <Button size="sm" variant="outline" disabled={!aiConfigured} onClick={() => regen.mutate("metadata")}><RefreshCw />Regenerate</Button></CardHeader>
            <CardContent className="grid gap-3">
              <Field label="YouTube title" htmlFor="st"><Input id="st" maxLength={100} value={seo.title ?? ""} onChange={(e) => setSeo({ ...seo, title: e.target.value })} /></Field>
              <Field label="Description" htmlFor="sd"><Textarea id="sd" className="min-h-[120px]" value={seo.description ?? ""} onChange={(e) => setSeo({ ...seo, description: e.target.value })} /></Field>
              <Field label="Hashtags (max 5)" htmlFor="sh"><Input id="sh" value={(seo.hashtags ?? []).join(" ")} onChange={(e) => setSeo({ ...seo, hashtags: e.target.value.split(/\s+/).filter(Boolean) })} /></Field>
              <Field label="Keywords / tags" htmlFor="sk"><Input id="sk" value={(seo.keywords ?? []).join(", ")} onChange={(e) => setSeo({ ...seo, keywords: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
              <Field label="Thumbnail text" htmlFor="stt"><Input id="stt" maxLength={40} value={seo.thumbnail_text ?? ""} onChange={(e) => setSeo({ ...seo, thumbnail_text: e.target.value })} /></Field>
              <p className="text-xs text-muted-foreground">Uploads are marked "Made for Kids" by default. No ranking or view guarantees.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Regeneration notes</CardTitle><CardDescription>Optional guidance sent with “Regenerate”.</CardDescription></CardHeader>
            <CardContent className="grid gap-3">
              <Textarea aria-label="Regeneration instructions" maxLength={500} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="e.g. make the chorus shorter and add counting to five" />
              {regenJob && <JobProgress jobId={regenJob} compact invalidate={[["script", id ?? ""]]} />}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Details</CardTitle></CardHeader>
            <CardContent className="grid gap-2 text-sm">
              <p><span className="text-muted-foreground">Objective:</span> {s.objective}</p>
              <p><span className="text-muted-foreground">Story:</span> {s.story_concept}</p>
              <p><span className="text-muted-foreground">Audio:</span> {s.audio_instructions || "—"}</p>
              <details><summary className="cursor-pointer text-muted-foreground">Prompt used</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">{s.prompt}</pre></details>
              <Button variant="ghost" size="sm" className="justify-self-start text-red-700" onClick={() => { if (confirm("Delete this script?")) del.mutate(); }}><Trash2 />Delete script</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
