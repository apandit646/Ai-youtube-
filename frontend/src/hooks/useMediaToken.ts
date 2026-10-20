import { useQuery } from "@tanstack/react-query";
import { api, apiUrl } from "@/lib/api";

/** <video>/<img> can't send Authorization headers, so the API issues short-lived per-video media tokens. */
export function useMediaUrl(projectId: number, enabled = true) {
  const q = useQuery({
    queryKey: ["media-token", projectId],
    queryFn: () => api<{ token: string }>(`/videos/${projectId}/media-token`),
    enabled,
    staleTime: 45 * 60 * 1000,
  });
  return (kind: string, download = false) =>
    q.data ? apiUrl(`/videos/${projectId}/file/${kind}`, { token: q.data.token, download: download || undefined }) : undefined;
}
