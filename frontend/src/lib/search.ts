// Page state kept in the URL (bookmarkable, back/forward). Parsed leniently: a bad or
// hand-edited value is dropped, never an error.

export type Order = "asc" | "desc";

export const RUN_STATUSES = ["running", "ok", "partial", "failed"] as const;
export const RUN_SORTS = [
  "started_at",
  "job",
  "status",
  "duration",
  "requests",
  "rows_written",
  "errors",
] as const;
export const RUN_LIMITS = [50, 100, 200] as const;
export const PAGE_SIZES = [25, 50, 100, 200] as const;

export type RunStatus = (typeof RUN_STATUSES)[number];
export type RunSort = (typeof RUN_SORTS)[number];

export type RunsSearch = {
  job?: string;
  status?: RunStatus;
  from?: string; // YYYY-MM-DD, local, inclusive
  to?: string; // YYYY-MM-DD, local, inclusive
  sort?: RunSort;
  order?: Order;
  limit?: number;
};

export type DataSearch = {
  table?: string;
  f?: string[]; // filters as column:op:value (the API's format)
  sort?: string;
  order?: Order;
  page?: number; // 0-based
  size?: number;
};

const text = (v: unknown) => (typeof v === "string" && v !== "" ? v : undefined);
const oneOf = <T,>(v: unknown, options: readonly T[]) =>
  options.includes(v as T) ? (v as T) : undefined;
const day = (v: unknown) => {
  const s = text(v);
  return s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : undefined;
};

export function parseRunsSearch(s: Record<string, unknown>): RunsSearch {
  return {
    job: text(s.job),
    status: oneOf(s.status, RUN_STATUSES),
    from: day(s.from),
    to: day(s.to),
    sort: oneOf(s.sort, RUN_SORTS),
    order: oneOf(s.order, ["asc", "desc"] as const),
    limit: oneOf(s.limit, RUN_LIMITS),
  };
}

export function parseDataSearch(s: Record<string, unknown>): DataSearch {
  const f = Array.isArray(s.f) ? s.f.filter((x): x is string => typeof x === "string") : [];
  const page = typeof s.page === "number" && Number.isInteger(s.page) && s.page > 0 ? s.page : undefined;
  return {
    table: text(s.table),
    f: f.length ? f : undefined,
    sort: text(s.sort),
    order: oneOf(s.order, ["asc", "desc"] as const),
    page,
    size: oneOf(s.size, PAGE_SIZES),
  };
}

/** Local calendar day -> UTC instant at its start; `nextDay` gives the exclusive end. */
export function dayStart(day: string, nextDay = false): string {
  const d = new Date(`${day}T00:00:00`);
  if (nextDay) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

/** Header click: unsorted -> asc -> desc -> unsorted. */
export function nextSort(
  column: string,
  sort: string | undefined,
  order: Order | undefined,
): { sort?: string; order?: Order } {
  if (sort !== column) return { sort: column, order: "asc" };
  return order === "asc" ? { sort: column, order: "desc" } : { sort: undefined, order: undefined };
}
