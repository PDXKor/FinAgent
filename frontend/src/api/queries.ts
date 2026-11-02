// TanStack Query hooks. The only module that calls API clients.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Order, RunSort, RunStatus } from "../lib/search";
import { data, unwrap } from "./data";

export const ACTIVE_POLL_MS = 2_000; // while a job runs
export const IDLE_POLL_MS = 15_000;

export type RunsQuery = {
  job?: string;
  status?: RunStatus;
  since?: string; // ISO instant, inclusive
  until?: string; // ISO instant, exclusive
  sort?: RunSort;
  order?: Order;
  limit: number;
};

export type RowsQuery = {
  table: string;
  filter?: string[];
  sort?: string;
  order?: Order;
  limit: number;
  offset: number;
};

export const keys = {
  health: ["data", "health"] as const,
  jobs: ["data", "jobs"] as const,
  ingestRuns: (q: RunsQuery) => ["data", "ingest-runs", q] as const,
  counts: ["data", "counts"] as const,
  tables: ["data", "tables"] as const,
  rows: (q: RowsQuery) => ["data", "rows", q] as const,
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

export function useIngestRuns(q: RunsQuery, active: boolean) {
  return useQuery({
    queryKey: keys.ingestRuns(q),
    queryFn: () => unwrap(data.GET("/v1/ingest-runs", { params: { query: q } })),
    refetchInterval: interval(active),
    placeholderData: keepPreviousData, // keep rows on screen while filters change
  });
}

export function useCounts(active: boolean) {
  return useQuery({
    queryKey: keys.counts,
    queryFn: () => unwrap(data.GET("/v1/ops/counts")),
    refetchInterval: interval(active),
  });
}

export function useTables() {
  return useQuery({
    queryKey: keys.tables,
    queryFn: () => unwrap(data.GET("/v1/tables")),
    staleTime: 5 * 60_000, // schema changes only on deploy
  });
}

export function useTableRows(q: RowsQuery | undefined) {
  return useQuery({
    queryKey: keys.rows(q ?? { table: "", limit: 0, offset: 0 }),
    queryFn: () => {
      const { table, ...query } = q!;
      return unwrap(data.GET("/v1/tables/{name}/rows", { params: { path: { name: table }, query } }));
    },
    enabled: q !== undefined,
    placeholderData: keepPreviousData,
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
