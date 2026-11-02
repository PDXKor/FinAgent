import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { renderRoute } from "../test/render";
import { server } from "../test/server";
import { splitFilter } from "./DataViewer";

const API = "*/api/data/v1";

const TABLES = [
  {
    name: "tickers",
    kind: "table",
    columns: [
      { name: "ticker", type: "VARCHAR" },
      { name: "cik", type: "VARCHAR" },
      { name: "exchange", type: "VARCHAR" },
    ],
  },
  {
    name: "facts",
    kind: "table",
    columns: [
      { name: "concept", type: "VARCHAR" },
      { name: "value", type: "DOUBLE" },
      { name: "fy", type: "INTEGER" },
    ],
  },
  { name: "v_small_cap_candidates", kind: "view", columns: [{ name: "ticker", type: null }] },
];

const TICKERS = [
  { ticker: "AAPL", cik: "0000320193", exchange: "Nasdaq" },
  { ticker: "ZZZ", cik: "0000000004", exchange: null },
];

function serve(total = 2) {
  const queries: { table: string; params: URLSearchParams }[] = [];
  server.use(
    http.get(`${API}/health`, () => HttpResponse.json({ status: "ok" })),
    http.get(`${API}/tables`, () => HttpResponse.json(TABLES)),
    http.get(`${API}/tables/:name/rows`, ({ params, request }) => {
      const url = new URL(request.url);
      queries.push({ table: String(params.name), params: url.searchParams });
      const table = TABLES.find((t) => t.name === params.name)!;
      const rows =
        params.name === "facts"
          ? [{ concept: "Revenues", value: 9500000000, fy: 2024 }]
          : params.name === "tickers"
            ? TICKERS
            : [];
      return HttpResponse.json({
        table: params.name,
        columns: table.columns,
        rows,
        total,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
  );
  return queries;
}

const last = (q: { params: URLSearchParams }[]) => q.at(-1)!.params;

test("lists tables and views; picking one shows its rows", async () => {
  serve();
  renderRoute("/data");
  const nav = await screen.findByRole("navigation", { name: "Tables and views" });
  expect(within(nav).getByText("Views")).toBeInTheDocument();
  expect(screen.getByText("Pick a table or view to browse its rows.")).toBeInTheDocument();

  await userEvent.click(await within(nav).findByRole("button", { name: "tickers" }));
  expect(await screen.findByText("AAPL")).toBeInTheDocument();
  expect(screen.getByText("2 rows")).toBeInTheDocument();
  // Null renders as a dash, not "null"
  const zzz = screen.getByText("ZZZ").closest("tr")!;
  expect(within(zzz).getByText("—")).toBeInTheDocument();
});

test("numbers: large values grouped, years not", async () => {
  serve();
  renderRoute("/data?table=facts");
  expect(await screen.findByText("9,500,000,000")).toBeInTheDocument();
  expect(screen.getByText("2024")).toBeInTheDocument();
});

test("adding and removing filters", async () => {
  const queries = serve();
  const { router } = renderRoute("/data?table=tickers");
  await screen.findByText("AAPL");

  await userEvent.selectOptions(screen.getByLabelText("Filter column"), "exchange");
  await userEvent.selectOptions(screen.getByLabelText("Filter condition"), "eq");
  await userEvent.type(screen.getByLabelText("Filter value"), "NYSE:A{enter}");
  await waitFor(() => expect(last(queries).getAll("filter")).toEqual(["exchange:eq:NYSE:A"]));
  expect(router.state.location.search).toMatchObject({ f: ["exchange:eq:NYSE:A"] });
  expect(screen.getByText("2 matching rows")).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Filter condition"), "null");
  expect(screen.queryByLabelText("Filter value")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add filter" }));
  await waitFor(() =>
    expect(last(queries).getAll("filter")).toEqual(["exchange:eq:NYSE:A", "exchange:null:"]),
  );

  await userEvent.click(screen.getByRole("button", { name: /Remove filter exchange = NYSE:A/ }));
  await waitFor(() => expect(last(queries).getAll("filter")).toEqual(["exchange:null:"]));
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(last(queries).getAll("filter")).toEqual([]));
});

test("header clicks cycle sort: asc, desc, none", async () => {
  const queries = serve();
  renderRoute("/data?table=tickers");
  await screen.findByText("AAPL");
  const header = within(screen.getByRole("table")).getByRole("button", { name: /^ticker/ });

  await userEvent.click(header);
  await waitFor(() => expect(last(queries).get("order")).toBe("asc"));
  expect(last(queries).get("sort")).toBe("ticker");
  expect(header.closest("th")).toHaveAttribute("aria-sort", "ascending");

  await userEvent.click(header);
  await waitFor(() => expect(last(queries).get("order")).toBe("desc"));

  await userEvent.click(header);
  await waitFor(() => expect(last(queries).get("sort")).toBeNull());
});

test("paging moves the offset and page size resets it", async () => {
  const queries = serve(120);
  renderRoute("/data?table=tickers");
  await screen.findByText("AAPL");
  expect(last(queries).get("limit")).toBe("50");
  expect(screen.getByText("1 / 3")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(last(queries).get("offset")).toBe("50"));

  await userEvent.selectOptions(screen.getByLabelText("Rows per page"), "25");
  await waitFor(() => expect(last(queries).get("limit")).toBe("25"));
  expect(last(queries).get("offset")).toBe("0");
});

test("switching tables clears filters and sort", async () => {
  const queries = serve();
  renderRoute("/data?table=tickers&sort=ticker&order=desc&f=%5B%22ticker%3Acontains%3AA%22%5D");
  await screen.findByText("AAPL");
  expect(last(queries).getAll("filter")).toEqual(["ticker:contains:A"]);
  const nav = screen.getByRole("navigation", { name: "Tables and views" });
  await userEvent.click(within(nav).getByRole("button", { name: "facts" }));
  await waitFor(() => expect(queries.at(-1)!.table).toBe("facts"));
  expect(last(queries).getAll("filter")).toEqual([]);
  expect(last(queries).get("sort")).toBeNull();
});

test("an API error (e.g. a bad filter in the URL) is shown", async () => {
  serve();
  server.use(
    http.get(`${API}/tables/:name/rows`, () =>
      HttpResponse.json({ detail: "unknown column 'nope'" }, { status: 422 }),
    ),
  );
  renderRoute("/data?table=tickers&f=%5B%22nope%3Aeq%3A1%22%5D");
  expect(await screen.findByRole("alert")).toHaveTextContent("unknown column 'nope'");
});

test("splitFilter keeps colons in the value", () => {
  expect(splitFilter("url:contains:https://sec.gov")).toEqual(["url", "contains", "https://sec.gov"]);
  expect(splitFilter("exchange:null:")).toEqual(["exchange", "null", ""]);
});
