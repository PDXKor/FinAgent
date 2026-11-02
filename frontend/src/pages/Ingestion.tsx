import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import type { IngestRun, Job } from "../api/data";
import { useCounts, useIngestRuns, useJobs, useStartJob } from "../api/queries";
import StatusBadge, { toStatus, type Status } from "../components/StatusBadge";
import { EMPTY, formatAgo, formatCount, formatDateTime, formatElapsed } from "../lib/format";
import { useNow } from "../lib/useNow";

/** Badge state for a job: its own process state first, then its last run record. */
export function jobStatus(job: Job): Status {
  if (job.running) return "running";
  if (job.last_error) return "failed";
  const s = job.last_run?.status;
  return s === "running" ? "external" : toStatus(s);
}

/** A `running` record is live only if this API is running that job now. */
function runStatus(run: IngestRun, active: Job | undefined, latestOfActive?: string): Status {
  if (run.status !== "running") return toStatus(run.status);
  return active && run.run_id === latestOfActive ? "running" : "external";
}

export default function Ingestion() {
  const jobs = useJobs();
  const active = jobs.data?.find((j) => j.running);
  const [filter, setFilter] = useState<string>("");
  const runs = useIngestRuns(filter || undefined, !!active);
  const counts = useCounts(!!active);
  const start = useStartJob();
  const now = useNow(!!active);
  useRefreshWhenJobEnds(!!active);

  return (
    <div className="space-y-8">
      <section>
        <SectionTitle
          title="Ingestion jobs"
          note="One job runs at a time. Run in order: sec_tickers → sec_submissions → sec_companyfacts. sec_frames is independent."
        />
        {start.isError && (
          <Banner onClose={() => start.reset()}>
            Could not start {start.variables}: {start.error.message}
          </Banner>
        )}
        {jobs.isError ? (
          <Banner>{jobs.error.message}</Banner>
        ) : (
          <Table
            head={["Job", "Status", "Last run", "Duration", "Requests", "Rows", "Errors", ""]}
            loading={jobs.isPending}
          >
            {jobs.data?.map((job) => (
              <JobRow
                key={job.name}
                job={job}
                now={now}
                disabled={!!active || start.isPending}
                busyReason={active ? `${active.name} is running` : undefined}
                onRun={() => start.mutate(job.name)}
              />
            ))}
          </Table>
        )}
      </section>

      <section>
        <SectionTitle title="Tables" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {Object.entries(counts.data ?? {}).map(([table, n]) => (
            <div
              key={table}
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <div className="text-xs text-zinc-500">{table}</div>
              <div className="text-lg font-semibold tabular-nums">{formatCount(n)}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-end justify-between gap-4">
          <SectionTitle title="Recent runs" />
          <select
            aria-label="Filter by job"
            className="mb-3 rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">All jobs</option>
            {jobs.data?.map((j) => (
              <option key={j.name} value={j.name}>
                {j.name}
              </option>
            ))}
          </select>
        </div>
        {runs.isError ? (
          <Banner>{runs.error.message}</Banner>
        ) : (
          <Table
            head={["Started", "Job", "Status", "Duration", "Requests", "Rows", "Errors", "Error"]}
            loading={runs.isPending}
            empty={runs.data?.length === 0 ? "No runs yet." : undefined}
          >
            {runs.data?.map((run) => (
              <tr key={run.run_id}>
                <Td title={run.started_at}>{formatDateTime(run.started_at)}</Td>
                <Td mono>{run.job}</Td>
                <Td>
                  <StatusBadge
                    status={runStatus(run, active, active?.last_run?.run_id)}
                  />
                </Td>
                <Td num>{formatElapsed(run.started_at, run.finished_at, now)}</Td>
                <Td num>{formatCount(run.requests)}</Td>
                <Td num>{formatCount(run.rows_written)}</Td>
                <Td num>{formatCount(run.errors)}</Td>
                <Td>
                  <span
                    className="block max-w-xs truncate text-red-700 dark:text-red-400"
                    title={run.error_sample ?? undefined}
                  >
                    {run.error_sample ?? ""}
                  </span>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </section>
    </div>
  );
}

function JobRow(props: {
  job: Job;
  now: number;
  disabled: boolean;
  busyReason?: string;
  onRun: () => void;
}) {
  const { job, now, disabled, busyReason, onRun } = props;
  const run = job.last_run;
  const status = jobStatus(job);
  // While the API has started a job but the runner hasn't written its record yet,
  // last_run is still the previous run.
  const current = !job.running || run?.status === "running" ? run : undefined;
  const error = job.last_error ?? current?.error_sample;
  return (
    <>
      <tr>
        <Td>
          <div className="font-mono text-sm">{job.name}</div>
          <div className="font-mono text-xs text-zinc-500">{job.schedule ?? "not scheduled"}</div>
        </Td>
        <Td>
          <StatusBadge status={status} />
        </Td>
        <Td title={current?.started_at}>
          {job.running && !current ? "starting…" : formatAgo(current?.started_at, now)}
        </Td>
        <Td num>{current ? formatElapsed(current.started_at, current.finished_at, now) : EMPTY}</Td>
        <Td num>{formatCount(current?.requests)}</Td>
        <Td num>{formatCount(current?.rows_written)}</Td>
        <Td num>{formatCount(current?.errors)}</Td>
        <Td>
          <button
            type="button"
            onClick={onRun}
            disabled={disabled}
            title={disabled ? busyReason : `Run ${job.name} now`}
            aria-label={`Run ${job.name}`}
            className="rounded-md bg-zinc-900 px-3 py-1 text-sm font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {job.running ? "Running…" : "Run"}
          </button>
        </Td>
      </tr>
      {error && (
        <tr>
          <td colSpan={8} className="px-3 pb-3 text-xs text-red-700 dark:text-red-400">
            {error}
          </td>
        </tr>
      )}
    </>
  );
}

/** When the active job finishes, refetch everything once so the final record shows now. */
function useRefreshWhenJobEnds(active: boolean) {
  const qc = useQueryClient();
  const was = useRef(active);
  useEffect(() => {
    if (was.current && !active) qc.invalidateQueries({ queryKey: ["data"] });
    was.current = active;
  }, [active, qc]);
}

function SectionTitle({ title, note }: { title: string; note?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-base font-semibold">{title}</h2>
      {note && <p className="text-sm text-zinc-500">{note}</p>}
    </div>
  );
}

function Banner({ children, onClose }: { children: ReactNode; onClose?: () => void }) {
  return (
    <div
      role="alert"
      className="mb-3 flex items-start justify-between gap-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
    >
      <span>{children}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Dismiss" className="font-medium">
          ×
        </button>
      )}
    </div>
  );
}

const NUMERIC = new Set(["Duration", "Requests", "Rows", "Errors"]); // right-aligned headers

function Table(props:{ head: string[]; loading?: boolean; empty?: string; children: ReactNode }) {
  const { head, loading, empty, children } = props;
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
          <tr>
            {head.map((h, i) => (
              <th
                key={i}
                className={`px-3 py-2 font-medium whitespace-nowrap ${NUMERIC.has(h) ? "text-right" : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {loading || empty ? (
            <tr>
              <td colSpan={head.length} className="px-3 py-6 text-center text-zinc-500">
                {loading ? "Loading…" : empty}
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
      </table>
    </div>
  );
}

function Td(props: { children: ReactNode; num?: boolean; mono?: boolean; title?: string }) {
  const { children, num, mono, title } = props;
  const cls = num ? "text-right tabular-nums" : mono ? "font-mono" : "";
  return (
    <td className={`px-3 py-2 whitespace-nowrap ${cls}`} title={title}>
      {children}
    </td>
  );
}
