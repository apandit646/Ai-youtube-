import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, AlertTriangle, CalendarClock, Clapperboard, Eye, Pause, Play, Rocket, Users } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Job, Project, ProviderStatus, PublishingJob, SettingsResponse } from "@/lib/types";
import { formatDate, formatDuration, formatNumber } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { JobProgress } from "@/components/JobProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, EmptyState, Skeleton } from "@/components/ui/misc";
import { SetupWizard } from "./SetupWizard";

interface DashboardData {
  channel: { connected: boolean; title: string | null; subscriber_count: number | null; video_count: number | null };
  analytics: { has_data: boolean; totals: Record<string, number>; last_collected_at: string | null; unavailable: string[] };
  jobs: { queued: number; running: number; failed_last_7_days: number; succeeded: number };
  active_jobs: Job[];
  projects_by_status: Record<string, number>;
  recent_videos: Project[];
  upcoming: PublishingJob[];
  automation: { enabled: boolean; paused: boolean; dry_run: boolean; auto_publish: boolean; private_test_passed_at: string | null };
  connections: { ai_providers: ProviderStatus[]; ai_configured: boolean; youtube_oauth_configured: boolean; youtube_connected: boolean; worker_alive: boolean; worker_heartbeat: string | null };
}

function Stat({ icon: Icon, label, value, hint }: { icon: React.ElementType; label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-secondary"><Icon className="h-5 w-5 text-primary" aria-hidden /></div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold">{value}</p>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<DashboardData>("/dashboard"), refetchInterval: 10000 });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const toggle = useMutation({
    mutationFn: (pause: boolean) => api<{ note?: string }>(`/automation/${pause ? "pause" : "resume"}`, { method: "POST" }),
    onSuccess: (r, pause) => { toast.success(pause ? "Automation paused" : "Automation resumed", { description: r.note }); qc.invalidateQueries({ queryKey: ["dashboard"] }); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const runNow = useMutation({
    mutationFn: () => api<Job>("/automation/run", { method: "POST" }),
    onSuccess: () => { toast.success("Pipeline run queued"); qc.invalidateQueries({ queryKey: ["dashboard"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (q.isLoading) return <div className="grid gap-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-28" /><Skeleton className="h-64" /></div>;
  if (q.isError || !q.data) return <Alert variant="error" title="Could not load the dashboard">{(q.error as Error)?.message}</Alert>;
  const d = q.data;
  const totals = d.analytics.totals;

  return (
    <>
      {settings.data && !settings.data.settings.setup_completed && <SetupWizard data={settings.data} />}
      <PageHeader title="Dashboard" description="Overview of your channel, production pipeline and publishing queue."
        actions={<>
          <Button variant="outline" onClick={() => toggle.mutate(!d.automation.paused)} loading={toggle.isPending}>
            {d.automation.paused ? <><Play />Resume automation</> : <><Pause />Pause everything</>}
          </Button>
          <Button onClick={() => runNow.mutate()} loading={runNow.isPending} disabled={d.automation.paused}><Rocket />Run pipeline now</Button>
        </>} />

      {d.automation.paused && <Alert variant="warning" title="Automation is paused" className="mb-4">No uploads or automated runs will happen until you resume.</Alert>}
      {!d.connections.worker_alive && <Alert variant="warning" title="Background worker not detected" className="mb-4">Jobs will stay queued until the worker service is running (docker compose up worker).</Alert>}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Users} label="Subscribers" value={d.channel.connected ? (d.channel.subscriber_count != null ? formatNumber(d.channel.subscriber_count) : "Hidden") : "—"} hint={d.channel.connected ? d.channel.title ?? "" : "Channel not connected"} />
        <Stat icon={Eye} label="Views (28 days)" value={d.analytics.has_data ? formatNumber(totals.views) : "—"} hint={d.analytics.has_data ? `Collected ${formatDate(d.analytics.last_collected_at)}` : "No analytics collected yet"} />
        <Stat icon={Activity} label="Jobs running / queued" value={`${d.jobs.running} / ${d.jobs.queued}`} hint={`${d.jobs.succeeded} completed`} />
        <Stat icon={AlertTriangle} label="Failed (7 days)" value={d.jobs.failed_last_7_days} hint="Retry from the Video Library" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>Recent videos</CardTitle><CardDescription>Latest generated projects</CardDescription></div>
            <Button asChild variant="outline" size="sm"><Link to="/videos">Open library</Link></Button>
          </CardHeader>
          <CardContent>
            {d.recent_videos.length === 0 ? (
              <EmptyState icon={Clapperboard} title="No videos yet" description="Generate a rhyme in the Content Studio to create your first video." action={<Button asChild><Link to="/content">Create a rhyme</Link></Button>} />
            ) : (
              <ul className="divide-y">
                {d.recent_videos.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-3 py-2.5">
                    <Link to={`/videos?open=${p.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">{p.title}</Link>
                    <Badge variant="outline">{p.video_format === "short" ? "Short 9:16" : "Long 16:9"}</Badge>
                    <span className="w-16 text-right text-sm text-muted-foreground">{formatDuration(p.duration_seconds)}</span>
                    <StatusBadge status={p.status} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Connections</CardTitle><CardDescription>Integration status</CardDescription></CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {d.connections.ai_providers.map((p) => (
              <div key={p.provider} className="flex items-center justify-between"><span>{p.label}</span>{p.configured ? <Badge variant="success">{p.model}</Badge> : <Badge variant="secondary">off</Badge>}</div>
            ))}
            <div className="flex items-center justify-between"><span>YouTube channel</span>{d.connections.youtube_connected ? <Badge variant="success">connected</Badge> : <Badge variant={d.connections.youtube_oauth_configured ? "warning" : "secondary"}>{d.connections.youtube_oauth_configured ? "not connected" : "OAuth not configured"}</Badge>}</div>
            <div className="flex items-center justify-between"><span>Worker</span>{d.connections.worker_alive ? <Badge variant="success">alive</Badge> : <Badge variant="destructive">offline</Badge>}</div>
            <div className="flex items-center justify-between"><span>Publishing mode</span><Badge variant={d.automation.dry_run ? "warning" : "success"}>{d.automation.dry_run ? "dry run" : "live"}</Badge></div>
            <div className="flex items-center justify-between"><span>Private test upload</span>{d.automation.private_test_passed_at ? <Badge variant="success">passed</Badge> : <Badge variant="secondary">not yet</Badge>}</div>
            {!d.connections.ai_configured && <Alert variant="warning" className="mt-2">No AI model configured — content uses labelled local templates.</Alert>}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Active jobs</CardTitle><CardDescription>Research, generation, rendering and uploads run in the background.</CardDescription></CardHeader>
          <CardContent className="grid gap-3">
            {d.active_jobs.length === 0 ? <p className="text-sm text-muted-foreground">Nothing running right now.</p> : d.active_jobs.slice(0, 4).map((j) => <JobProgress key={j.id} jobId={j.id} compact invalidate={[["dashboard"]]} />)}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>Next scheduled uploads</CardTitle></div>
            <CalendarClock className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {d.upcoming.length === 0 ? <p className="text-sm text-muted-foreground">No uploads scheduled.</p> : (
              <ul className="grid gap-2 text-sm">
                {d.upcoming.map((u) => (
                  <li key={u.id} className="flex items-center justify-between gap-2">
                    <span className="truncate">{u.project_title}</span>
                    <span className="shrink-0 text-muted-foreground">{formatDate(u.publish_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
