import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Lightbulb, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Job, Page, ResearchQuery, Snapshot, TrendReport } from "@/lib/types";
import { formatDate, formatDuration, formatNumber, LANGUAGE_LABELS } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { JobProgress } from "@/components/JobProgress";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Alert, EmptyState, Pager, Table, Td, Th } from "@/components/ui/misc";

const TOPICS = ["animals", "numbers", "colors", "shapes", "alphabet", "bedtime", "kindness", "hygiene", "fruits", "vehicles", "family", "nature", "unclassified"];

export default function Research() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState({ query_type: "topic", query: "", language: "", video_format: "", min_views: 0, max_results: 25, published_after: "", order: "viewCount" });
  const [jobId, setJobId] = useState<number | null>(null);
  const [filters, setFilters] = useState({ query_id: "", language: "", video_format: "", topic: "", min_views: "", sort: "views_per_day" });
  const [page, setPage] = useState(1);

  const queries = useQuery({ queryKey: ["research-queries"], queryFn: () => api<Page<ResearchQuery>>("/research/queries", { query: { page_size: 50 } }) });
  const results = useQuery({ queryKey: ["research-results", filters, page], queryFn: () => api<Page<Snapshot>>("/research/results", { query: { ...filters, page, page_size: 25 } }) });
  const reports = useQuery({ queryKey: ["trend-reports"], queryFn: () => api<Page<TrendReport>>("/research/reports", { query: { page_size: 10 } }) });
  const [reportId, setReportId] = useState<number | null>(null);
  const report = reports.data?.items.find((r) => r.id === reportId) ?? reports.data?.items[0];

  const search = useMutation({
    mutationFn: () => api<{ job: Job }>("/research/search", { method: "POST", body: {
      query_type: form.query_type, query: form.query, language: form.language || undefined, video_format: form.video_format || undefined,
      min_views: Number(form.min_views) || 0, max_results: Number(form.max_results), order: form.order,
      published_after: form.published_after ? new Date(form.published_after).toISOString() : undefined,
    } }),
    onSuccess: (r) => { setJobId(r.job.id); toast.success("Research job queued"); qc.invalidateQueries({ queryKey: ["research-queries"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const ideas = useMutation({
    mutationFn: (trend_report_id: number) => api<Job>("/content/ideas", { method: "POST", body: { count: 5, trend_report_id } }),
    onSuccess: (job) => { toast.success("Idea generation started"); navigate(`/content?ideasJob=${job.id}`); },
    onError: (e: Error) => toast.error(e.message),
  });

  const obs = report?.observations ?? {};
  const topicData = (obs.top_topics ?? []).slice(0, 8).map((t: any) => ({ name: t.topic, videos: t.videos, vpd: t.median_views_per_day ?? 0 }));

  return (
    <>
      <PageHeader title="Research Studio" description="Study public nursery-rhyme videos through the official YouTube Data API. Only public statistics are used — competitors' CTR, retention and revenue are never available or inferred." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>New research</CardTitle><CardDescription>A topic search costs ~100 quota units; channel lookups ~3.</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); search.mutate(); }}>
              <Field label="Search by" htmlFor="qt"><Select id="qt" value={form.query_type} onChange={(e) => setForm({ ...form, query_type: e.target.value })}><option value="topic">Topic / keywords</option><option value="channel">Channel ID</option></Select></Field>
              <Field label={form.query_type === "topic" ? "Topic" : "Channel ID (UC…)"} htmlFor="q"><Input id="q" required minLength={2} value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} placeholder={form.query_type === "topic" ? "e.g. hindi animal rhymes" : "UCxxxxxxxxxxxxxxxx"} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Language" htmlFor="l"><Select id="l" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}><option value="">Any</option><option value="hi">Hindi</option><option value="en">English</option><option value="bilingual">Bilingual</option></Select></Field>
                <Field label="Format" htmlFor="f"><Select id="f" value={form.video_format} onChange={(e) => setForm({ ...form, video_format: e.target.value })}><option value="">Any</option><option value="short">Shorts</option><option value="long">Long-form</option></Select></Field>
                <Field label="Published after" htmlFor="pa"><Input id="pa" type="date" value={form.published_after} onChange={(e) => setForm({ ...form, published_after: e.target.value })} /></Field>
                <Field label="Min views" htmlFor="mv"><Input id="mv" type="number" min={0} value={form.min_views} onChange={(e) => setForm({ ...form, min_views: Number(e.target.value) })} /></Field>
                <Field label="Max results" htmlFor="mr"><Input id="mr" type="number" min={1} max={50} value={form.max_results} onChange={(e) => setForm({ ...form, max_results: Number(e.target.value) })} /></Field>
                <Field label="Order" htmlFor="o"><Select id="o" value={form.order} onChange={(e) => setForm({ ...form, order: e.target.value })}><option value="viewCount">Most viewed</option><option value="date">Newest</option><option value="relevance">Relevance</option></Select></Field>
              </div>
              <Button type="submit" loading={search.isPending}><Search />Run research</Button>
            </form>
            {jobId && <div className="mt-4"><JobProgress jobId={jobId} invalidate={[["research-queries"], ["research-results"], ["trend-reports"]]} /></div>}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
            <div><CardTitle>Trend report</CardTitle><CardDescription>{report ? `Report #${report.id} · ${formatDate(report.created_at)} · ${obs.video_count ?? 0} videos` : "Run research to create a report"}</CardDescription></div>
            {reports.data && reports.data.items.length > 0 && (
              <div className="flex gap-2">
                <Select aria-label="Choose report" value={report?.id ?? ""} onChange={(e) => setReportId(Number(e.target.value))} className="w-44">
                  {reports.data.items.map((r) => <option key={r.id} value={r.id}>Report #{r.id}</option>)}
                </Select>
                {report && <Button size="sm" variant="accent" loading={ideas.isPending} onClick={() => ideas.mutate(report.id)}><Lightbulb />Ideas from this</Button>}
              </div>
            )}
          </CardHeader>
          <CardContent className="grid gap-4">
            {!report ? <EmptyState title="No reports yet" description="Reports summarise stored research snapshots: language, format, topic and upload-time patterns." /> : (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg bg-muted p-3"><p className="text-xs text-muted-foreground">Median views</p><p className="text-lg font-semibold">{formatNumber(obs.median_views)}</p></div>
                  <div className="rounded-lg bg-muted p-3"><p className="text-xs text-muted-foreground">Median views/day</p><p className="text-lg font-semibold">{formatNumber(obs.median_views_per_day, 1)}</p></div>
                  <div className="rounded-lg bg-muted p-3"><p className="text-xs text-muted-foreground">Median duration</p><p className="text-lg font-semibold">{formatDuration(obs.duration_seconds?.median)}</p></div>
                </div>
                {topicData.length > 0 && (
                  <div className="h-56" aria-label="Topics chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={topicData}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Bar dataKey="vpd" name="Median views/day" fill="hsl(254 100% 64%)" radius={[4, 4, 0, 0]} /></BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <p className="mb-1 text-sm font-medium">Observations <Badge variant="success">from data</Badge></p>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {Object.entries(obs.by_language ?? {}).map(([k, v]: [string, any]) => <li key={k}>{LANGUAGE_LABELS[k] ?? k}: {v.videos} videos, median {formatNumber(v.median_views_per_day, 1)} views/day</li>)}
                      {Object.entries(obs.by_format ?? {}).map(([k, v]: [string, any]) => <li key={k}>{k}: {v.videos} videos, median {formatNumber(v.median_views)} views</li>)}
                      {(report.ai_summary?.observations ?? []).map((o, i) => <li key={`ai${i}`}>{o}</li>)}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-1 text-sm font-medium">Hypotheses <Badge variant="warning">unverified</Badge></p>
                    {report.ai_summary ? (
                      <ul className="list-disc space-y-1 pl-5 text-sm">{report.ai_summary.hypotheses.map((h, i) => <li key={i}>{h}</li>)}</ul>
                    ) : <p className="text-sm text-muted-foreground">{report.error ?? "No AI interpretation."}</p>}
                  </div>
                </div>
                {report.ai_summary && (
                  <div>
                    <p className="mb-1 text-sm font-medium">AI summary <span className="text-xs text-muted-foreground">({report.provider} · {report.model})</span></p>
                    <p className="text-sm">{report.ai_summary.summary}</p>
                    {report.ai_summary.opportunities.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2">{report.ai_summary.opportunities.map((o, i) => <Badge key={i} variant="secondary" title={o.why}>{o.topic} · {o.language} · {o.format}</Badge>)}</div>
                    )}
                  </div>
                )}
                <Alert title="Data limits">{(obs.data_limits ?? []).join(" ")}</Alert>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>Research results</CardTitle><CardDescription>Timestamped public snapshots stored in your database.</CardDescription></CardHeader>
        <CardContent>
          <div className="mb-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Select aria-label="Research query" value={filters.query_id} onChange={(e) => { setFilters({ ...filters, query_id: e.target.value }); setPage(1); }}>
              <option value="">All queries</option>
              {queries.data?.items.map((q) => <option key={q.id} value={q.id}>#{q.id} {q.query_text}</option>)}
            </Select>
            <Select aria-label="Language filter" value={filters.language} onChange={(e) => { setFilters({ ...filters, language: e.target.value }); setPage(1); }}>
              <option value="">Any language</option><option value="hi">Hindi</option><option value="en">English</option><option value="bilingual">Bilingual</option><option value="unknown">Unknown</option>
            </Select>
            <Select aria-label="Format filter" value={filters.video_format} onChange={(e) => { setFilters({ ...filters, video_format: e.target.value }); setPage(1); }}>
              <option value="">Any format</option><option value="short">Shorts</option><option value="long">Long-form</option>
            </Select>
            <Select aria-label="Topic filter" value={filters.topic} onChange={(e) => { setFilters({ ...filters, topic: e.target.value }); setPage(1); }}>
              <option value="">Any topic</option>{TOPICS.map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
            <Input aria-label="Minimum views" type="number" min={0} placeholder="Min views" value={filters.min_views} onChange={(e) => { setFilters({ ...filters, min_views: e.target.value }); setPage(1); }} />
            <Select aria-label="Sort" value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value })}>
              <option value="views_per_day">Views / day</option><option value="view_count">Total views</option><option value="engagement_rate">Engagement</option><option value="published_at">Newest</option>
            </Select>
          </div>
          {results.data && results.data.total === 0 ? <EmptyState title="No results" description="Run a research query or relax the filters." /> : (
            <Table>
              <thead><tr><Th>Video</Th><Th>Channel</Th><Th>Lang</Th><Th>Format</Th><Th className="text-right">Views</Th><Th className="text-right">Views/day</Th><Th className="text-right">Engagement</Th><Th>Published</Th></tr></thead>
              <tbody>
                {results.data?.items.map((s) => (
                  <tr key={s.id}>
                    <Td className="max-w-xs"><a className="line-clamp-2 hover:underline" href={`https://www.youtube.com/watch?v=${s.video_id}`} target="_blank" rel="noreferrer">{s.title}</a>
                      <div className="mt-1 flex flex-wrap gap-1">{s.topics.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</div></Td>
                    <Td className="text-muted-foreground">{s.channel_title}</Td>
                    <Td>{LANGUAGE_LABELS[s.language] ?? s.language}</Td>
                    <Td>{s.video_format}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(s.view_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(s.views_per_day, 1)}</Td>
                    <Td className="text-right tabular-nums">{s.engagement_rate != null ? `${(s.engagement_rate * 100).toFixed(2)}%` : "—"}</Td>
                    <Td className="whitespace-nowrap text-muted-foreground">{formatDate(s.published_at, { dateStyle: "medium" })}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {results.data && <Pager page={page} pageSize={25} total={results.data.total} onPage={setPage} />}
        </CardContent>
      </Card>

      {queries.data && queries.data.items.length > 0 && (
        <Card className="mt-6">
          <CardHeader><CardTitle>Query history</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <thead><tr><Th>#</Th><Th>Query</Th><Th>Status</Th><Th className="text-right">Results</Th><Th className="text-right">Quota units</Th><Th>When</Th></tr></thead>
              <tbody>{queries.data.items.map((q) => (
                <tr key={q.id}><Td>{q.id}</Td><Td>{q.query_type}: {q.query_text}{q.error && <p className="text-xs text-red-700">{q.error}</p>}</Td><Td><StatusBadge status={q.status} /></Td><Td className="text-right">{q.result_count}</Td><Td className="text-right">{q.quota_units_used}</Td><Td className="text-muted-foreground">{formatDate(q.created_at)}</Td></tr>
              ))}</tbody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  );
}
