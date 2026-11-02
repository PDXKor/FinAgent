export type Status = "running" | "external" | "ok" | "partial" | "failed" | "never";

const STYLES: Record<Status, [string, string]> = {
  running: ["Running", "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300"],
  external: ["Running elsewhere", "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300"],
  ok: ["OK", "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"],
  partial: ["Partial", "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"],
  failed: ["Failed", "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"],
  never: ["Never run", "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"],
};

const HINTS: Partial<Record<Status, string>> = {
  external: "Started by the CLI or scheduler, or interrupted when the API stopped.",
  partial: "Some requests failed; the rest were saved.",
};

/** Maps an ingest_runs status (or a UI state) to a badge. */
export function toStatus(raw: string | null | undefined): Status {
  return raw && raw in STYLES ? (raw as Status) : "never";
}

export default function StatusBadge({ status }: { status: Status }) {
  const [label, style] = STYLES[status];
  const live = status === "running" || status === "external";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${style}`}
      title={HINTS[status]}
    >
      {live && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {label}
    </span>
  );
}
