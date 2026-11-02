# Recon — Data Model

What is stored, where it comes from, and what it means. Row counts are a snapshot from 2026-10-31 (12-ticker watchlist). Schema source of truth: [`data/schema.sql`](../../data/schema.sql), [`data/views.sql`](../../data/views.sql).

## Files (`data/`, gitignored)

| Path | What | Size | Regenerable |
|---|---|---|---|
| `finagent.db` | Parsed tables and views (SQLite, WAL: also `-wal`, `-shm` while open) | 5.9 MB | Yes, from raw via `recon reparse` |
| `raw/` | Unmodified SEC responses, one file per fetch | 44 MB | Yes, by refetching |
| `slice.txt` | Watchlist: one ticker per line, `#` comments | 113 B | No, hand-edited |
| `finagent.duckdb`, `finagent.v2-backup.duckdb` | Pre-SQLite DuckDB files | 8.1 MB, 3.3 MB | Obsolete; safe to delete |

Paths set by `FINAGENT_DB_PATH`, `FINAGENT_RAW_DIR`, `FINAGENT_SLICE_FILE`.

## Lineage

```
SEC company_tickers_exchange.json ──► raw/sec/sec_tickers/all/<ts>.json ──► companies, tickers
SEC submissions/CIK<cik>.json     ──► raw/sec/sec_submissions/<cik>/<ts>.json ──► companies (enrich), filings
SEC companyfacts/CIK<cik>.json    ──► raw/sec/sec_companyfacts/<cik>/<ts>.json ──► facts
SEC frames/dei/EntityPublicFloat  ──► raw/sec/sec_frames/EntityPublicFloat_<frame>/<ts>.json ──► public_float
every job run ──► ingest_runs, source_state
```

All data comes from SEC EDGAR today. See [data-sources.md](data-sources.md) for planned sources.

## Relationships

```
companies (cik) ─┬─< tickers.cik
                 ├─< filings.cik
                 ├─< public_float.cik
                 └─< facts.cik
filings.accession_no ··· facts.accession_no   (same filing; join is by value)
```

No foreign keys are enforced. `cik` is the join key everywhere.

## Tables

### companies — 8,023 rows
One row per SEC registrant. Key: `cik`.

| Column | Meaning | Source |
|---|---|---|
| `cik` | 10-digit zero-padded SEC ID, text | tickers file, submissions |
| `name` | Registered name, often upper case | tickers file, then submissions |
| `sic`, `sic_desc` | Industry code and label (`3620`, Electrical Industrial Apparatus) | submissions |
| `state_inc` | State or country of incorporation | submissions |
| `fiscal_year_end` | `MMDD` text (`1231`, `0928`) | submissions |
| `updated_at` | Last write, UTC | runner |

All 8,023 have `cik` and `name`. Only the 12 watchlist companies have `sic`, `state_inc`, `fiscal_year_end`.

### tickers — 10,430 rows
One row per listed symbol. Key: `ticker`.

| Column | Meaning |
|---|---|
| `ticker` | Symbol (`PLUG`, `BRK-B`) |
| `cik` | Owning company |
| `exchange` | As reported by SEC |
| `updated_at` | Last write, UTC |

- 1,441 companies list more than one ticker (share classes).
- Every company has at least one ticker.
- Exchanges: Nasdaq 4,357, NYSE 3,269, **OTC 2,577**, CBOE 44, TXSE 12, null 171.
- The universe already includes OTC names; filtering them is a later choice.

### filings — 8,886 rows (12 companies)
One row per SEC filing. Key: `accession_no`.

| Column | Meaning |
|---|---|
| `accession_no` | Filing ID, `0001104659-26-022286`. Prefix is the filer agent, not always the company |
| `cik` | Company |
| `form` | Form type (see below) |
| `filed_date` | Date submitted to SEC |
| `report_date` | Period or event date the filing covers. Null for 2,607 rows, e.g. Form 144, CORRESP, proxy material (DEFA14A), prospectuses (424B3), 13G/A |
| `primary_doc` | Main document file name |
| `url` | Built link to the primary document on sec.gov |
| `ingested_at` | When we stored it, UTC |

- Range: 2010-02-25 to 2026-10-30. Only each company's ~1,000 most recent filings are fetched.
- Metadata only. No filing text, exhibits, or Form 4 contents (who traded, how much).
- Most common forms:

| Form | Count | Meaning |
|---|---:|---|
| 4 | 3,317 | Insider trade report |
| 8-K | 1,207 | Material event |
| 6-K | 741 | Foreign issuer report |
| 144 | 665 | Notice of insider sale |
| 3 | 309 | Insider initial holdings |
| 10-Q | 267 | Quarterly report |
| 10-K | 85 | Annual report |

### facts — 9,293 rows (12 companies)
One row per reported XBRL number. Key: `cik, taxonomy, concept, unit, period_start, period_end, accession_no`.

| Column | Meaning |
|---|---|
| `taxonomy` | `us-gaap` (US GAAP), `dei` (cover page), `ifrs-full` (foreign filers) |
| `concept` | Line item, e.g. `NetIncomeLoss` |
| `unit` | `USD` or `shares` |
| `period_start`, `period_end` | Period measured. For point-in-time values (Assets), `period_start = period_end` |
| `value` | Number in `unit`, full dollars (not thousands) |
| `fy`, `fp` | Fiscal year and period (`FY`, `Q1`–`Q3`) **of the filing that reported it**, not of the value |
| `form` | Filing form: 10-K 2,046, 10-Q 6,442, 10-K/A 270, 40-F 175, others small |
| `accession_no` | Filing that reported it |
| `filed_date` | Filing date |

Tracked concepts only:

| Concept | Rows |
|---|---:|
| NetIncomeLoss | 1,628 |
| StockholdersEquity | 1,544 |
| OperatingIncomeLoss | 1,363 |
| CashAndCashEquivalentsAtCarryingValue | 1,153 |
| Assets | 915 (887 us-gaap, 28 ifrs-full) |
| Liabilities | 883 (855 us-gaap, 28 ifrs-full) |
| Revenues | 741 |
| RevenueFromContractWithCustomerExcludingAssessedTax | 440 |
| RevenueFromContractWithCustomerIncludingAssessedTax | 249 |
| EntityCommonStockSharesOutstanding (dei) | 377 |

Reading facts correctly:
- **One period, many rows.** A number is repeated in each later filing that shows it as a comparative or restates it (2,473 such repeats). For the latest figure, take the highest `filed_date`.
- **Durations mix.** A 10-Q holds a 3-month and a year-to-date value with the same end date. Filter by `period_end - period_start` (about 90, 180, 270, 365 days).
- **Share counts for multi-class companies are unreliable.** See [ingestion.md](ingestion.md) known limitations.
- **Revenue has three concepts.** Companies pick one; views merge them.

### public_float — 5,164 rows (5,120 companies)
Public float: market value of shares held by non-affiliates, as reported on the cover of a 10-K. Key: `cik, period_end`. Covers all filers, not just the watchlist. Figures from the first verified run; the live database gets them on its first `sec_frames` run.

| Column | Meaning |
|---|---|
| `cik` | Company |
| `period_end` | Date the float was measured: the filer's fiscal Q2 end (`2025-06-30` for Dec year-ends, `2025-03-28` for Apple) |
| `value` | USD. Can be 0 (no public market) or implausibly small for shells/SPACs |
| `accession_no` | Filing that reported it; the latest if amended |
| `location` | SEC business location (`US-NY`, `CA-ON`) |

- A company has one row per year it reported; the view takes the latest.
- Dates run 2025-05 to 2026-10. Stale by up to 16 months for Dec year-ends.
- ~3,400 tickered companies have no float (ETFs, funds, many foreign filers, new listings).

### ingest_runs — 4 rows
One row per job run. Key: `run_id` (uuid).

| Column | Meaning |
|---|---|
| `job` | Job name; reparses are `<job>:reparse` |
| `started_at`, `finished_at` | UTC |
| `status` | `running`, `ok`, `partial` (some requests failed), `failed` |
| `requests`, `rows_written`, `errors` | Counts. `rows_written` counts rows upserted, not net-new |
| `error_sample` | First error, up to 500 chars |

A run stuck at `running` means the process died mid-run.

### source_state — 25 rows
Latest fetch per unit of work. Key: `job, key`.

| Column | Meaning |
|---|---|
| `job`, `key` | Job and its unit (`all`, or a CIK) |
| `last_fetched_at` | UTC; drives `sec_companyfacts` incremental logic |
| `last_status` | HTTP status of the last successful fetch |
| `raw_path` | Raw file from that fetch |

Written on successful fetches only. Clearing a job's rows forces a full refetch.

## Views

| View | Rows | What |
|---|---|---|
| `v_small_cap_candidates` | companies with latest float `0 < f ≤ $2B` (2,993 in first run: Nasdaq 1,743, NYSE 715, OTC 509, other 26) | `ticker, name, exchange, public_float, float_date, sic_desc, location, cik`; largest float first |
| `v_recent_filings` | filings from the last 30 days | `filed_date, ticker, name, form, report_date, url`; one ticker per company (alphabetically first) |
| `v_latest_financials` | one per company with facts | `revenue, net_income, operating_income, assets, liabilities, equity, cash, shares_outstanding, balance_sheet_date, annual_period_end` |

`v_latest_financials` rules: balance-sheet items use the latest period from any filing; income items use the latest 10-K value covering 350–380 days. Metrics can come from different years; see known limitations.

## Raw files — `raw/sec/<job>/<key>/<YYYYMMDDTHHMMSS>.json`

SEC JSON saved exactly as received, UTC timestamp.

| Job | Files | Size | Per file | Content |
|---|---:|---:|---|---|
| `sec_companyfacts` | 24 | 41 MB | ~1.7 MB | Every XBRL fact the company ever reported, all concepts. We keep 10 of them in `facts` |
| `sec_submissions` | 12 | 1.5 MB | ~125 KB | Company profile plus recent-filings arrays |
| `sec_tickers` | 3 | 1.6 MB | ~520 KB | Entire SEC ticker list |
| `sec_frames` | 6 per run | ~0.7 MB per run | ~115 KB | One quarterly frame of public float for all filers |

- Raw holds far more than the tables do. Adding a concept or column needs `recon reparse`, not a refetch.
- Files accumulate: every fetch adds one, and nothing is pruned. Unchanged ticker lists are stored repeatedly. At ~1.7 MB per company, a 1,000-company watchlist adds ~1.7 GB per full refresh. A retention rule is needed before scaling.
- `reparse` reads only the newest file per key.

## Watchlist — `slice.txt`

```
# Starter watchlist: one ticker per line. Edit freely.
BBAI
SOUN
...
```

12 tickers today. Drives `sec_submissions` and `sec_companyfacts`; `sec_tickers` ignores it. Tickers resolve through `tickers`; unknown ones are logged and skipped.

## Conventions

- `cik`: text, zero-padded to 10 digits. Never an integer.
- Dates: ISO text (`YYYY-MM-DD`) from SEC as-is. Timestamps: naive UTC, ISO text (`YYYY-MM-DD HH:MM:SS`). SQLite has no date type: query results are strings; compare and sort as text, use `date()`/`julianday()` for arithmetic.
- Money: full units, floating point (`DOUBLE`). Fine for analysis, not for accounting.
- Writes are upserts on the table key; reruns never duplicate rows.
- Columns a job doesn't supply are left untouched on update (enrichment survives a ticker refresh).

## Not captured yet

- Prices, true market cap, volume (M3). Public float is only a proxy.
- Filing text, exhibits, Form 4 and 13D/G contents.
- Filings older than a company's ~1,000 most recent.
- Short interest, news, press releases (M4).
- Facts and filings for companies outside the watchlist (float covers everyone).

## Example queries

```sql
-- Annual revenue history
SELECT period_end, value FROM facts
WHERE cik = (SELECT cik FROM tickers WHERE ticker = 'PLUG')
  AND concept LIKE 'Revenue%' AND form LIKE '10-K%'
  AND julianday(period_end) - julianday(period_start) BETWEEN 350 AND 380
ORDER BY period_end DESC, filed_date DESC;

-- Insider activity (Form 4) in the last 90 days
SELECT t.ticker, count(*) AS form4s
FROM filings f JOIN tickers t USING (cik)
WHERE f.form = '4' AND f.filed_date >= date('now', '-90 day')
GROUP BY 1 ORDER BY 2 DESC;

-- Exchange mix of the universe
SELECT coalesce(exchange, 'unknown') AS exchange, count(*) FROM tickers GROUP BY 1 ORDER BY 2 DESC;
```
