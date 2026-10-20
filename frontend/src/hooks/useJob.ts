import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

const TERMINAL = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);

/** Polls a background job until it reaches a terminal state, then invalidates related queries. */
export function useJob(jobId: number | null | undefined, invalidate: readonly (readonly unknown[])[] = []) {
  const qc = useQueryClient();
  const done = useRef<number | null>(null);
  const q = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data && TERMINAL.has(query.state.data.status) ? false : 1500),
  });
  useEffect(() => {
    if (q.data && TERMINAL.has(q.data.status) && done.current !== q.data.id) {
      done.current = q.data.id;
      invalidate.forEach((key) => qc.invalidateQueries({ queryKey: key }));
    }
  }, [q.data, qc, invalidate]);
  return { job: q.data, isTerminal: !!q.data && TERMINAL.has(q.data.status) };
}

export { TERMINAL };
