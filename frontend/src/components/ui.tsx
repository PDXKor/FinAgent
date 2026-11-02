import type { ReactNode } from "react";

import type { Order } from "../lib/search";

export const INPUT =
  "rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900";
export const BUTTON =
  "rounded-md bg-zinc-900 px-3 py-1 text-sm font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300";
export const BUTTON_QUIET =
  "rounded-md border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800";

export function SectionTitle({ title, note }: { title: string; note?: ReactNode }) {
  return (
    <div className="mb-3">
      <h2 className="text-base font-semibold">{title}</h2>
      {note && <p className="text-sm text-zinc-500">{note}</p>}
    </div>
  );
}

export function Banner({ children, onClose }: { children: ReactNode; onClose?: () => void }) {
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

/** Header cell. With `onSort`, a button that shows and cycles the sort. */
export function Th(props: {
  children: ReactNode;
  num?: boolean;
  sorted?: Order;
  onSort?: () => void;
}) {
  const { children, num, sorted, onSort } = props;
  const arrow = sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "";
  const aria = sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined;
  return (
    <th
      aria-sort={onSort ? (aria ?? "none") : undefined}
      className={`px-3 py-2 font-medium whitespace-nowrap ${num ? "text-right" : ""}`}
    >
      {onSort ? (
        <button
          type="button"
          onClick={onSort}
          className={`inline-flex items-center gap-1 hover:text-zinc-900 dark:hover:text-zinc-100 ${sorted ? "text-zinc-900 dark:text-zinc-100" : ""}`}
        >
          {children}
          <span className="w-2 text-[10px]">{arrow}</span>
        </button>
      ) : (
        children
      )}
    </th>
  );
}

export function Table(props: {
  head: ReactNode;
  columns: number;
  loading?: boolean;
  empty?: string;
  children: ReactNode;
}) {
  const { head, columns, loading, empty, children } = props;
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
          <tr>{head}</tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {loading || empty ? (
            <tr>
              <td colSpan={columns} className="px-3 py-6 text-center text-zinc-500">
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

export function Td(props: { children: ReactNode; num?: boolean; mono?: boolean; title?: string }) {
  const { children, num, mono, title } = props;
  const cls = num ? "text-right tabular-nums" : mono ? "font-mono" : "";
  return (
    <td className={`px-3 py-2 whitespace-nowrap ${cls}`} title={title}>
      {children}
    </td>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-500">
      {label}
      {children}
    </label>
  );
}
