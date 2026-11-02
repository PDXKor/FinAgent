-- Reference
CREATE TABLE IF NOT EXISTS companies (
  cik             VARCHAR PRIMARY KEY,   -- zero-padded 10 digits
  name            VARCHAR,
  sic             VARCHAR,
  sic_desc        VARCHAR,
  state_inc       VARCHAR,
  fiscal_year_end VARCHAR,
  updated_at      TIMESTAMP
);

-- One company can list several tickers (share classes).
CREATE TABLE IF NOT EXISTS tickers (
  ticker     VARCHAR PRIMARY KEY,
  cik        VARCHAR,
  exchange   VARCHAR,
  updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS filings (
  accession_no VARCHAR PRIMARY KEY,
  cik          VARCHAR,
  form         VARCHAR,
  filed_date   DATE,
  report_date  DATE,
  primary_doc  VARCHAR,
  url          VARCHAR,
  ingested_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facts (
  cik          VARCHAR,
  taxonomy     VARCHAR,   -- us-gaap, dei
  concept      VARCHAR,
  unit         VARCHAR,   -- USD, shares
  period_start DATE,     -- = period_end for point-in-time values (e.g. Assets)
  period_end   DATE,
  value        DOUBLE,
  fy           INTEGER,
  fp           VARCHAR,   -- FY, Q1..Q4
  form         VARCHAR,
  accession_no VARCHAR,
  filed_date   DATE,
  PRIMARY KEY (cik, taxonomy, concept, unit, period_start, period_end, accession_no)
);

-- Aggregate market value of shares held by non-affiliates, as of each company's fiscal Q2 end.
-- Source: SEC XBRL frames (dei:EntityPublicFloat). A market-cap proxy until prices land.
CREATE TABLE IF NOT EXISTS public_float (
  cik          VARCHAR,
  period_end   DATE,
  value        DOUBLE,    -- USD
  accession_no VARCHAR,   -- filing that reported it (latest if amended)
  location     VARCHAR,   -- SEC business location code, e.g. US-NY, CA-ON
  PRIMARY KEY (cik, period_end)
);

-- Ops
CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id       VARCHAR PRIMARY KEY,
  job          VARCHAR,
  started_at   TIMESTAMP,
  finished_at  TIMESTAMP,
  status       VARCHAR,   -- running | ok | partial | failed
  requests     INTEGER,
  rows_written INTEGER,
  errors       INTEGER,
  error_sample VARCHAR
);

CREATE TABLE IF NOT EXISTS source_state (
  job             VARCHAR,
  key             VARCHAR,   -- e.g. CIK
  last_fetched_at TIMESTAMP,
  last_status     INTEGER,
  raw_path        VARCHAR,
  PRIMARY KEY (job, key)
);

-- Agents
-- One row per agent workflow run. JSON columns hold text written by the agents repo.
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id            VARCHAR PRIMARY KEY,
  workflow          VARCHAR,
  status            VARCHAR,   -- running | ok | failed | timeout
  inputs            VARCHAR,   -- JSON
  output            VARCHAR,   -- JSON
  error             VARCHAR,
  bindings          VARCHAR,   -- JSON: node -> {model, effort, prompt, tools}
  started_at        TIMESTAMP,
  finished_at       TIMESTAMP,
  input_tokens      INTEGER,
  output_tokens     INTEGER,
  cache_read_tokens INTEGER
);
