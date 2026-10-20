import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Check, RefreshCw, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Job, Page, Recommendation } from "@/lib/types";
import { formatDate, formatDuration, formatNumber, LANGUAGE_LABELS } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { JobProgress } from "@/components/JobProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, EmptyState, Pager, Skeleton, Table, Td, Th } from "@/components/ui/misc";
import { Select } from "@/components/ui/input";

interface Overview { connected: boolean; has_data: boolean; last_collected_at: string | null; series: Record<string, any>[]; totals: Record<string, number>; traffic_sources: Record<string, any>[]; unavailable_metrics: string[]; note: string | null }
interface VideoRow { youtube_video_id: string; title: string; language: string; topic: string; format: string; duration_seconds: number | null; privacy_status: string; published_at: string | null; views: number | null; views_source: string | null; estimated_minutes_watched: number | null; average_view_duration: number | null; average_view_percentage: number | null; likes: number | null; subscribers_gained: number | null }
interface Group { group: string; videos: number; mean_views: number; median_views: number; mean_avg_view_percentage: number | null }
interface Compare { video_count: number; by_language: Group[]; by_topic: Group[]; by_format: Group[]; by_duration: Group[]; by_publish_hour_utc: Group[]; experiments: string }

const NA = <span className="text-muted-foreground" title="Not available from the API for this video">n/a</span>;

function Kpi({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded-lg border bg-card p-4"><p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold">{value}</p></div>;
}

export default function Analytics() {
  const qc = useQueryClient();
  const [days, setDays] = useState(28);
  const [page, setPage] = useState(1);
  const [dimension, setDimension] = useState<keyof Compare>("by_language");
  const [jobId, setJobId] = useState<number | null>(null);
  const ov = useQuery({ queryKey: ["analytics-overview", days], queryFn: () => api<Overview>("/analytics/overview", { query: { days } }) });
  const vids = useQuery({ queryKey: ["analytics-videos", page], queryFn: () => api<Page<VideoRow>>("/analytics/videos", { query: { page, page_size: 20 } }) });
  const cmp = useQuery({ queryKey: ["analytics-compare"], queryFn: () => api<Compare>("/analytics/compare") });
  const recs = useQuery({ queryKey: ["recommendations"], queryFn: () => api<Page<Recommendation>>("/recommendations", { query: { page_size: 20 } }) });
  const inv = [["analytics-overview"], ["analytics-videos"], ["analytics-compare"], ["recommendations"]];
  const refresh = useMutation({ mutationFn: () => api<Job>("/analytics/refresh", { method: "POST" }), onSuccess: (j) => setJobId(j.id), onError: (e: Error) => toast.error(e.message) });
  const genRecs = useMutation({ mutationFn: () => api<Job>("/recommendations/generate", { method: "POST" }), onSuccess: (j) => setJobId(j.id), onError: (e: Error) => toast.error(e.message) });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api(`/recommendations/${id}`, { method: "PUT", body: { status } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recommendations"] }),
  });

  const o = ov.data;
  const groups = (cmp.data?.[dimension] as Group[] | undefined) ?? [];
  return (
    <>
      <PageHeader title="Analytics" description="Authorised metrics for your own channel from the YouTube Analytics API. Unavailable metrics are labelled, never estimated."
        actions={<>
          <Select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-36"><option value={7}>Last 7 days</option><option value={28}>Last 28 days</option><option value={90}>Last 90 days</option></Select>
          <Button variant="outline" loading={refresh.isPending} disabled={!o?.connected} onClick={() => refresh.mutate()}><RefreshCw />Collect now</Button>
        </>} />
      {jobId && <div className="mb-4"><JobProgress jobId={jobId} compact invalidate={inv} /></div>}
      {ov.isLoading ? <Skeleton className="h-72" /> : !o ? <Alert variant="error">{(ov.error as Error)?.message}</Alert> : (
        <>
          {!o.connected && <Alert variant="warning" className="mb-4" title="No channel connected">Connect your YouTube channel in Settings to collect analytics.</Alert>}
          {o.note && <Alert className="mb-4">{o.note}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Kpi label="Views" value={o.has_data ? formatNumber(o.totals.views) : "—"} />
            <Kpi label="Watch time (min)" value={o.has_data ? formatNumber(o.totals.estimatedMinutesWatched) : "—"} />
            <Kpi label="Avg view duration" value={o.has_data ? formatDuration(o.totals.averageViewDuration) : "—"} />
            <Kpi label="Subscribers gained" value={o.has_data ? formatNumber((o.totals.subscribersGained ?? 0) - (o.totals.subscribersLost ?? 0)) : "—"} />
            <Kpi label="Impressions / CTR" value={<span className="text-base font-normal text-muted-foreground">Not available via API</span>} />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Last collected: {formatDate(o.last_collected_at)}. YouTube Analytics data usually lags 24–72 hours.</p>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Daily views & watch time</CardTitle></CardHeader>
              <CardContent className="h-72">
                {o.series.length === 0 ? <EmptyState title="No time-series data yet" /> : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={o.series}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="day" fontSize={11} /><YAxis yAxisId="l" fontSize={11} /><YAxis yAxisId="r" orientation="right" fontSize={11} /><Tooltip /><Legend />
                      <Line yAxisId="l" type="monotone" dataKey="views" stroke="hsl(254 100% 64%)" strokeWidth={2} dot={false} name="Views" />
                      <Line yAxisId="r" type="monotone" dataKey="estimatedMinutesWatched" stroke="hsl(35 92% 50%)" strokeWidth={2} dot={false} name="Minutes watched" />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Traffic sources</CardTitle></CardHeader>
              <CardContent className="h-72">
                {o.traffic_sources.length === 0 ? <EmptyState title="Not collected yet" /> : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={o.traffic_sources} layout="vertical"><XAxis type="number" fontSize={11} /><YAxis type="category" dataKey="insightTrafficSourceType" width={110} fontSize={10} /><Tooltip /><Bar dataKey="views" fill="hsl(254 100% 64%)" radius={[0, 4, 4, 0]} /></BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>Comparisons</CardTitle><CardDescription>Median views by group across {cmp.data?.video_count ?? 0} videos with metrics. Observational only.</CardDescription></div>
            <Select aria-label="Compare by" className="w-44" value={dimension} onChange={(e) => setDimension(e.target.value as keyof Compare)}>
              <option value="by_language">Language</option><option value="by_topic">Topic</option><option value="by_format">Format</option><option value="by_duration">Duration</option><option value="by_publish_hour_utc">Publish hour (UTC)</option>
            </Select>
          </CardHeader>
          <CardContent>
            {groups.length === 0 ? <EmptyState title="Not enough data" description="Comparisons appear once published videos have metrics." /> : (
              <>
                <div className="h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={groups.map((g) => ({ ...g, name: LANGUAGE_LABELS[g.group] ?? g.group }))}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Bar dataKey="median_views" name="Median views" fill="hsl(254 100% 64%)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div>
                <Table><thead><tr><Th>Group</Th><Th className="text-right">Videos</Th><Th className="text-right">Median views</Th><Th className="text-right">Mean views</Th><Th className="text-right">Avg % viewed</Th></tr></thead>
                  <tbody>{groups.map((g) => <tr key={g.group}><Td>{LANGUAGE_LABELS[g.group] ?? g.group}</Td><Td className="text-right">{g.videos}{g.videos < 3 && <Badge variant="warning" className="ml-1">small n</Badge>}</Td><Td className="text-right">{formatNumber(g.median_views)}</Td><Td className="text-right">{formatNumber(g.mean_views)}</Td><Td className="text-right">{g.mean_avg_view_percentage != null ? `${g.mean_avg_view_percentage}%` : NA}</Td></tr>)}</tbody></Table>
              </>
            )}
            <p className="mt-2 text-xs text-muted-foreground">{cmp.data?.experiments}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between"><div><CardTitle>Recommendations</CardTitle><CardDescription>Grounded in stored metrics. Never applied automatically.</CardDescription></div>
            <Button size="sm" variant="outline" loading={genRecs.isPending} onClick={() => genRecs.mutate()}><Sparkles />Update</Button></CardHeader>
          <CardContent className="grid gap-3">
            {recs.data?.items.length === 0 ? <p className="text-sm text-muted-foreground">No recommendations yet.</p> : recs.data?.items.map((r) => (
              <div key={r.id} className="grid gap-1.5 rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-1.5"><p className="font-medium">{r.title}</p></div>
                <div className="flex flex-wrap gap-1"><Badge variant="secondary">{r.category}</Badge><Badge variant={r.confidence === "high" ? "success" : r.confidence === "medium" ? "default" : "warning"}>{r.confidence} confidence</Badge><Badge variant="outline">{r.source}</Badge>{r.status !== "proposed" && <Badge variant={r.status === "accepted" ? "success" : "secondary"}>{r.status}</Badge>}</div>
                <p className="text-muted-foreground">{r.body}</p>
                {r.supporting_data?.evidence && <p className="text-xs">Evidence: {r.supporting_data.evidence}</p>}
                <p className="text-xs text-muted-foreground">{formatDate(r.created_at)}</p>
                {r.status === "proposed" && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setStatus.mutate({ id: r.id, status: "accepted" })}><Check />Accept</Button><Button size="sm" variant="ghost" onClick={() => setStatus.mutate({ id: r.id, status: "dismissed" })}><X />Dismiss</Button></div>}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>Per-video performance</CardTitle></CardHeader>
        <CardContent>
          {vids.data?.total === 0 ? <EmptyState title="No published videos yet" description="Metrics appear after videos are uploaded and analytics are collected." /> : (
            <Table>
              <thead><tr><Th>Video</Th><Th>Lang</Th><Th>Format</Th><Th className="text-right">Views</Th><Th className="text-right">Watch min</Th><Th className="text-right">Avg duration</Th><Th className="text-right">Avg %</Th><Th className="text-right">Likes</Th><Th className="text-right">Subs</Th><Th className="text-right">Impr. / CTR</Th></tr></thead>
              <tbody>{vids.data?.items.map((v) => (
                <tr key={v.youtube_video_id}>
                  <Td className="max-w-xs"><a className="line-clamp-1 hover:underline" href={`https://www.youtube.com/watch?v=${v.youtube_video_id}`} target="_blank" rel="noreferrer">{v.title || v.youtube_video_id}</a><p className="text-xs text-muted-foreground">{formatDate(v.published_at)} · {v.privacy_status}</p></Td>
                  <Td>{LANGUAGE_LABELS[v.language] ?? v.language}</Td><Td>{v.format}</Td>
                  <Td className="text-right">{v.views != null ? <>{formatNumber(v.views)}{v.views_source === "public" && <span className="ml-1 text-xs text-muted-foreground" title="Public counter (Analytics data not yet available)">*</span>}</> : NA}</Td>
                  <Td className="text-right">{v.estimated_minutes_watched != null ? formatNumber(v.estimated_minutes_watched) : NA}</Td>
                  <Td className="text-right">{v.average_view_duration != null ? formatDuration(v.average_view_duration) : NA}</Td>
                  <Td className="text-right">{v.average_view_percentage != null ? `${formatNumber(v.average_view_percentage, 1)}%` : NA}</Td>
                  <Td className="text-right">{v.likes != null ? formatNumber(v.likes) : NA}</Td>
                  <Td className="text-right">{v.subscribers_gained != null ? formatNumber(v.subscribers_gained) : NA}</Td>
                  <Td className="text-right">{NA}</Td>
                </tr>
              ))}</tbody>
            </Table>
          )}
          {vids.data && <Pager page={page} pageSize={20} total={vids.data.total} onPage={setPage} />}
          <p className="mt-2 text-xs text-muted-foreground">* public view counter from the Data API, shown while Analytics data is still processing. Impressions and CTR are not exposed by the YouTube Analytics API queries this app uses.</p>
        </CardContent>
      </Card>
    </>
  );
}
