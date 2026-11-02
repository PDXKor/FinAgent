-- One primary ticker per company (share classes collapse to the alphabetically first).
DROP VIEW IF EXISTS v_recent_filings;
CREATE VIEW v_recent_filings AS
SELECT f.filed_date, t.ticker, c.name, f.form, f.report_date, f.url
FROM filings f
JOIN companies c USING (cik)
LEFT JOIN (SELECT cik, min(ticker) AS ticker FROM tickers GROUP BY cik) t USING (cik)
WHERE f.filed_date >= date('now', '-30 day')
ORDER BY f.filed_date DESC, t.ticker;

-- Headline facts tagged with a metric name. Base for the financials views.
-- Flow (income) metrics cover a period; the rest are point-in-time.
DROP VIEW IF EXISTS v_fact_metrics;
CREATE VIEW v_fact_metrics AS
SELECT * FROM (
  SELECT cik, period_start, period_end, value, fy, fp, form, accession_no, filed_date,
    CASE concept
      WHEN 'Revenues' THEN 'revenue'
      WHEN 'RevenueFromContractWithCustomerExcludingAssessedTax' THEN 'revenue'
      WHEN 'RevenueFromContractWithCustomerIncludingAssessedTax' THEN 'revenue'
      WHEN 'NetIncomeLoss' THEN 'net_income'
      WHEN 'OperatingIncomeLoss' THEN 'operating_income'
      WHEN 'Assets' THEN 'assets'
      WHEN 'Liabilities' THEN 'liabilities'
      WHEN 'StockholdersEquity' THEN 'equity'
      WHEN 'CashAndCashEquivalentsAtCarryingValue' THEN 'cash'
      WHEN 'EntityCommonStockSharesOutstanding' THEN 'shares_outstanding'
    END AS metric,
    concept IN ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomerIncludingAssessedTax',
                'NetIncomeLoss', 'OperatingIncomeLoss') AS is_flow,
    julianday(period_end) - julianday(period_start) BETWEEN 350 AND 380 AS is_full_year
  FROM facts
) WHERE metric IS NOT NULL;

-- Latest value per company per metric, pivoted wide.
-- Balance-sheet items: latest period of any filing.
-- Income items: latest full-year (350-380 day) period from a 10-K, so quarters and YTD never mix in.
DROP VIEW IF EXISTS v_latest_financials;
CREATE VIEW v_latest_financials AS
WITH usable AS (
  SELECT * FROM v_fact_metrics
  WHERE NOT is_flow OR (form LIKE '10-K%' AND is_full_year)
),
ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY cik, metric ORDER BY period_end DESC, filed_date DESC) AS rn
  FROM usable
),
latest AS (SELECT * FROM ranked WHERE rn = 1)
SELECT
  c.cik,
  t.ticker,
  c.name,
  max(value) FILTER (WHERE metric = 'revenue') AS revenue,
  max(value) FILTER (WHERE metric = 'net_income') AS net_income,
  max(value) FILTER (WHERE metric = 'operating_income') AS operating_income,
  max(value) FILTER (WHERE metric = 'assets') AS assets,
  max(value) FILTER (WHERE metric = 'liabilities') AS liabilities,
  max(value) FILTER (WHERE metric = 'equity') AS equity,
  max(value) FILTER (WHERE metric = 'cash') AS cash,
  max(value) FILTER (WHERE metric = 'shares_outstanding') AS shares_outstanding,
  max(period_end) FILTER (WHERE metric = 'assets') AS balance_sheet_date,
  max(period_end) FILTER (WHERE metric IN ('revenue', 'net_income', 'operating_income'))
    AS annual_period_end
FROM latest l
JOIN companies c USING (cik)
LEFT JOIN (SELECT cik, min(ticker) AS ticker FROM tickers GROUP BY cik) t USING (cik)
GROUP BY c.cik, t.ticker, c.name;

-- One row per company per fiscal year, from 10-Ks. A fiscal year is any period end with a
-- full-year income value. Values: latest filing wins, so restatements replace originals.
-- Shares outstanding: cover page of the year's original 10-K.
DROP VIEW IF EXISTS v_annual_financials;
CREATE VIEW v_annual_financials AS
WITH annual AS (
  SELECT * FROM v_fact_metrics
  WHERE form LIKE '10-K%' AND (is_flow AND is_full_year OR NOT is_flow)
),
latest AS (
  SELECT cik, metric, period_end, value FROM (
    SELECT *, row_number() OVER (
      PARTITION BY cik, metric, period_end ORDER BY filed_date DESC) AS rn
    FROM annual WHERE metric <> 'shares_outstanding'
  ) WHERE rn = 1
),
original AS (
  SELECT cik, period_end, fy, form, filed_date, accession_no FROM (
    SELECT *, row_number() OVER (PARTITION BY cik, period_end ORDER BY filed_date) AS rn
    FROM annual WHERE is_flow
  ) WHERE rn = 1
),
cover AS (
  SELECT accession_no, period_end, value AS shares FROM annual
  WHERE metric = 'shares_outstanding'
),
shares AS (
  SELECT accession_no, shares FROM (
    SELECT *, row_number() OVER (PARTITION BY accession_no ORDER BY period_end DESC) AS rn
    FROM cover
  ) WHERE rn = 1
)
SELECT
  o.cik,
  o.fy AS fiscal_year,
  o.period_end,
  max(l.value) FILTER (WHERE l.metric = 'revenue') AS revenue,
  max(l.value) FILTER (WHERE l.metric = 'net_income') AS net_income,
  max(l.value) FILTER (WHERE l.metric = 'operating_income') AS operating_income,
  max(l.value) FILTER (WHERE l.metric = 'assets') AS assets,
  max(l.value) FILTER (WHERE l.metric = 'liabilities') AS liabilities,
  max(l.value) FILTER (WHERE l.metric = 'equity') AS equity,
  max(l.value) FILTER (WHERE l.metric = 'cash') AS cash,
  s.shares AS shares_outstanding,
  o.form,
  o.filed_date,
  o.accession_no
FROM original o
JOIN latest l USING (cik, period_end)
LEFT JOIN shares s USING (accession_no)
GROUP BY o.cik, o.period_end;

-- Latest public float per company, at or below $2B (the small-cap ceiling). Zero floats
-- (no public market) are excluded. Float excludes insider/affiliate holdings and can be up to
-- a year old, so this understates market cap: treat as a first-pass shortlist.
DROP VIEW IF EXISTS v_small_cap_candidates;
CREATE VIEW v_small_cap_candidates AS
WITH latest AS (
  SELECT cik, public_float, float_date, location FROM (
    SELECT cik, value AS public_float, period_end AS float_date, location,
      row_number() OVER (PARTITION BY cik ORDER BY period_end DESC) AS rn
    FROM public_float
  ) WHERE rn = 1
),
primary_ticker AS (
  SELECT cik, ticker, exchange FROM (
    SELECT cik, ticker, exchange,
      row_number() OVER (PARTITION BY cik ORDER BY ticker) AS rn
    FROM tickers
  ) WHERE rn = 1
)
SELECT p.ticker, c.name, p.exchange, l.public_float, l.float_date, c.sic_desc, l.location, c.cik
FROM latest l
JOIN companies c USING (cik)
JOIN primary_ticker p USING (cik)
WHERE l.public_float > 0 AND l.public_float <= 2000000000
ORDER BY l.public_float DESC;
