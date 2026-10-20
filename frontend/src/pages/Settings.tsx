import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { AppSettings, Page, SettingsResponse } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Alert, Skeleton, Table, Td, Th } from "@/components/ui/misc";
import { SwitchRow } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProviderKeyForm } from "./settings/ProviderKeyForm";
import { YouTubeConnection } from "./settings/YouTubeConnection";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PROVIDERS = ["grok", "openai", "gemini"];
const TASK_LABELS: Record<string, string> = { ideas: "Content ideas", script: "Lyrics & storyboard", metadata: "Titles & SEO", trend_analysis: "Trend analysis", recommendations: "Recommendations", review: "Independent review" };

export default function Settings() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const auditLog = useQuery({ queryKey: ["audit"], queryFn: () => api<Page<{ id: number; action: string; entity_type: string; entity_id: string; created_at: string }>>("/audit", { query: { page_size: 25 } }) });
  const [draft, setDraft] = useState<AppSettings | null>(null);
  useEffect(() => { if (q.data) setDraft(q.data.settings); }, [q.data]);
  useEffect(() => {
    const yt = params.get("youtube");
    if (yt === "connected") toast.success("YouTube channel connected");
    if (yt === "error") toast.error(`YouTube connection failed: ${params.get("reason") ?? "unknown error"}`);
    if (yt) { setParams({}, { replace: true }); qc.invalidateQueries({ queryKey: ["youtube-channel"] }); }
  }, [params, setParams, qc]);

  const save = useMutation({
    mutationFn: (patch: Partial<AppSettings>) => api<AppSettings>("/settings", { method: "PUT", body: patch }),
    onSuccess: () => { toast.success("Settings saved"); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); },
    onError: (e: Error) => { toast.error(e.message); if (q.data) setDraft(q.data.settings); },
  });
  const pause = useMutation({
    mutationFn: (p: boolean) => api(`/automation/${p ? "pause" : "resume"}`, { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); },
  });

  if (q.isLoading || !draft || !q.data) return <Skeleton className="h-96" />;
  const data = q.data;
  const set = <K extends keyof AppSettings>(k: K, v: AppSettings[K]) => setDraft({ ...draft, [k]: v });
  const toggle = (k: keyof AppSettings, v: boolean) => { setDraft({ ...draft, [k]: v }); save.mutate({ [k]: v }); };
  const routing = (task: string) => draft.llm_routing[task] ?? [];

  return (
    <>
      <PageHeader title="Settings" description="Credentials stay on the server. API keys are write-only and encrypted at rest." />
      <Tabs defaultValue="ai">
        <TabsList className="flex-wrap"><TabsTrigger value="ai">AI models</TabsTrigger><TabsTrigger value="youtube">YouTube</TabsTrigger><TabsTrigger value="publishing">Publishing</TabsTrigger><TabsTrigger value="automation">Automation</TabsTrigger><TabsTrigger value="rendering">Rendering</TabsTrigger><TabsTrigger value="system">System</TabsTrigger></TabsList>

        <TabsContent value="ai" className="grid gap-6">
          <div className="grid gap-4 lg:grid-cols-3">{data.providers.map((p) => <ProviderKeyForm key={p.provider} provider={p} />)}</div>
          <Card>
            <CardHeader><CardTitle>Model routing</CardTitle><CardDescription>Which model handles each task first. If it fails or returns invalid JSON, the next configured model is tried automatically.</CardDescription></CardHeader>
            <CardContent className="grid gap-3">
              {data.tasks.map((task) => (
                <div key={task} className="grid items-center gap-2 sm:grid-cols-4">
                  <span className="text-sm font-medium">{TASK_LABELS[task] ?? task}</span>
                  {[0, 1, 2].map((i) => (
                    <Select key={i} aria-label={`${task} choice ${i + 1}`} value={routing(task)[i] ?? ""} onChange={(e) => {
                      const next = [...routing(task)]; next[i] = e.target.value;
                      set("llm_routing", { ...draft.llm_routing, [task]: next.filter(Boolean) });
                    }}>
                      <option value="">{i === 0 ? "Default order" : "—"}</option>
                      {PROVIDERS.map((p) => <option key={p} value={p}>{i + 1}. {p === "openai" ? "ChatGPT" : p[0].toUpperCase() + p.slice(1)}</option>)}
                    </Select>
                  ))}
                </div>
              ))}
              <SwitchRow id="cmr" label="Cross-model review" description="After generation, a different model independently reviews originality, safety and age-appropriateness." checked={draft.cross_model_review} onCheckedChange={(v) => toggle("cross_model_review", v)} />
              <Button className="justify-self-start" loading={save.isPending} onClick={() => save.mutate({ llm_routing: draft.llm_routing })}>Save routing</Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="youtube">
          <Card>
            <CardHeader><CardTitle>YouTube channel</CardTitle><CardDescription>OAuth 2.0 with the channel owner's Google account.</CardDescription></CardHeader>
            <CardContent className="grid gap-4">
              <YouTubeConnection />
              <Alert title="How to revoke access">Use “Disconnect & revoke” above (deletes stored tokens and revokes them at Google), or remove “RhymePilot” at myaccount.google.com/permissions. Pause automation first if uploads are queued.</Alert>
              <p className="text-sm text-muted-foreground">Research API key: {data.youtube.api_key_configured ? "configured (YOUTUBE_API_KEY)" : "not set — research will use the connected channel's OAuth token"}.</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="publishing">
          <Card>
            <CardHeader><CardTitle>Defaults & publishing policy</CardTitle></CardHeader>
            <CardContent>
              <form className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" onSubmit={(e) => { e.preventDefault(); save.mutate({
                default_language: draft.default_language, default_format: draft.default_format, default_target_age: draft.default_target_age,
                timezone: draft.timezone, publish_window_start_hour: Number(draft.publish_window_start_hour), publish_window_end_hour: Number(draft.publish_window_end_hour),
                max_uploads_per_day: Number(draft.max_uploads_per_day), publish_days: draft.publish_days, default_privacy: draft.default_privacy, youtube_category_id: draft.youtube_category_id,
              }); }}>
                <Field label="Default language" htmlFor="dl"><Select id="dl" value={draft.default_language} onChange={(e) => set("default_language", e.target.value as AppSettings["default_language"])}><option value="hi">Hindi</option><option value="en">English</option><option value="bilingual">Bilingual</option></Select></Field>
                <Field label="Default format" htmlFor="df"><Select id="df" value={draft.default_format} onChange={(e) => set("default_format", e.target.value as AppSettings["default_format"])}><option value="short">Short (9:16)</option><option value="long">Long-form (16:9)</option></Select></Field>
                <Field label="Target age" htmlFor="ta"><Input id="ta" pattern="\d{1,2}-\d{1,2}" value={draft.default_target_age} onChange={(e) => set("default_target_age", e.target.value)} /></Field>
                <Field label="Time zone (IANA)" htmlFor="tz" hint="e.g. Asia/Kolkata"><Input id="tz" value={draft.timezone} onChange={(e) => set("timezone", e.target.value)} /></Field>
                <Field label="Window start hour" htmlFor="ws"><Input id="ws" type="number" min={0} max={23} value={draft.publish_window_start_hour} onChange={(e) => set("publish_window_start_hour", Number(e.target.value))} /></Field>
                <Field label="Window end hour" htmlFor="we"><Input id="we" type="number" min={1} max={24} value={draft.publish_window_end_hour} onChange={(e) => set("publish_window_end_hour", Number(e.target.value))} /></Field>
                <Field label="Max uploads per day" htmlFor="mu" hint="Each upload costs ~1,600 of the default 10,000 daily API quota units."><Input id="mu" type="number" min={1} max={10} value={draft.max_uploads_per_day} onChange={(e) => set("max_uploads_per_day", Number(e.target.value))} /></Field>
                <Field label="Default privacy (unscheduled)" htmlFor="dp"><Select id="dp" value={draft.default_privacy} onChange={(e) => set("default_privacy", e.target.value)}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></Select></Field>
                <Field label="YouTube category" htmlFor="cat"><Select id="cat" value={draft.youtube_category_id} onChange={(e) => set("youtube_category_id", e.target.value)}><option value="27">Education</option><option value="24">Entertainment</option><option value="10">Music</option><option value="1">Film & Animation</option></Select></Field>
                <fieldset className="sm:col-span-2 lg:col-span-3"><legend className="mb-2 text-sm font-medium">Publishing days</legend>
                  <div className="flex flex-wrap gap-2">{DAYS.map((d, i) => {
                    const on = draft.publish_days.includes(i);
                    return <button type="button" key={d} aria-pressed={on} onClick={() => set("publish_days", on ? draft.publish_days.filter((x) => x !== i) : [...draft.publish_days, i].sort())} className={`rounded-md border px-3 py-1.5 text-sm ${on ? "border-primary bg-primary text-white" : "bg-card"}`}>{d}</button>;
                  })}</div>
                </fieldset>
                <Button type="submit" className="justify-self-start" loading={save.isPending}>Save publishing settings</Button>
              </form>
              <div className="mt-4 border-t pt-2">
                <SwitchRow id="mfk" label="Made for Kids by default" description="Required for content directed at children (COPPA). Disables comments and personalised ads on YouTube." checked={draft.made_for_kids_default} onCheckedChange={(v) => toggle("made_for_kids_default", v)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="automation">
          <Card>
            <CardHeader><CardTitle>Automation controls</CardTitle><CardDescription>Automation runs one end-to-end pipeline per publishing day (03:17 UTC). Auto-publishing additionally needs a successful private test upload.</CardDescription></CardHeader>
            <CardContent className="grid gap-1 divide-y">
              <SwitchRow id="pause" label="Global pause" description="Stops all uploads and automated runs immediately and cancels queued uploads." checked={draft.paused} onCheckedChange={(v) => { set("paused", v); pause.mutate(v); }} />
              <SwitchRow id="dry" label="Dry-run mode" description="Validate and record uploads without calling YouTube. Turn off only after testing." checked={draft.dry_run} onCheckedChange={(v) => toggle("dry_run", v)} />
              <SwitchRow id="auto" label="Daily automation" description="Research → idea → script → render each publishing day." checked={draft.automation_enabled} onCheckedChange={(v) => toggle("automation_enabled", v)} />
              <SwitchRow id="autopub" label="Auto-publish READY videos" description={draft.private_test_passed_at ? `Private test passed ${formatDate(draft.private_test_passed_at)}.` : "Locked until a private test upload succeeds (or while dry-run is on)."} checked={draft.auto_publish_enabled} onCheckedChange={(v) => toggle("auto_publish_enabled", v)} disabled={!draft.private_test_passed_at && !draft.dry_run} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="rendering">
          <Card>
            <CardHeader><CardTitle>Rendering</CardTitle><CardDescription>Output resolution, frame rate and audio mix.</CardDescription></CardHeader>
            <CardContent>
              <form className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" onSubmit={(e) => { e.preventDefault(); save.mutate({ shorts_resolution: draft.shorts_resolution, long_resolution: draft.long_resolution, fps: Number(draft.fps), music_volume: Number(draft.music_volume), narration_volume: Number(draft.narration_volume) }); }}>
                <Field label="Shorts resolution" htmlFor="sr"><Select id="sr" value={draft.shorts_resolution} onChange={(e) => set("shorts_resolution", e.target.value)}><option value="1080x1920">1080×1920</option><option value="720x1280">720×1280</option><option value="540x960">540×960 (fast preview)</option></Select></Field>
                <Field label="Long-form resolution" htmlFor="lr"><Select id="lr" value={draft.long_resolution} onChange={(e) => set("long_resolution", e.target.value)}><option value="1920x1080">1920×1080</option><option value="1280x720">1280×720</option><option value="960x540">960×540 (fast preview)</option></Select></Field>
                <Field label="Frame rate" htmlFor="fps"><Select id="fps" value={draft.fps} onChange={(e) => set("fps", Number(e.target.value))}><option value={24}>24</option><option value={25}>25</option><option value={30}>30</option></Select></Field>
                <Field label={`Narration volume (${draft.narration_volume})`} htmlFor="nv"><input id="nv" type="range" min={0} max={2} step={0.05} value={draft.narration_volume} onChange={(e) => set("narration_volume", Number(e.target.value))} /></Field>
                <Field label={`Music volume (${draft.music_volume})`} htmlFor="mv"><input id="mv" type="range" min={0} max={1} step={0.05} value={draft.music_volume} onChange={(e) => set("music_volume", Number(e.target.value))} /></Field>
                <Button type="submit" className="justify-self-start self-end" loading={save.isPending}>Save rendering settings</Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="system" className="grid gap-6">
          <Card>
            <CardHeader><CardTitle>Media toolchain</CardTitle></CardHeader>
            <CardContent className="grid gap-2 text-sm">
              {[["FFmpeg", data.media.ffmpeg, "Required for rendering."], ["Local TTS (espeak-ng)", data.media.tts, "Without it, narration is silent and lyrics are on-screen only."], ["Hindi text shaping (libraqm)", data.media.raqm, "Needed for correct Devanagari rendering."], ["Devanagari font", !!data.media.devanagari_font, data.media.devanagari_font ?? "Install fonts-noto-core."]].map(([label, ok, hint]) => (
                <div key={label as string} className="flex items-start gap-2">{ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <XCircle className="mt-0.5 h-4 w-4 text-red-600" />}<div><p>{label}</p><p className="text-xs text-muted-foreground">{hint}</p></div></div>
              ))}
              <Alert variant="warning" className="mt-2">The built-in media providers are placeholders: procedural flat-cartoon visuals, robotic TTS and a simple synthesized melody. They are not equivalent to professional animation or singing.</Alert>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Audit log</CardTitle><CardDescription>Recent actions (secrets are never logged).</CardDescription></CardHeader>
            <CardContent>
              <Table><thead><tr><Th>When</Th><Th>Action</Th><Th>Entity</Th></tr></thead>
                <tbody>{auditLog.data?.items.map((a) => <tr key={a.id}><Td className="whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</Td><Td><Badge variant="secondary">{a.action}</Badge></Td><Td className="text-muted-foreground">{a.entity_type} {a.entity_id}</Td></tr>)}</tbody></Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
