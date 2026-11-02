import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import type { IngestRun, Job } from "../api/data";
import { renderWithQuery } from "../test/render";
import { server } from "../test/server";
import Ingestion, { jobStatus } from "./Ingestion";

const API = "*/api/data/v1";

const run = (over: Partial<IngestRun> = {}): IngestRun => ({
  run_id: "r1",
  job: "sec_tickers",
  status: "ok",
  started_at: "2026-11-01T12:00:00Z",
  finished_at: "2026-11-01T12:00:05Z",
  requests: 1,
  rows_written: 18453,
  errors: 0,
  error_sample: null,
  ...over,
});

const job = (name: string, over: Partial<Job> = {}): Job => ({
  name,
  schedule: "0 6 * * *",
  running: false,
  last_run: null,
  last_error: null,
  ...over,
});

function serve(jobs: Job[], runs: IngestRun[] = []) {
  const started: string[] = [];
  server.use(
    http.get(`${API}/jobs`, () => HttpResponse.json(jobs)),
    http.get(`${API}/ingest-runs`, () => HttpResponse.json(runs)),
    http.get(`${API}/ops/counts`, () => HttpResponse.json({ tickers: 10430, facts: 9293 })),
    http.post(`${API}/jobs/:name/runs`, ({ params }) => {
      started.push(String(params.name));
      return HttpResponse.json(
        { job: params.name, started_at: "2026-11-01T12:00:00Z" },
        { status: 202 },
      );
    }),
  );
  return started;
}

test("lists jobs with status, last run numbers and errors", async () => {
  serve(
    [
      job("sec_tickers", { last_run: run() }),
      job("sec_frames", { last_run: run({ job: "sec_frames", status: "partial", errors: 2, error_sample: "https://sec/x: HTTP 500" }) }),
      job("sec_submissions"),
    ],
    [run()],
  );
  renderWithQuery(<Ingestion />);

  const tickers = (await screen.findAllByText("sec_tickers"))[0]!.closest("tr")!;
  expect(within(tickers).getByText("OK")).toBeInTheDocument();
  expect(within(tickers).getByText("18,453")).toBeInTheDocument();
  expect(screen.getByText("Partial")).toBeInTheDocument();
  expect(screen.getAllByText("https://sec/x: HTTP 500").length).toBeGreaterThan(0);
  expect(screen.getByText("Never run")).toBeInTheDocument();
  expect(await screen.findByText("10,430")).toBeInTheDocument();
});

test("Run starts the job", async () => {
  const started = serve([job("sec_tickers"), job("sec_frames")]);
  renderWithQuery(<Ingestion />);
  await userEvent.click(await screen.findByRole("button", { name: "Run sec_frames" }));
  await waitFor(() => expect(started).toEqual(["sec_frames"]));
});

test("all Run buttons are disabled while a job runs", async () => {
  serve([
    job("sec_tickers", { running: true, last_run: run({ status: "running", finished_at: null }) }),
    job("sec_frames"),
  ]);
  renderWithQuery(<Ingestion />);
  const frames = await screen.findByRole("button", { name: "Run sec_frames" });
  expect(frames).toBeDisabled();
  expect(frames).toHaveAttribute("title", "sec_tickers is running");
  expect(screen.getByRole("button", { name: "Run sec_tickers" })).toHaveTextContent("Running…");
});

test("a start rejected by the API shows its detail", async () => {
  serve([job("sec_tickers")]);
  server.use(
    http.post(`${API}/jobs/:name/runs`, () =>
      HttpResponse.json({ detail: "sec_frames is already running" }, { status: 409 }),
    ),
  );
  renderWithQuery(<Ingestion />);
  await userEvent.click(await screen.findByRole("button", { name: "Run sec_tickers" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not start sec_tickers: sec_frames is already running",
  );
});

test("API down shows an error instead of the table", async () => {
  server.use(
    http.get(`${API}/jobs`, () => new HttpResponse(null, { status: 502 })),
    http.get(`${API}/ingest-runs`, () => HttpResponse.json([])),
    http.get(`${API}/ops/counts`, () => HttpResponse.json({})),
  );
  renderWithQuery(<Ingestion />);
  expect(await screen.findByRole("alert")).toHaveTextContent("unreachable");
});

test("jobStatus distinguishes our run, outside runs and early failures", () => {
  expect(jobStatus(job("a", { running: true }))).toBe("running");
  expect(jobStatus(job("a", { last_run: run({ status: "running" }) }))).toBe("external");
  expect(jobStatus(job("a", { last_run: run(), last_error: "ValidationError: x" }))).toBe("failed");
  expect(jobStatus(job("a"))).toBe("never");
});
