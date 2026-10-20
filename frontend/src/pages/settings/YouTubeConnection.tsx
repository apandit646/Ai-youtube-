import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Youtube } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, Skeleton } from "@/components/ui/misc";
import { formatNumber } from "@/lib/utils";

interface ChannelStatus { connected: boolean; oauth_configured: boolean; title?: string; channel_id?: string; subscriber_count?: number | null; video_count?: number | null; scopes?: string[]; thumbnail_url?: string }

export function YouTubeConnection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["youtube-channel"], queryFn: () => api<ChannelStatus>("/youtube/channel") });
  const connect = useMutation({
    mutationFn: () => api<{ auth_url: string }>("/youtube/auth"),
    onSuccess: (r) => { window.location.href = r.auth_url; },
    onError: (e: Error) => toast.error(e.message),
  });
  const revoke = useMutation({
    mutationFn: () => api<{ revoked_at_google: boolean }>("/youtube/revoke", { method: "POST" }),
    onSuccess: (r) => {
      toast.success(r.revoked_at_google ? "Access revoked at Google and tokens deleted" : "Local tokens deleted (Google revoke could not be confirmed — remove access manually)");
      qc.invalidateQueries({ queryKey: ["youtube-channel"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (q.isLoading) return <Skeleton className="h-24" />;
  const ch = q.data;
  return (
    <div className="grid gap-3">
      {!ch?.oauth_configured && (
        <Alert variant="warning" title="Google OAuth is not configured on the server">
          Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI in the backend environment (see README → YouTube OAuth), then restart the API.
        </Alert>
      )}
      {ch?.connected ? (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border p-4">
          {ch.thumbnail_url ? <img src={ch.thumbnail_url} alt="" className="h-12 w-12 rounded-full" /> : <Youtube className="h-10 w-10 text-red-600" />}
          <div className="flex-1">
            <p className="font-medium">{ch.title}</p>
            <p className="text-xs text-muted-foreground">{ch.channel_id} · {ch.subscriber_count != null ? `${formatNumber(ch.subscriber_count)} subscribers` : "subscriber count hidden"} · {formatNumber(ch.video_count)} videos</p>
            <div className="mt-1 flex flex-wrap gap-1">{ch.scopes?.map((s) => <Badge key={s} variant="secondary">{s.split("/").pop()}</Badge>)}</div>
          </div>
          <Button variant="destructive" size="sm" loading={revoke.isPending} onClick={() => { if (confirm("Disconnect this channel and revoke RhymePilot's access?")) revoke.mutate(); }}>Disconnect & revoke</Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-4">
          <Youtube className="h-8 w-8 text-red-600" />
          <p className="flex-1 text-sm text-muted-foreground">Connect the channel you own. RhymePilot requests upload, read-only and analytics scopes.</p>
          <Button disabled={!ch?.oauth_configured} loading={connect.isPending} onClick={() => connect.mutate()}>Connect YouTube</Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">You can also revoke access any time at myaccount.google.com/permissions. Unverified Google Cloud projects may only upload private videos until the project passes Google's audit.</p>
    </div>
  );
}
