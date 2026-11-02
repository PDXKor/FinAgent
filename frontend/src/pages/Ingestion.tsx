import { useQueryClient } from "@tanstack/react-query";
import { getRouteApi } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import type { IngestRun, Job } from "../api/data";
import { useCounts, useIngestRuns, useJobs, useStartJob } from "../api/queries";
import StatusBadge, { toStatus, type Status } from "../components/StatusBadge";
import { Banner, BUTTON, BUTTON_QUIET, Field, INPUT, SectionTitle, Table, Td, Th } from "../components/ui";
import { EMPTY, formatAgo, formatCount, formatDateTime, formatElapsed } from "../lib/format";
import {
  dayStart,
  RUN_LIMITS,
  RUN_STATUSES,
  type RunSort,
  type RunsSearch,
} from "../lib/search";
import { useNow } from "../lib/useNow";

const route = getRouteApi("/");

/** Badge state for a job: its own process state first, then its last run record. */
export function jobStatus(job: Job): Status {
  if (job.running) return "running";
  if (job.last_error) return "failed";
  const s = job.last_run?.status;
  return s === "running" ? "external" : toStatus(s);
}

/** A `running` record is live only if this API is running that job now. */
function runStatus(run: IngestRun, active: Job | undefined): Status {
  if (run.status !== "running") return toStatus(run.status);
  return active && run.run_id === active.last_run?.run_id ? "running" : "external";
}

export default function Ingestion() {
  const jobs = useJobs();
  const active = jobs.data?.find((j) => j.running);
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
            columns={8}
            loading={jobs.isPending}
            head={
              <>
                <Th>Job</Th>
                <Th>Status</Th>
                <Th>Last run</Th>
                <Th num>Duration</Th>
                <Th num>Requests</Th>
                <Th num>Rows</Th>
                <Th num>Errors</Th>
                <Th>{""}</Th>
              </>
            }
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

      <RecentRuns jobs={jobs.data ?? []} active={active} now={now} />
    </div>
  );
}

const RUN_COLUMNS: { label: string; sort?: RunSort; num?: boolean }[] = [
  { label: "Started", sort: "started_at" },
  { label: "Job", sort: "job" },
  { label: "Status", sort: "status" },
  { label: "Duration", sort: "duration", num: true },
  { label: "Requests", sort: "requests", num: true },
  { label: "Rows", sort: "rows_written", num: true },
  { label: "Errors", sort: "errors", num: true },
  { label: "Error" },
];

function RecentRuns({ jobs, active, now }: { jobs: Job[]; active?: Job; now: number }) {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const set = (patch: Partial<RunsSearch>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true });

  const sort = search.sort ?? "started_at";
  const order = search.order ?? "desc";
  const runs = useIngestRuns(
    {
      job: search.job,
      status: search.status,
      since: search.from ? dayStart(search.from) : undefined,
      until: search.to ? dayStart(search.to, true) : undefined,
      sort,
      order,
      limit: search.limit ?? RUN_LIMITS[0],
    },
    !!active,
  );
  const filtered = !!(search.job || search.status || search.from || search.to);

  // Header click: new column -> descending (newest/largest first), then flip.
  const sortBy = (column: RunSort) =>
    set({ sort: column, order: sort === column && order === "desc" ? "asc" : "desc" });

  return (
    <section>
      <SectionTitle title="Recent runs" />
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label="Job">
          <select
            aria-label="Filter by job"
            className={INPUT}
            value={search.job ?? ""}
            onChange={(e) => set({ job: e.target.value || undefined })}
          >
            <option value="">All jobs</option>
            {jobs.map((j) => (
              <option key={j.name} value={j.name}>
                {j.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select
            aria-label="Filter by status"
            className={INPUT}
            value={search.status ?? ""}
            onChange={(e) =>
              set({ status: (e.target.value || undefined) as RunsSearch["status"] })
            }
          >
            <option value="">Any status</option>
            {RUN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label="From">
          <input
            type="date"
            aria-label="Started from"
            className={INPUT}
            value={search.from ?? ""}
            max={search.to}
            onChange={(e) => set({ from: e.target.value || undefined })}
          />
        </Field>
        <Field label="To">
          <input
            type="date"
            aria-label="Started to"
            className={INPUT}
            value={search.to ?? ""}
            min={search.from}
            onChange={(e) => set({ to: e.target.value || undefined })}
          />
        </Field>
        <Field label="Show">
          <select
            aria-label="Rows to show"
            className={INPUT}
            value={search.limit ?? RUN_LIMITS[0]}
            onChange={(e) => set({ limit: Number(e.target.value) })}
          >
            {RUN_LIMITS.map((n) => (
              <option key={n} value={n}>
                {n} rows
              </option>
            ))}
          </select>
        </Field>
        {(filtered || search.sort) && (
          <button
            type="button"
            className={BUTTON_QUIET}
            onClick={() => navigate({ search: {}, replace: true })}
          >
            Clear
          </button>
        )}
      </div>
      {runs.isError ? (
        <Banner>{runs.error.message}</Banner>
      ) : (
        <Table
          columns={RUN_COLUMNS.length}
          loading={runs.isPending}
          empty={runs.data?.length === 0 ? (filtered ? "No runs match." : "No runs yet.") : undefined}
          head={RUN_COLUMNS.map((c) => (
            <Th
              key={c.label}
              num={c.num}
              sorted={c.sort === sort ? order : undefined}
              onSort={c.sort ? () => sortBy(c.sort!) : undefined}
            >
              {c.label}
            </Th>
          ))}
        >
          {runs.data?.map((run) => (
            <tr key={run.run_id}>
              <Td title={run.started_at}>{formatDateTime(run.started_at)}</Td>
              <Td mono>{run.job}</Td>
              <Td>
                <StatusBadge status={runStatus(run, active)} />
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
            className={BUTTON}
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
