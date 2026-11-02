import { getRouteApi } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import type { components } from "../api/generated/data";
import { useTables, useTableRows } from "../api/queries";
import { Banner, BUTTON, BUTTON_QUIET, Field, INPUT, Table, Th } from "../components/ui";
import { formatCell, formatCount } from "../lib/format";
import { nextSort, PAGE_SIZES, type DataSearch } from "../lib/search";

type TableInfo = components["schemas"]["TableInfo"];

const route = getRouteApi("/data");

export const OPS = [
  { op: "contains", label: "contains" },
  { op: "eq", label: "=" },
  { op: "ne", label: "≠" },
  { op: "starts", label: "starts with" },
  { op: "gt", label: ">" },
  { op: "gte", label: "≥" },
  { op: "lt", label: "<" },
  { op: "lte", label: "≤" },
  { op: "null", label: "is empty" },
  { op: "notnull", label: "is not empty" },
] as const;
const NO_VALUE = new Set(["null", "notnull"]);
const opLabel = (op: string) => OPS.find((o) => o.op === op)?.label ?? op;

/** "col:op:value" -> parts; the value may itself contain colons. */
export function splitFilter(f: string): [string, string, string] {
  const [col = "", op = "", ...rest] = f.split(":");
  return [col, op, rest.join(":")];
}

export default function DataViewer() {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const set = (patch: Partial<DataSearch>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true });

  const tables = useTables();
  const info = tables.data?.find((t) => t.name === search.table);
  const size = search.size ?? PAGE_SIZES[1];
  const page = search.page ?? 0;
  const rows = useTableRows(
    info && {
      table: info.name,
      filter: search.f,
      sort: search.sort,
      order: search.order,
      limit: size,
      offset: page * size,
    },
  );

  // A new table starts clean; keep the page size.
  const pick = (name: string) => navigate({ search: { table: name, size: search.size } });

  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <aside className="md:w-56 md:shrink-0">
        {tables.isError ? (
          <Banner>{tables.error.message}</Banner>
        ) : (
          <TablePicker tables={tables.data ?? []} current={search.table} onPick={pick} />
        )}
      </aside>

      <section className="min-w-0 flex-1">
        {!search.table ? (
          <p className="text-sm text-zinc-500">Pick a table or view to browse its rows.</p>
        ) : tables.isSuccess && !info ? (
          <Banner>Unknown table {search.table}.</Banner>
        ) : info ? (
          <>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-base font-semibold">
                <span className="font-mono">{info.name}</span>
                <span className="ml-2 text-xs font-normal text-zinc-500">{info.kind}</span>
              </h2>
              {rows.data && (
                <span className="text-sm text-zinc-500">
                  {formatCount(rows.data.total)} {search.f ? "matching " : ""}rows
                </span>
              )}
            </div>

            <FilterBuilder
              key={info.name}
              columns={info.columns.map((c) => c.name)}
              onAdd={(f) => set({ f: [...(search.f ?? []), f], page: undefined })}
            />
            {search.f && (
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {search.f.map((f, i) => {
                  const [col, op, value] = splitFilter(f);
                  return (
                    <span
                      key={`${f}-${i}`}
                      className="inline-flex items-center gap-1 rounded-full bg-zinc-200 px-2.5 py-0.5 text-xs dark:bg-zinc-800"
                    >
                      <span className="font-mono">{col}</span> {opLabel(op)}
                      {!NO_VALUE.has(op) && <span className="font-medium">“{value}”</span>}
                      <button
                        type="button"
                        aria-label={`Remove filter ${col} ${opLabel(op)} ${value}`}
                        className="ml-1 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
                        onClick={() => {
                          const rest = search.f!.filter((_, j) => j !== i);
                          set({ f: rest.length ? rest : undefined, page: undefined });
                        }}
                      >
                        ×
                      </button>
                    </span>
                  );
                })}
                <button
                  type="button"
                  className="text-xs text-zinc-500 underline"
                  onClick={() => set({ f: undefined, page: undefined })}
                >
                  Clear filters
                </button>
              </div>
            )}

            {rows.isError ? (
              <Banner>{rows.error.message}</Banner>
            ) : (
              <RowsTable info={info} search={search} data={rows.data} loading={rows.isPending} set={set} />
            )}

            {rows.data && (
              <Pager
                page={page}
                size={size}
                shown={rows.data.rows.length}
                total={rows.data.total}
                onPage={(p) => set({ page: p || undefined })}
                onSize={(s) => set({ size: s, page: undefined })}
              />
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}

function TablePicker(props: { tables: TableInfo[]; current?: string; onPick: (name: string) => void }) {
  const { tables, current, onPick } = props;
  const groups = [
    ["Tables", tables.filter((t) => t.kind === "table")],
    ["Views", tables.filter((t) => t.kind === "view")],
  ] as const;
  return (
    <>
      <select
        aria-label="Table"
        className={`${INPUT} w-full md:hidden`}
        value={current ?? ""}
        onChange={(e) => e.target.value && onPick(e.target.value)}
      >
        <option value="">Choose a table…</option>
        {groups.map(([label, list]) => (
          <optgroup key={label} label={label}>
            {list.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <nav className="hidden space-y-4 md:block" aria-label="Tables and views">
        {groups.map(([label, list]) => (
          <div key={label}>
            <h3 className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">{label}</h3>
            <ul>
              {list.map((t) => (
                <li key={t.name}>
                  <button
                    type="button"
                    onClick={() => onPick(t.name)}
                    aria-current={t.name === current ? "page" : undefined}
                    className={`w-full truncate rounded px-2 py-1 text-left font-mono text-sm hover:bg-zinc-200 dark:hover:bg-zinc-800 ${t.name === current ? "bg-zinc-200 font-medium dark:bg-zinc-800" : ""}`}
                  >
                    {t.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );
}

function FilterBuilder({ columns, onAdd }: { columns: string[]; onAdd: (f: string) => void }) {
  const [col, setCol] = useState(columns[0] ?? "");
  const [op, setOp] = useState<string>("contains");
  const [value, setValue] = useState("");
  const needsValue = !NO_VALUE.has(op);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!col || (needsValue && value === "")) return;
    onAdd(`${col}:${op}:${needsValue ? value : ""}`);
    setValue("");
  };

  return (
    <form onSubmit={submit} className="mb-3 flex flex-wrap items-end gap-2" aria-label="Add filter">
      <Field label="Column">
        <select aria-label="Filter column" className={INPUT} value={col} onChange={(e) => setCol(e.target.value)}>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Condition">
        <select aria-label="Filter condition" className={INPUT} value={op} onChange={(e) => setOp(e.target.value)}>
          {OPS.map((o) => (
            <option key={o.op} value={o.op}>
              {o.label}
            </option>
          ))}
        </select>
      </Field>
      {needsValue && (
        <Field label="Value">
          <input
            aria-label="Filter value"
            className={`${INPUT} w-48`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="text, number or date"
          />
        </Field>
      )}
      <button type="submit" className={BUTTON} disabled={needsValue && value === ""}>
        Add filter
      </button>
    </form>
  );
}

function RowsTable(props: {
  info: TableInfo;
  search: DataSearch;
  data?: components["schemas"]["TableRows"];
  loading: boolean;
  set: (patch: Partial<DataSearch>) => void;
}) {
  const { info, search, data, loading, set } = props;
  const names = info.columns.map((c) => c.name);
  // Right-align columns whose values on this page are numbers.
  const numeric = new Set(
    names.filter((n) => {
      const vals = (data?.rows ?? []).map((r) => r[n]).filter((v) => v != null);
      return vals.length > 0 && vals.every((v) => typeof v === "number");
    }),
  );
  return (
    <Table
      columns={names.length}
      loading={loading}
      empty={data?.rows.length === 0 ? (search.f ? "No rows match." : "No rows.") : undefined}
      head={names.map((n) => (
        <Th
          key={n}
          num={numeric.has(n)}
          sorted={search.sort === n ? search.order : undefined}
          onSort={() => set({ ...nextSort(n, search.sort, search.order), page: undefined })}
        >
          <span className="font-mono">{n}</span>
        </Th>
      ))}
    >
      {data?.rows.map((row, i) => (
        <tr key={i}>
          {names.map((n) => {
            const text = formatCell(row[n]);
            return (
              <td
                key={n}
                title={text.length > 40 ? text : undefined}
                className={`max-w-[22rem] truncate px-3 py-1.5 whitespace-nowrap ${numeric.has(n) ? "text-right tabular-nums" : ""} ${row[n] == null ? "text-zinc-400" : ""}`}
              >
                {text}
              </td>
            );
          })}
        </tr>
      ))}
    </Table>
  );
}

function Pager(props: {
  page: number;
  size: number;
  shown: number;
  total: number;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
}) {
  const { page, size, shown, total, onPage, onSize } = props;
  const first = total === 0 ? 0 : page * size + 1;
  const last = page * size + shown;
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-500">
      <span>
        Rows {formatCount(first)}–{formatCount(last)} of {formatCount(total)}
      </span>
      <div className="flex items-center gap-2">
        <select
          aria-label="Rows per page"
          className={INPUT}
          value={size}
          onChange={(e) => onSize(Number(e.target.value))}
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </select>
        <button type="button" className={BUTTON_QUIET} disabled={page === 0} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span className="tabular-nums">
          {page + 1} / {pages}
        </span>
        <button
          type="button"
          className={BUTTON_QUIET}
          disabled={page + 1 >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
