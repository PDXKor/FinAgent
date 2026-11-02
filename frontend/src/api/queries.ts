// TanStack Query hooks. The only module that calls API clients.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data, unwrap } from "./data";

export const ACTIVE_POLL_MS = 2_000; // while a job runs
export const IDLE_POLL_MS = 15_000;

export const keys = {
  health: ["data", "health"] as const,
  jobs: ["data", "jobs"] as const,
  ingestRuns: (job?: string) => ["data", "ingest-runs", job ?? "all"] as const,
  counts: ["data", "counts"] as const,
};

const interval = (active: boolean) => (active ? ACTIVE_POLL_MS : IDLE_POLL_MS);

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => unwrap(data.GET("/v1/health")),
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useJobs() {
  return useQuery({
    queryKey: keys.jobs,
    queryFn: () => unwrap(data.GET("/v1/jobs")),
    refetchInterval: (q) => interval(q.state.data?.some((j) => j.running) ?? false),
  });
}

export function useIngestRuns(job: string | undefined, active: boolean) {
  return useQuery({
    queryKey: keys.ingestRuns(job),
    queryFn: () =>
      unwrap(data.GET("/v1/ingest-runs", { params: { query: { job, limit: 50 } } })),
    refetchInterval: interval(active),
  });
}

export function useCounts(active: boolean) {
  return useQuery({
    queryKey: keys.counts,
    queryFn: () => unwrap(data.GET("/v1/ops/counts")),
    refetchInterval: interval(active),
  });
}

export function useStartJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(data.POST("/v1/jobs/{name}/runs", { params: { path: { name } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: ["data"] }),
  });
}
