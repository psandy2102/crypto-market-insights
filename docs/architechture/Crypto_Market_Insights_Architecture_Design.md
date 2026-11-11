# Crypto Market Insights — Architecture & Technical Design

**Version:** 1.0 | **Status:** Proposed MVP | **Architecture:** Local-first modular application

## 1. Architecture summary

Build a Python-centric analytics backend and React dashboard. Ingest market data and news, compute technical features deterministically, rank a ten-asset universe, use a local LLM to explain retrieved evidence, and publish a versioned daily research brief.

### Recommended stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | Next.js, React, TypeScript | Interactive dashboard |
| UI | Tailwind CSS, shadcn/ui | Consistent components |
| Charts | Lightweight Charts or Apache ECharts | Candles, volume, overlays |
| API | Python, FastAPI | One language for data and analytics |
| Analytics | pandas, NumPy, tested indicator functions | Reproducible calculations |
| Scheduling | APScheduler initially | Simple daily jobs |
| Database | PostgreSQL | Market/news/history storage |
| Time series | TimescaleDB later if justified | Avoid premature complexity |
| Cache/queue | None initially; Redis/Celery later | Single-user MVP does not need distributed jobs |
| Local AI | Ollama behind provider interface | Local inference |
| News | RSS parser + optional CryptoPanic adapter | Low-cost ingestion |
| Packaging | Docker Compose | Repeatable local setup |
| Tests | Pytest, Vitest/Jest, Playwright | Unit/integration/e2e |

**Hardware baseline:** Windows, 16 GB RAM, no dedicated GPU. Run Ollama natively on Windows initially; use a small quantized model, short context and sequential inference. Avoid running this model workload and the CodeGuard AI stack simultaneously if memory is constrained.

## 2. High-level components

```mermaid
flowchart LR
  subgraph Sources
    CG[CoinGecko / CoinPaprika]
    EX[Exchange public market API]
    RSS[News RSS / API]
  end
  subgraph Ingestion
    SCH[Scheduler]
    MD[Market Data Adapters]
    NI[News Ingestion]
  end
  subgraph Core
    DB[(PostgreSQL)]
    FE[Feature and Indicator Engine]
    R[Ranking and Risk Gates]
    C[Evidence Context Builder]
    L[Local LLM Explanation]
    B[Daily Brief Builder]
    E[Backtest and Evaluation]
  end
  subgraph Product
    API[FastAPI]
    UI[Next.js Dashboard]
  end
  CG --> MD
  EX --> MD
  RSS --> NI
  SCH --> MD
  SCH --> NI
  MD --> DB
  NI --> DB
  DB --> FE --> R
  DB --> C
  R --> C --> L --> B
  R --> B
  B --> DB
  DB --> E
  DB --> API --> UI
```

## 3. Key architecture decisions

### ADR-001 — Python-first backend
Use Python for API, ingestion, analytics and orchestration. This is a data/quant-heavy product; TypeScript remains the frontend language.

### ADR-002 — Separate aggregator metadata from venue candles
Use CoinGecko or CoinPaprika for asset discovery/market-cap metadata. Use one explicitly selected venue for candles that determine trade levels. Never silently blend exchange candles.

### ADR-003 — Deterministic calculations before AI
Indicators, scores, levels, risk/reward and backtests are computed by tested code. The LLM explains structured features and retrieved news; it must not invent prices or perform authoritative arithmetic.

### ADR-004 — Local LLM behind an abstraction
Start with Ollama and a small model verified at setup time. Persist model identity/digest, prompt version and generation parameters. Hosted model support, if ever enabled, must be explicit.

### ADR-005 — No execution in MVP
No exchange trading credentials, order placement or wallet functionality. Future execution requires a separate security, regulatory and operational design.

### ADR-006 — PostgreSQL first
Use PostgreSQL with indexed candle tables. Add TimescaleDB only if query/retention needs justify it. No vector database is required for a small news corpus; start with metadata filtering and PostgreSQL full-text search.

### ADR-007 — Scheduler before distributed queue
Use APScheduler with idempotent jobs. Add Redis/Celery only when concurrent jobs, durable distributed retries or multiple workers are genuinely needed.

## 4. Data source strategy

Provider access, free-tier limits, geographic availability and licensing can change. Recheck before implementation and before public/commercial release.

### Asset metadata
- **CoinGecko API:** market-cap ranking and asset metadata via `/coins/markets`. Rate limits, endpoint access, freshness and usage terms depend on the current API plan and may change. Review the [API documentation](https://docs.coingecko.com/reference/coins-markets), [pricing](https://www.coingecko.com/en/api/pricing) and [data-use/attribution guidance](https://support.coingecko.com/articles/4315804955-can-i-use-coingecko-data-and-screenshots-for-my-website-book-etc) before deployment or publication.
- **CoinPaprika:** tickers, coins, exchanges and OHLCV. Current free plan is personal-use only, with 20,000 calls/month per IP and limited historical OHLCV. Do not assume personal-use terms allow public/commercial use. [Pricing](https://coinpaprika.com/api/pricing/) · [Developer docs](https://coinpaprika.com/developers)

### Venue candles
- Use an exchange public market-data API for OHLCV, ticker and optionally order-book snapshots.
- Candidate adapters include Kraken public market data and Binance market-data-only endpoints, subject to regional availability, pair coverage and current terms.
- Binance documents unauthenticated public endpoints including klines and ticker endpoints: [Market Data Only](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md).
- Historical public Binance candles are also documented in [Binance Public Data](https://github.com/binance/binance-public-data).
- Do not assume an exchange is available to a Canadian user merely because its API is public. Validate the actual service and product availability.

### News
- Start with curated RSS feeds from reputable crypto, financial and regulator sources.
- Optional CryptoPanic adapter; authentication is required. Confirm current plan, quotas and usage rights before depending on it: [API reference](https://cryptopanic.com/developers/api/).
- Store article metadata and only permitted excerpts; link to publishers rather than republishing full copyrighted articles.
- Use source allowlists and reliability metadata. Social virality is not proof of factual credibility.

## 5. Ingestion pipelines

### Market data
1. Scheduler refreshes universe and market data.
2. Universe service obtains eligible assets and metadata.
3. Exclude stablecoins, wrapped/bridged duplicates, leveraged tokens, insufficient history/liquidity and unsupported venue pairs.
4. Map canonical asset IDs to venue symbols.
5. Fetch candles for required intervals (e.g. 5m/15m/1h/4h/1d) and ticker/volume.
6. Normalize UTC timestamps and decimal values.
7. Validate OHLC invariants, gaps, duplicates, staleness and outliers.
8. Upsert idempotently and record provider health.

### News
1. Poll configured RSS/API sources conservatively.
2. Normalize title, publisher, URL, language and publication/retrieval timestamps.
3. Canonicalize URLs and deduplicate by URL/title similarity.
4. Tag assets/entities and event topics.
5. Persist metadata, permitted excerpt and provenance.
6. Retrieve relevant stories for the daily analysis window.
7. Use LLM only for source-grounded classification/summaries.
8. Show original source link and publication time.

## 6. Universe selection

Use a versioned process, not a hard-coded top-ten list:
- Rank eligible assets by market capitalization among supported venue pairs.
- Require minimum rolling quote volume and minimum price history.
- Exclude stablecoins, wrapped/bridged duplicates, leveraged tokens, synthetic assets and duplicate economic exposures.
- Exclude stale data and uncertain symbol mappings.
- Consider concentration limits across similar sectors.
- Persist the candidate universe and selected ten with effective timestamps.

Refresh membership daily or weekly, not on every intraday run.

## 7. Quantitative engine

### Initial features
EMA 20/50/200; RSI 14; MACD (12,26,9); ATR 14; relative volume; VWAP when reliable intraday volume exists; returns/relative strength vs BTC and universe; realized volatility; swing highs/lows; pivot zones; spread/liquidity proxy where available.

Every feature function needs unit tests against known candle fixtures. Define candle close-time semantics; do not use unfinished candles unless labelled.

### Candidate score (initial hypothesis)

```text
score =
  0.25 * trend_alignment +
  0.20 * momentum_relative_strength +
  0.15 * volume_confirmation +
  0.20 * setup_quality +
  0.10 * liquidity_quality +
  0.10 * news_context
```

Each component is normalized to 0–100. Keep raw values, explanations and strategy version. Tune only on training/validation data and evaluate on an untouched chronological test period.

### Risk gates
Reject a candidate when required candles are stale/missing, pair mapping is uncertain, liquidity/spread fails limits, volatility makes stop distance unreasonable, reward/risk is poor after costs, severe event risk is unresolved, timeframes materially conflict or invalidation cannot be defined. The selector may return `NO_TRADE`.

## 8. Trade-level calculation

Return structured data rather than free-form prose. Example schema (zero values are placeholders, not real levels):

```json
{
  "asset": "BTC",
  "venue": "configured-venue",
  "market_pair": "BTC/USD",
  "as_of": "2026-11-02T20:00:00Z",
  "bias": "neutral",
  "entry_zone": {"low": 0, "high": 0, "conditions": []},
  "stop_invalidation": {"price": 0, "reason": ""},
  "targets": [{"price": 0, "reason": ""}],
  "risk_reward_estimate": 0,
  "assumptions": {"fees_bps": 0, "slippage_bps": 0},
  "expires_at": "2026-11-03T00:00:00Z"
}
```

Level inputs: swing support/resistance, ATR, pivots, VWAP, volume zones and multi-timeframe structure. Entry requires a trigger (reclaim/retest or breakout confirmation). A stop is not a guaranteed fill price. Include costs and expiry. Recompute after material movement, level break or important news. Suppress plans when data or liquidity is inadequate.

## 9. News intelligence

Pipeline: `Feed -> Normalize -> Deduplicate -> Entity Tag -> Topic Classify -> Relevance Rank -> Evidence Pack -> LLM Summary`

Topics: regulation/enforcement, ETF/institutional flows, protocol upgrades/governance, hacks/exploits/outages, token unlocks/issuance/burns, listings/delistings, macro, adoption/partnerships and litigation.

Relevance uses asset match, source credibility, recency, novelty, event severity, impact horizon and confirmation status. Sentiment alone is never a trade signal; severe negative events can trigger a risk gate.

### LLM grounding contract
Provide article title, publisher, URL, timestamps, permitted excerpt, deterministic features and strict task/schema. Require summary, factual claims linked to article IDs, possible relevance, impact horizon, sentiment, uncertainty, contradictory evidence and unknowns. Reject invented URLs, unsourced numbers or unsupported claims. Treat article content as untrusted data and guard against prompt injection.

## 10. Multi-horizon outlook

| Horizon | Main evidence | Output |
|---|---|---|
| 1 week | Trend, momentum, volatility, liquidity, near-term events | Bull/base/bear ranges and triggers |
| 1 month | Regime, trend persistence, catalysts, supply events | Scenario ranges, assumptions, invalidation |
| 1 year | Adoption, fundamentals, token supply, sector and macro risk | Broad strategic scenarios with wide uncertainty |

Do not ask the LLM for one future price. Where feasible, use historical return distributions, volatility models or quantile regression. Evaluate interval coverage and calibration. Include BTC/broad-market baselines. State that crypto can suffer severe or near-total losses. Return `INSUFFICIENT_EVIDENCE` when data is inadequate.

## 11. Backtesting and evaluation

This is core product functionality:
- Persist point-in-time data and daily recommendation before outcome is known.
- Use only candles/news available before the decision timestamp.
- Store point-in-time universe membership to reduce survivorship bias.
- Split training/validation/test chronologically; use walk-forward tests.
- Include fees, spread, slippage and delayed fills.
- Compare with BTC buy-and-hold, equal-weight watchlist and simple trend baselines.
- Track No Trade frequency and coverage.

Metrics: forward return at 1d/1w/1m/1y, max adverse/favourable excursion, win rate, average win/loss, expectancy after costs, drawdown, volatility, risk/reward realization, abstention rate and scenario calibration. Never tune and report on the same period.

## 12. Data model

| Table | Purpose |
|---|---|
| `assets` | Canonical asset metadata |
| `asset_universe_snapshots` | Point-in-time top-ten membership |
| `venues` | Venue metadata |
| `market_pairs` | Venue symbol/base/quote mapping |
| `candles` | OHLCV by venue, pair, interval and open time |
| `market_snapshots` | Price, market cap, volume, spread and provenance |
| `news_sources` | Feed/API and reliability metadata |
| `news_articles` | Normalized article metadata/permitted excerpt |
| `article_asset_links` | Asset relevance |
| `feature_snapshots` | Indicator values by asset/timeframe |
| `candidate_rankings` | Component scores and rank |
| `daily_briefs` | Coin of the Day or No Trade |
| `trade_setups` | Entry, stop, targets, expiry and assumptions |
| `scenario_forecasts` | Bull/base/bear by horizon |
| `analysis_runs` | Status, timestamps and diagnostics |
| `strategy_versions` | Scoring/level configuration |
| `model_versions` | Model/prompt configuration |
| `evaluation_results` | Forward outcomes and calibration |

Use UTC timestamps and decimal/numeric types for prices. Unique candle key: `(venue_id, market_pair_id, interval, open_time)`. Store source and retrieval times separately. Preserve immutable input references and model/strategy versions. Append new briefs; do not overwrite old calls.

## 13. API routes

```text
GET  /api/v1/health
GET  /api/v1/universe
GET  /api/v1/market/overview
GET  /api/v1/assets/{asset_id}
GET  /api/v1/assets/{asset_id}/candles
GET  /api/v1/assets/{asset_id}/indicators
GET  /api/v1/assets/{asset_id}/news
GET  /api/v1/rankings/latest
GET  /api/v1/briefs/latest
GET  /api/v1/briefs/{date}
GET  /api/v1/setups/latest
GET  /api/v1/outlooks/{asset_id}
GET  /api/v1/performance/summary
GET  /api/v1/data-health
POST /api/v1/admin/refresh
```

Protect admin routes if bound beyond localhost. No order endpoint is included.

## 14. Repository structure

```text
crypto-market-insights/
├── apps/web/                     # Next.js dashboard
├── services/api/                 # FastAPI application
├── src/
│   ├── ingestion/{market_data,news}/
│   ├── providers/{market_data,exchanges,news,llm}/
│   ├── domain/{universe,indicators,ranking,levels,scenarios,evaluation}/
│   ├── intelligence/{context_builder,news_analysis,brief_generator}/
│   ├── jobs/
│   ├── repositories/
│   └── schemas/
├── migrations/
├── tests/{unit,integration,backtesting,e2e}/
├── infrastructure/{docker,monitoring}/
├── docs/{business,architecture,decisions,data-sources,operations}/
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── README.md
└── CONTRIBUTING.md
```

## 15. Local deployment and configuration

Services: Next.js `3000`, FastAPI `8000`, PostgreSQL `5432`, optional Redis, and Ollama `11434` (native Windows service initially). Bind ports to localhost for personal use. Never expose PostgreSQL/Ollama publicly.

Example `.env.example`:

```env
APP_ENV=development
APP_TIMEZONE=America/Toronto
DATABASE_URL=postgresql+psycopg://app:change-me@postgres:5432/crypto_insights
MARKET_METADATA_PROVIDER=coingecko
MARKET_DATA_VENUE=kraken
DEFAULT_QUOTE_CURRENCY=USD
COINGECKO_API_KEY=
CRYPTOPANIC_API_KEY=
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=your-verified-local-model-tag
DAILY_ANALYSIS_TIME=08:00
UNIVERSE_SIZE=10
```

Template only; never commit real keys. Validate venue/pair availability for the user's region. Use timeouts, bounded retries, provider rate limits, URL validation and article-fetch size limits. No trading keys in MVP.

## 16. Security and reliability

- Treat feeds/articles as untrusted input; delimit them as data in prompts.
- LLM cannot access shell, filesystem, browser or exchange credentials.
- Validate model output with Pydantic schemas.
- Do not permit arbitrary model-generated URL/tool calls.
- Rate-limit providers and retry with exponential backoff.
- Make ingestion idempotent; record failed runs.
- Show last-success timestamps and stale-data warnings.
- Maintain source allowlists, URL validation and audit history for strategy changes.
- No private holdings or wallet data is needed in MVP.

## 17. Testing strategy

**Unit:** indicator fixtures, candle boundaries, score normalization, risk gates, No Trade, levels/expiry, deduplication and scenario validation.  
**Integration:** provider fixtures, DB upserts, scheduler idempotency/retries, LLM schema validation and hallucination rejection.  
**Backtesting:** chronological walk-forward, out-of-sample, cost sensitivity, survivorship and leakage checks.  
**E2E:** dashboard freshness, Coin of the Day/No Trade, chart values, source links and immutable historical briefs.

## 18. Initial GitHub issues

1. Initialize repository and engineering conventions.
2. Set up Python project, linting, formatting and type checking.
3. Create Next.js dashboard shell.
4. Add Docker Compose and PostgreSQL.
5. Design schema and migrations.
6. Implement market metadata adapter.
7. Implement venue OHLCV adapter.
8. Build candle normalization, validation and persistence.
9. Implement indicator library with fixtures.
10. Implement universe eligibility and ranking.
11. Add risk gates and No Trade.
12. Implement RSS ingestion and deduplication.
13. Add source-grounded LLM summaries.
14. Implement daily brief/trade setup schemas.
15. Build Coin of the Day dashboard and chart.
16. Add week/month/year scenario outlooks.
17. Persist snapshots and evaluation metrics.
18. Implement walk-forward backtesting and benchmark report.

## 19. Implementation sequence

**Milestone 1 — Prove data availability:** choose quote currency/venue; pull sample metadata and candles for ten assets; validate symbol mapping, gaps, freshness and terms.  
**Milestone 2 — Deterministic engine:** persist candles, calculate indicators, rank, risk-gate and generate No Trade/levels.  
**Milestone 3 — News:** RSS, deduplication, tagging and grounded summaries.  
**Milestone 4 — Dashboard:** overview, chart, plan, news and outlook.  
**Milestone 5 — Evaluation:** freeze daily calls, paper-track, backtest and calibrate.

## 20. Design risks

Top-ten-by-market-cap does not guarantee liquidity. Aggregator and venue prices can differ. Free API access does not imply commercial redistribution rights. News sentiment is noisy/manipulable. LLMs can sound confident while wrong. Backtests can be distorted by leakage, survivorship, overfitting or unrealistic fills. Stops do not guarantee execution prices. One-year crypto scenarios have very wide uncertainty. Review jurisdiction-specific requirements before distributing investment recommendations or adding execution.

## Appendix — Sources checked

- CoinGecko pricing: https://www.coingecko.com/en/api/pricing
- CoinGecko data-use guidance: https://support.coingecko.com/articles/4315804955-can-i-use-coingecko-data-and-screenshots-for-my-website-book-etc
- CoinPaprika pricing: https://coinpaprika.com/api/pricing/
- CoinPaprika docs: https://coinpaprika.com/developers
- Binance market-data-only API: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md
- Binance public historical data: https://github.com/binance/binance-public-data
- CryptoPanic API: https://cryptopanic.com/developers/api/

Recheck provider terms and limits before implementation or public release.
