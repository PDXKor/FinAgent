# Recon — Data Sources

Free sources for small-cap data. Limits change often; verify before building each adapter.

## Regulatory / Filings (primary, highest trust)

| Source | Data | Access | Limits / Notes |
|---|---|---|---|
| SEC EDGAR (`data.sec.gov`) | Filings index, XBRL financials (`companyfacts`, `frames`), Forms 3/4/5, 8-K, 10-K/Q, 13D/G | REST, no key | 10 req/s; `User-Agent` with email required |
| SEC EDGAR Full-Text Search (`efts.sec.gov`) | Keyword search across filings since 2001 | REST, no key | Unofficial JSON endpoint behind the search UI |
| SEC bulk data | `company_tickers.json`, Financial Statement Data Sets, nightly `submissions.zip` | File download | Best for building the universe |
| FINRA | Short interest (twice monthly), OTC/ATS volume | Query API / file download | Free tier needs account for some endpoints |
| Nasdaq Trader symbol directory | All listed US tickers, exchange, ETF flag | Plain-text files, no key | Daily refresh; universe seed |

## Market Data APIs (free tiers)

| Source | Data | Access | Limits / Notes |
|---|---|---|---|
| yfinance | Prices, fundamentals, holders, options | Python lib (scrapes Yahoo) | Unofficial; breaks and throttles without warning |
| Stooq | EOD prices (CSV) | HTTP, no key | No fundamentals; good fallback |
| Alpha Vantage | Prices, fundamentals, earnings, news sentiment | REST, free key | ~25 req/day |
| Financial Modeling Prep | Fundamentals, profiles, screener | REST, free key | ~250 req/day; some endpoints paid |
| Finnhub | Quotes, company news, insider trades, earnings calendar | REST, free key | ~60 req/min |
| Polygon.io (Massive) | EOD aggregates, ticker details, reference data | REST, free key | ~5 req/min; delayed data |
| Tiingo | EOD prices, news | REST, free key | Daily/hourly caps |
| Twelve Data | Prices, some fundamentals | REST, free key | ~800 req/day |
| Alpaca | Bars, quotes (IEX feed) | REST/WebSocket, free account | IEX-only on free tier |

## Sector-Specific (small-cap heavy)

| Source | Data | Use Case |
|---|---|---|
| ClinicalTrials.gov API | Trial status, phases, sponsors | Biotech catalysts |
| openFDA | Approvals, recalls, adverse events | Biotech / med device |
| USAspending.gov API | Federal contract awards | Gov contractors, defense |
| PatentsView (USPTO) | Patent grants by assignee | Tech / IP-driven names |
| FRED | Macro series | Context only |

## News / Sentiment

| Source | Data | Access | Notes |
|---|---|---|---|
| Press release wires (GlobeNewswire, PR Newswire, Business Wire, Accesswire) | Company announcements | RSS | Small caps announce here first |
| Google News RSS | Headlines by ticker/company | RSS, no key | Unofficial; deduplicate |
| GDELT | Global news events | REST, no key | Broad, noisy |
| Reddit API | r/pennystocks, r/smallstreetbets, r/stocks | OAuth, free tier | ~100 req/min; ToS limits commercial use |
| StockTwits | Ticker message stream | REST | Public access restricted; verify |

## Scrape Targets (no API)

Check each site's ToS and `robots.txt` before scraping.

| Site | Data | Risk |
|---|---|---|
| Finviz | Screener, short float, insider table, news | ToS prohibits scraping; Elite tier has export |
| OpenInsider | Insider buys/sells, cluster buys | Low; same data available from EDGAR Form 4 |
| Nasdaq.com (`api.nasdaq.com`) | Earnings calendar, institutional holdings | Unofficial JSON; needs browser headers |
| OTC Markets | OTC tier, disclosure status | API is paid; site scrape only |

## Recommended Starting Set
1. **SEC EDGAR** — universe, financials, insider activity. Free, authoritative, no key.
2. **Nasdaq Trader + SEC tickers** — build small-cap universe.
3. **yfinance + Stooq fallback** — prices and market cap.
4. **FINRA** — short interest.
5. **Press release RSS** — catalysts.

Add keyed APIs (Finnhub, FMP) only to fill gaps.
