# Recon — Ingestion v0

Goal: pull basic company data from **one source (SEC EDGAR)** into **SQLite** on a schedule, and browse it locally. Small first, extend later.

## Why SEC EDGAR First
- Free, no key, authoritative.
- One source covers universe, company metadata, filings, and financials.
- Generous limit (10 req/s).
- Only requirement: `User-Agent` header with contact email (`FINAGENT_SEC_USER_AGENT`).

## Architecture

```
jobs.yaml ──► Scheduler ──► Runner ──► Job.plan()  ──► Requests
                              │                          │
                              │                  RateLimiter + Retry
                              │                          │
                              │                       HTTP fetch
                              │                          │
                              │               Raw store (data/raw/...)
                              │                          │
                              │                     Job.parse()
                              │                          │
                              └──► ingest_runs    SQLite upsert
```

Principles:
- **Fetch and parse are separate.** Raw responses saved to disk first; parsing can be re-run without re-fetching.
- **Idempotent.** Every write is an upsert on a natural key. Re-running a job is safe.
- **Incremental.** Jobs skip work already done using `source_state` and existing rows.
- **Observable.** Every run logged to `ingest_runs`.
- **Single writer.** SQLite serializes writers (readers are unaffected in WAL mode). Scheduler and jobs run in one process.

## First Jobs

| Job | Endpoint | Writes | Schedule | Scope |
|---|---|---|---|---|
| `sec_tickers` ✅ | `https://www.sec.gov/files/company_tickers_exchange.json` | `companies`, `tickers` | Daily 06:00 | All (1 request) |
| `sec_submissions` ✅ | `https://data.sec.gov/submissions/CIK##########.json` | `companies` (enrich), `filings` | Weekdays 07:00 | Watchlist. Recent ~1000 filings only; older history pages not fetched |
| `sec_companyfacts` ✅ | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | `facts` | Weekdays 08:00 | Watchlist, only CIKs never fetched or with a 10-K/10-Q filed on/after the last fetch date |
| `sec_frames` ✅ | `https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY####Q#I.json` | `public_float` | Mondays 05:00 | All filers; last 6 quarterly frames (a filer's float lands in the frame of its fiscal Q2 end). Quarters with no data (404) are skipped |

Dependency: `sec_tickers` → `sec_submissions` → `sec_companyfacts`. Each job reads what the previous one wrote; no explicit DAG needed in v0.

**Watchlist:** `data/slice.txt` (`FINAGENT_SLICE_FILE`), one ticker per line, `#` comments allowed. Unknown tickers are logged and skipped; share classes collapse to one CIK. Run `sec_tickers` first. Expands to a market-cap-filtered universe in M3.

## Schema (SQLite)

```sql
-- Reference
CREATE TABLE companies (
  cik            VARCHAR PRIMARY KEY,   -- zero-padded 10 digits
  name           VARCHAR,
  sic            VARCHAR,
  sic_desc       VARCHAR,
  state_inc      VARCHAR,
  fiscal_year_end VARCHAR,
  updated_at     TIMESTAMP
);

-- One company can list several tickers (share classes, e.g. BRK-A / BRK-B).
CREATE TABLE tickers (
  ticker         VARCHAR PRIMARY KEY,
  cik            VARCHAR,
  exchange       VARCHAR,
  updated_at     TIMESTAMP
);

CREATE TABLE filings (
  accession_no   VARCHAR PRIMARY KEY,
  cik            VARCHAR,
  form           VARCHAR,
  filed_date     DATE,
  report_date    DATE,
  primary_doc    VARCHAR,
  url            VARCHAR,
  ingested_at    TIMESTAMP
);

CREATE TABLE facts (
  cik            VARCHAR,
  taxonomy       VARCHAR,   -- us-gaap, dei
  concept        VARCHAR,   -- Revenues, EntityCommonStockSharesOutstanding
  unit           VARCHAR,   -- USD, shares
  period_start   DATE,      -- = period_end for point-in-time values (e.g. Assets)
  period_end     DATE,
  value          DOUBLE,
  fy             INTEGER,
  fp             VARCHAR,   -- FY, Q1..Q4
  form           VARCHAR,
  accession_no   VARCHAR,
  filed_date     DATE,
  PRIMARY KEY (cik, taxonomy, concept, unit, period_start, period_end, accession_no)
);

-- Market-value proxy: shares held by non-affiliates, at each filer's fiscal Q2 end
CREATE TABLE public_float (
  cik            VARCHAR,
  period_end     DATE,
  value          DOUBLE,    -- USD
  accession_no   VARCHAR,
  location       VARCHAR,   -- e.g. US-NY, CA-ON
  PRIMARY KEY (cik, period_end)
);

-- Ops
CREATE TABLE ingest_runs (
  run_id         VARCHAR PRIMARY KEY,
  job            VARCHAR,
  started_at     TIMESTAMP,
  finished_at    TIMESTAMP,
  status         VARCHAR,   -- running | ok | partial | failed
  requests       INTEGER,
  rows_written   INTEGER,
  errors         INTEGER,
  error_sample   VARCHAR
);

CREATE TABLE source_state (
  job            VARCHAR,
  key            VARCHAR,   -- e.g. CIK
  last_fetched_at TIMESTAMP,
  last_status    INTEGER,
  raw_path       VARCHAR,
  PRIMARY KEY (job, key)
);
```

`period_start` is in the key because a 10-Q reports 3-month and year-to-date values with the same end date.

`facts` concept filter for v0 (keep table small): `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `NetIncomeLoss`, `Assets`, `Liabilities`, `StockholdersEquity`, `CashAndCashEquivalentsAtCarryingValue`, `OperatingIncomeLoss`, `EntityCommonStockSharesOutstanding`. Expand later.

## Orchestration

### Job contract
```python
class Job(Protocol):
    name: str
    source: str  # rate-limit bucket, e.g. "sec"
    keys: dict[str, list[str]]  # table -> upsert key columns

    def plan(self, db) -> Iterable[Request]: ...  # what to fetch now
    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]: ...  # table -> rows
```

### Runner (one call per job run)
1. Insert `ingest_runs` row (`running`).
2. `plan()` → list of requests.
3. For each request: rate-limit → fetch (retry 429/5xx, exponential backoff, max 3) → save raw → `parse()` → upsert → update `source_state`.
4. One failed request does not stop the run; count it and continue.
5. Close run: `ok` / `partial` / `failed`.

### Rate limiting
Minimum-interval limiter per `source`. SEC set to 5 req/s (half the limit). Retries: 429, 5xx and transport errors, backoff 1s/2s, 3 attempts. Other 4xx fail immediately.

### Scheduling — staged
| Stage | Mechanism | When to move on |
|---|---|---|
| v0 | `recon run <job>` manual CLI | Jobs work end to end |
| v1 ✅ | `recon schedule` — APScheduler reads cron from `jobs.yaml` | Need DAGs, retries UI, or multiple workers |
| v2 | Prefect or Dagster | Later |

```yaml
# src/recon/jobs.yaml — standard 5-field cron, in FINAGENT_SCHEDULE_TIMEZONE (default UTC)
jobs:
  sec_tickers:      { schedule: "0 6 * * *" }
  sec_submissions:  { schedule: "0 7 * * 1-5" }
  sec_companyfacts: { schedule: "0 8 * * 1-5" }
```

Scheduler rules:
- **One worker.** Jobs run serially: single SQLite writer, and dependents wait for inputs. Space cron times so a job finishes before the next starts.
- **No overlap, coalesced.** `max_instances=1`; missed runs collapse to one. A run missed by under 1h (e.g. laptop asleep) still fires.
- **Failures don't stop it.** A failed or non-zero run is logged; the next schedule still fires.
- **Weekdays use standard cron numbering** (0/7 = Sunday). APScheduler's own numbering differs, so the weekday field is translated.
- `recon schedule --list` previews next run times without starting.

### Reparse
`recon reparse <job>` rebuilds a job's tables from the newest saved raw response per key, with no network. Logged as `<job>:reparse`; leaves `source_state` alone. Use after changing a parser or the tracked concept list.

### Database lock
WAL mode: any number of readers (`recon status`, shells, agents) run alongside one writer. Only a second writer conflicts.
- `recon run` / `reparse`: fail at once with `database is locked by another writer`.
- Scheduled runs wait up to 5 minutes for the lock, then fail and wait for the next schedule.
- `recon status` and ad-hoc queries never wait. Leave no write transaction open in a shell.

### Raw store
`data/raw/<source>/<job>/<key>/<YYYYMMDDTHHMMSS>.json` (`FINAGENT_RAW_DIR`). Gitignored. Enables replay: `recon reparse <job>`.

## Viewing Data
- **Shell:** `python -m sqlite3 data/finagent.db` (no install; autocommit).
- **GUI:** [DB Browser for SQLite](https://sqlitebrowser.org). Use *Open Database Read Only* so it never holds the write lock.
- **CLI:** `recon status` — last run per job, row counts per table.
- **Views** (`data/views.sql`, rebuilt on connect when changed):
  - `v_recent_filings` — last 30 days of filings with ticker and name.
  - `v_small_cap_candidates` — latest public float per company, `0 < float ≤ $2B`, with primary ticker, exchange, industry. First-pass universe until prices land (M3).
  - `v_latest_financials` — one row per company: revenue, net income, operating income, assets, liabilities, equity, cash, shares outstanding. Balance-sheet items use the latest period; income items use the latest full-year 10-K value only (no quarter/YTD mixing).

## Package Layout
```
src/recon/
  design.md
  design/
  jobs.yaml
  cli.py            # run | schedule | status | reparse
  pipeline.py       # run_job / reparse_job: DB + client lifecycle, exit codes
  config.py         # env settings (FINAGENT_*)
  runner.py         # Runner, RateLimiter, retry
  scheduler.py      # APScheduler wiring
  store/
    db.py           # connection, migrations, upsert helper
    schema.sql
    views.sql
    raw.py          # raw file store
  jobs/
    base.py         # Job protocol, Request
    sec_tickers.py
    sec_submissions.py
    sec_companyfacts.py
tests/recon/
  fixtures/         # saved SEC JSON samples
```

Built (M0–M2): `cli.py`, `config.py`, `pipeline.py`, `runner.py`, `scheduler.py`, `jobs.yaml`, `timeutil.py`, `watchlist.py`, `store/{db,raw}.py`, `store/{schema,views}.sql`, `jobs/{base,sec_tickers,sec_submissions,sec_companyfacts,sec_frames}.py`.

## Milestones
| # | Deliverable | Done when |
|---|---|---|
| M0 ✅ | Skeleton, schema, `sec_tickers`, `recon run`, `recon status`, `ingest_runs` | `companies` populated; visible in a SQLite shell |
| M1 ✅ | `sec_submissions`, `sec_companyfacts`, views | Watchlist filings + financials queryable |
| M2b ✅ | `sec_frames`, `public_float`, `v_small_cap_candidates` | Universe-wide small-cap shortlist without prices |
| M2 ✅ | `recon schedule`, `reparse`, lock handling (incremental fetch for `facts` landed in M1) | Runs unattended for a week, no duplicates — trial pending |
| M3 | Prices (yfinance → Stooq fallback), `market_cap = shares × close`, small-cap universe view | Watchlist replaced by filtered universe |
| M4 | FINRA short interest, press release RSS | New tables on same runner |

## Known Limitations
- **Public float is a stale, low-biased proxy for market cap.** It excludes affiliate holdings and is dated at the filer's fiscal Q2 end — for Dec year-ends that is June of the *prior* year. Stocks that rallied since (RGTI, QUBT, BBAI) are filtered out; stocks that fell are kept. Use it to shortlist, then confirm with price × shares (M3).
- **Float coverage is partial.** ~5,100 filers have one; ~3,400 tickered companies don't (funds, ETFs, many foreign filers, new listings).
- **Float tail is noisy.** Shells and SPACs report tiny or wrong-scale values (91 candidates under $1M). Add a floor in queries if wanted; the view has none by design.
- **Multi-class share counts.** `EntityCommonStockSharesOutstanding` in companyfacts drops per-class values. Multi-class issuers show a stale or single-class number (SOUN) or none (CLOV). M3 market cap needs another shares source (e.g. yfinance) or the cover page of the filing.
- **Mixed fiscal years in one row.** `annual_period_end` is the latest across income metrics; a metric a company stopped reporting under a tracked concept can lag behind.
- **Changed filers.** Companies whose CIK changed after a merger (e.g. FUBO) can show older annual data.
- **Concept coverage.** Companies tagging revenue with a concept outside the tracked list show NULL. Add the concept, clear that job's `source_state`, rerun.

## Decisions
- **Small-cap range:** market cap ≤ $2B, no lower bound (micro-caps included). Applied in M3 once `market_cap` exists.

## Open Questions
- Include OTC listings?
- Where does it run: local machine first, then a container (Dockerfile exists)?
