const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const integer = new Intl.NumberFormat();

export const EMPTY = "—";

/** Local date and time; API timestamps are UTC with an offset. */
export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTime.format(new Date(iso)) : EMPTY;
}

export function formatCount(n: number | null | undefined): string {
  return n == null ? EMPTY : integer.format(n);
}

/** Compact duration: 850ms, 12s, 3m 05s, 1h 02m. */
export function formatDuration(ms: number): string {
  if (ms < 1_000) return `${Math.max(0, Math.round(ms))}ms`;
  const s = Math.floor(ms / 1_000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/** Duration between two ISO timestamps; open-ended runs measure to `now`. */
export function formatElapsed(start: string, end: string | null | undefined, now = Date.now()) {
  return formatDuration((end ? Date.parse(end) : now) - Date.parse(start));
}

export function formatAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return EMPTY;
  const s = Math.round((now - Date.parse(iso)) / 1_000);
  if (s < 60) return "just now";
  if (s < 3_600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3_600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}
