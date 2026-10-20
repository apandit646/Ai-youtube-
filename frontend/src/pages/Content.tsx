import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Lightbulb, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Idea, Job, Page, ScriptSummary, SettingsResponse } from "@/lib/types";
import { formatDate, LANGUAGE_LABELS, THEMES } from "@/lib/utils";
import { useJob } from "@/hooks/useJob";
import { PageHeader } from "@/components/PageHeader";
import { JobProgress } from "@/components/JobProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Alert, EmptyState, Pager, Table, Td, Th } from "@/components/ui/misc";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function Content() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const s = settings.data?.settings;
  const [form, setForm] = useState({ topic: "", theme: "animals", language: "hi", video_format: "short", target_age: "2-5", duration_seconds: 45, style: "", preferred_provider: "", allow_fallback: true, auto_render: true, idea_id: null as number | null });
  useEffect(() => { if (s) setForm((f) => ({ ...f, language: s.default_language, video_format: s.default_format, target_age: s.default_target_age })); }, [s]);

  const [genJob, setGenJob] = useState<number | null>(null);
  const [ideasJob, setIdeasJob] = useState<number | null>(params.get("ideasJob") ? Number(params.get("ideasJob")) : null);
  const [tab, setTab] = useState(params.get("tab") ?? (params.get("ideasJob") ? "ideas" : "create"));
  const [page, setPage] = useState(1);
  const [ideaCount, setIdeaCount] = useState(5);

  const scripts = useQuery({ queryKey: ["scripts", page], queryFn: () => api<Page<ScriptSummary>>("/content", { query: { page, page_size: 15 } }) });
  const ideas = useQuery({ queryKey: ["ideas"], queryFn: () => api<Page<Idea>>("/content/ideas", { query: { status: "new", page_size: 30 } }) });
  const { job } = useJob(genJob, [["scripts"], ["videos"], ["dashboard"]]);

  const generate = useMutation({
    mutationFn: () => api<{ job: Job; project_id: number | null }>("/content/generate", { method: "POST", body: {
      ...form, preferred_provider: form.preferred_provider || undefined, duration_seconds: Number(form.duration_seconds), create_project: form.auto_render,
    } }),
    onSuccess: (r) => { setGenJob(r.job.id); toast.success(form.auto_render ? "Generating script and rendering video…" : "Generating script…"); },
    onError: (e: Error) => toast.error(e.message),
  });
  const genIdeas = useMutation({
    mutationFn: () => api<Job>("/content/ideas", { method: "POST", body: { count: ideaCount, language: form.language, video_format: form.video_format } }),
    onSuccess: (j) => { setIdeasJob(j.id); toast.success("Generating ideas…"); },
    onError: (e: Error) => toast.error(e.message),
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => api(`/content/ideas/${id}/dismiss`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ideas"] }),
  });

  const useIdea = (idea: Idea) => {
    setForm({ ...form, topic: idea.topic, theme: THEMES.includes(idea.theme) ? idea.theme : "general", language: idea.language, video_format: idea.video_format, target_age: idea.target_age, idea_id: idea.id });
    setTab("create");
    setParams({});
  };
  const aiConfigured = settings.data?.providers.some((p) => p.configured);

  return (
    <>
      <PageHeader title="Content Studio" description="Plan and generate original Hindi & English rhymes. Every script passes originality, safety and structure checks before it can become a video." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList><TabsTrigger value="create">Create</TabsTrigger><TabsTrigger value="ideas">Ideas</TabsTrigger><TabsTrigger value="scripts">Scripts</TabsTrigger></TabsList>

        <TabsContent value="create">
          <div className="grid gap-6 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader><CardTitle>New rhyme</CardTitle><CardDescription>Grok writes the brief; a second model reviews it when configured.</CardDescription></CardHeader>
              <CardContent>
                {settings.data && !aiConfigured && <Alert variant="warning" className="mb-4" title="No AI model configured">Generation will use deterministic local templates, clearly labelled as fallback. Add Grok, ChatGPT or Gemini in Settings.</Alert>}
                <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); generate.mutate(); }}>
                  <Field label="Topic" htmlFor="topic" hint={form.idea_id ? `From idea #${form.idea_id}` : "What is the rhyme about? e.g. 'A baby elephant learns to share'"}>
                    <Input id="topic" required minLength={2} maxLength={200} value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value, idea_id: null })} />
                  </Field>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Field label="Theme" htmlFor="theme"><Select id="theme" value={form.theme} onChange={(e) => setForm({ ...form, theme: e.target.value })}>{THEMES.map((t) => <option key={t} value={t}>{t}</option>)}</Select></Field>
                    <Field label="Language" htmlFor="lang"><Select id="lang" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}><option value="hi">Hindi</option><option value="en">English</option><option value="bilingual">Bilingual</option></Select></Field>
                    <Field label="Format" htmlFor="fmt"><Select id="fmt" value={form.video_format} onChange={(e) => setForm({ ...form, video_format: e.target.value, duration_seconds: e.target.value === "short" ? 45 : 180 })}><option value="short">Short · 9:16</option><option value="long">Long-form · 16:9</option></Select></Field>
                    <Field label="Target age" htmlFor="age"><Input id="age" pattern="\d{1,2}-\d{1,2}" value={form.target_age} onChange={(e) => setForm({ ...form, target_age: e.target.value })} /></Field>
                    <Field label="Duration (seconds)" htmlFor="dur"><Input id="dur" type="number" min={10} max={900} value={form.duration_seconds} onChange={(e) => setForm({ ...form, duration_seconds: Number(e.target.value) })} /></Field>
                    <Field label="Preferred model" htmlFor="prov"><Select id="prov" value={form.preferred_provider} onChange={(e) => setForm({ ...form, preferred_provider: e.target.value })}><option value="">Routing default</option><option value="grok">Grok</option><option value="openai">ChatGPT</option><option value="gemini">Gemini</option></Select></Field>
                  </div>
                  <Field label="Style notes (optional)" htmlFor="style"><Textarea id="style" maxLength={300} value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })} placeholder="e.g. call-and-response, lots of clapping, gentle bedtime pace" /></Field>
                  <div className="flex flex-wrap gap-6 text-sm">
                    <label className="flex items-center gap-2"><Switch checked={form.auto_render} onCheckedChange={(v) => setForm({ ...form, auto_render: v })} />Render video automatically</label>
                    <label className="flex items-center gap-2"><Switch checked={form.allow_fallback} onCheckedChange={(v) => setForm({ ...form, allow_fallback: v })} />Allow labelled template fallback</label>
                  </div>
                  <Button type="submit" loading={generate.isPending} className="justify-self-start"><Wand2 />Generate</Button>
                </form>
              </CardContent>
            </Card>
            <div className="grid content-start gap-4 lg:col-span-2">
              {genJob ? (
                <Card>
                  <CardHeader><CardTitle>Progress</CardTitle></CardHeader>
                  <CardContent className="grid gap-3">
                    <JobProgress jobId={genJob} invalidate={[["scripts"], ["videos"]]} />
                    {job?.status === "SUCCEEDED" && job.result?.script_id && (
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => navigate(`/content/${job.result!.script_id}`)}>Open script</Button>
                        {job.result.project_id && <Button variant="outline" asChild><Link to={`/videos?open=${job.result.project_id}`}>View video</Link></Button>}
                        {job.result.is_fallback && <Badge variant="warning">Fallback template (no AI)</Badge>}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ) : (
                <Card><CardContent className="p-6 text-sm text-muted-foreground">
                  <Sparkles className="mb-2 h-5 w-5 text-primary" />
                  Scripts include lyrics, a scene-by-scene storyboard, audio notes and SEO metadata. You can edit everything and regenerate individual sections before rendering.
                </CardContent></Card>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="ideas">
          <Card>
            <CardHeader className="flex-row flex-wrap items-end justify-between gap-3">
              <div><CardTitle>Content ideas</CardTitle><CardDescription>Ideas cite the research observation that supports them, or say they're untested.</CardDescription></div>
              <div className="flex items-end gap-2">
                <Field label="How many" htmlFor="ic"><Input id="ic" type="number" min={1} max={10} className="w-20" value={ideaCount} onChange={(e) => setIdeaCount(Number(e.target.value))} /></Field>
                <Button loading={genIdeas.isPending} disabled={!aiConfigured} onClick={() => genIdeas.mutate()}><Lightbulb />Generate ideas</Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3">
              {ideasJob && <JobProgress jobId={ideasJob} compact invalidate={[["ideas"]]} />}
              {!aiConfigured && <Alert variant="warning">Idea generation needs an AI model.</Alert>}
              {ideas.data?.items.length === 0 ? <EmptyState title="No open ideas" description="Generate ideas from your latest research report." /> : (
                <div className="grid gap-3 md:grid-cols-2">
                  {ideas.data?.items.map((i) => (
                    <div key={i.id} className="grid gap-2 rounded-lg border p-4">
                      <div className="flex flex-wrap items-center gap-2"><p className="font-medium">{i.topic}</p><Badge variant="secondary">{i.theme}</Badge><Badge variant="outline">{LANGUAGE_LABELS[i.language]}</Badge><Badge variant="outline">{i.video_format}</Badge></div>
                      <p className="text-sm">{i.objective}</p>
                      <p className="text-xs text-muted-foreground">Why: {i.rationale}</p>
                      <div className="flex gap-2"><Button size="sm" onClick={() => useIdea(i)}>Use idea</Button><Button size="sm" variant="ghost" onClick={() => dismiss.mutate(i.id)}>Dismiss</Button></div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="scripts">
          <Card>
            <CardHeader><CardTitle>Scripts</CardTitle></CardHeader>
            <CardContent>
              {scripts.data?.total === 0 ? <EmptyState title="No scripts yet" description="Generate your first original rhyme." /> : (
                <Table>
                  <thead><tr><Th>Title</Th><Th>Language</Th><Th>Format</Th><Th>Source</Th><Th>Status</Th><Th>Created</Th></tr></thead>
                  <tbody>
                    {scripts.data?.items.map((sc) => (
                      <tr key={sc.id} className="hover:bg-muted/50">
                        <Td><Link className="font-medium hover:underline" to={`/content/${sc.id}`}>{sc.title}</Link><p className="text-xs text-muted-foreground">{sc.topic}</p></Td>
                        <Td>{LANGUAGE_LABELS[sc.language]}</Td>
                        <Td>{sc.video_format}</Td>
                        <Td>{sc.is_fallback ? <Badge variant="warning">template</Badge> : <Badge>{sc.provider}</Badge>}</Td>
                        <Td>{sc.safety_flags.length ? <Badge variant="destructive">flagged</Badge> : sc.approved ? <Badge variant="success">approved</Badge> : <Badge variant="secondary">draft</Badge>}</Td>
                        <Td className="text-muted-foreground">{formatDate(sc.created_at)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
              {scripts.data && <Pager page={page} pageSize={15} total={scripts.data.total} onPage={setPage} />}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
