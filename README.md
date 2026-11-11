# Crypto Market Insights

Crypto Market Insights is a local-first research and decision-support application for crypto markets. It combines market data, deterministic technical analysis, relevant news and source-grounded AI explanations to publish a transparent daily **Coin of the Day** brief—or explicitly recommend **No Trade** when quality or risk criteria are not met.

> **Research software only.** The MVP is read-only, does not execute trades, does not manage wallets or custody assets, and does not provide personalized financial, tax or legal advice. Trade levels and risk examples are hypothetical.

## What it does

- Tracks a configurable universe of ten liquid, non-stablecoin crypto assets.
- Uses a versioned, explainable ranking model based on trend, momentum, relative strength, volume, setup quality, liquidity and news/event context.
- Computes technical indicators and conditional trade levels from one explicitly selected venue.
- Connects market moves to timestamped, deduplicated news and fundamental events.
- Produces week, month and year bull/base/bear scenarios with assumptions, invalidation conditions and uncertainty.
- Preserves immutable daily recommendations for chronological, cost-aware historical evaluation.
- Displays source provenance, data freshness, model/strategy versions and provider failures.

## MVP scope

### Included

- Market-cap metadata and asset eligibility
- Venue-specific OHLCV candles and market snapshots
- Deterministic indicators: EMA, RSI, MACD, ATR, VWAP where supported, relative volume, volatility and support/resistance features
- Candidate ranking, risk gates and `NO_TRADE`
- Conditional entry zones, invalidation/stop levels, targets, risk/reward assumptions and expiry
- RSS ingestion with an optional news API adapter
- News normalization, deduplication, classification and source-grounded summaries
- A separate frontend consumes the backend API for overview, charts, news, outlooks and historical performance
- PostgreSQL persistence, scheduled jobs and Docker Compose deployment
- Local LLM support through Ollama

### Explicitly not included

Live trading, exchange trading credentials, order submission, wallet transfers, automated order sizing, guaranteed predictions, high-frequency trading and personalized investment advice.

## Architecture

This repository contains the Python-centric backend. The dashboard is intentionally maintained
in a separate frontend repository and consumes the versioned API:

| Layer | Technology |
|---|---|
| API and jobs | Python, FastAPI, APScheduler |
| Analytics | pandas, NumPy and tested deterministic indicator functions |
| Database | PostgreSQL; TimescaleDB only if later justified |
| Market data | Aggregator metadata plus one selected exchange venue for candles |
| News | Curated RSS feeds plus an optional CryptoPanic adapter |
| Local AI | Ollama behind a provider abstraction |
| Packaging | Docker Compose |
| Testing | Pytest, Vitest/Jest and Playwright |

```mermaid
flowchart LR
  Sources[Market data, venue candles, RSS/API news] --> Ingestion[Ingestion adapters]
  Ingestion --> Database[(PostgreSQL)]
  Database --> Analytics[Features, indicators, ranking and risk gates]
  Analytics --> Context[Evidence context]
  Database --> Context
  Context --> LLM[Local LLM explanation]
  Analytics --> Brief[Daily brief and scenarios]
  LLM --> Brief
  Brief --> Database
  Database --> API[FastAPI]
  API --> Dashboard[Separate frontend repository]
  Database --> Evaluation[Walk-forward evaluation]
```

Core design decisions:

1. Deterministic calculations produce indicators, scores, levels and evaluation metrics before AI is used.
2. Aggregator metadata is kept separate from venue candles; prices are never silently blended across venues.
3. AI receives structured features and retrieved evidence, cannot perform authoritative arithmetic, and must produce schema-validated, source-linked output.
4. Ingestion is idempotent and all relevant timestamps, source references and versions are retained.
5. The system favors abstention over a forced recommendation.

## Local development

### Prerequisites

- Windows development machine with approximately 16 GB RAM
- Docker Desktop with Compose
- Python and Node.js toolchains
- Ollama installed natively for local inference

The repository is a monorepo in the architecture and implementation bootstrap phase. The Python
API foundation is available under `apps/api`, and the Next.js dashboard shell is available under
`apps/web`.
See [Contributing](CONTRIBUTING.md) for setup and validation commands.

The intended local services are:

| Service | Port |
|---|---:|
| FastAPI | `8000` |
| PostgreSQL | `5432` |
| Ollama | `11434` |

Bind services to localhost for personal use. Never expose PostgreSQL or Ollama publicly.

### Start the local stack

From the repository root, copy the example configuration and start PostgreSQL, the API, and the
dashboard:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Change `POSTGRES_PASSWORD` in `.env` before relying on the local setup. The sample value is only
a placeholder. Compose requires the database name, user, and password from this file. Service
ports are bound to localhost: the dashboard is at `http://localhost:3000`, the API health endpoint
is at `http://localhost:8000/health`, and PostgreSQL is at `localhost:5432` (or `POSTGRES_PORT`).
Compose waits for PostgreSQL and the API health checks before starting dependent services.

Useful lifecycle commands (from the repository root):

```powershell
docker compose ps
docker compose logs -f
docker compose down
```

`docker compose down` stops and removes the containers but preserves the PostgreSQL data volume.
To reset the local database and permanently delete its stored data:

```powershell
docker compose down -v
```

### Configuration

Copy `.env.example` to `.env` to configure the local stack. The configuration includes:

```env
APP_ENV=development
APP_TIMEZONE=America/Toronto
POSTGRES_DB=crypto_insights
POSTGRES_USER=crypto_insights
POSTGRES_PASSWORD=change-this-local-password
POSTGRES_PORT=5432
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/crypto_insights
MARKET_METADATA_PROVIDER=coingecko
MARKET_DATA_VENUE=kraken
DEFAULT_QUOTE_CURRENCY=USD
COINGECKO_API_KEY=
CRYPTOPANIC_API_KEY=
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=your-verified-local-model-tag
DAILY_ANALYSIS_TIME=08:00
UNIVERSE_SIZE=10
```

Do not commit secrets. Verify provider availability, regional access, licensing, quotas and attribution requirements before relying on any provider or publishing data.

The initial metadata adapter uses CoinGecko's `/coins/markets` endpoint, which returns assets
ordered by market capitalization. Set `COINGECKO_API_KEY` in `.env` for a Demo API key; it is sent
in the request header and is not included in logs. The adapter retries rate-limited and transient
server/network failures a bounded number of times, then logs and raises a provider error with the
provider, status, attempt count, and failure time. Successful records preserve CoinGecko's
`last_updated` timestamp separately from the local retrieval time.

CoinGecko's public API rate limits, endpoint availability, plan entitlements, and data-use terms
can change. Check the [API documentation](https://docs.coingecko.com/reference/coins-markets),
[current pricing](https://www.coingecko.com/en/api/pricing), and
[data-use and attribution guidance](https://support.coingecko.com/articles/4315804955-can-i-use-coingecko-data-and-screenshots-for-my-website-book-etc)
before deployment. When publishing CoinGecko data, name CoinGecko as the data source and follow
its branding guidance and any applicable plan terms. API key availability does not grant additional
data-use rights.

### Venue OHLCV and ticker data

The initial venue adapter uses Kraken's public spot `AssetPairs`, `OHLC`, and `Ticker` endpoints.
Configure `MARKET_DATA_VENUE=kraken` and `DEFAULT_QUOTE_CURRENCY` in `.env`; no exchange
credentials are used. The adapter resolves the requested base/quote symbols against Kraken's
current pair list and fails on unavailable, inactive, or ambiguous mappings rather than guessing.
Supported intervals are `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, and `15d`.

OHLC prices and volumes remain `Decimal` values, candle timestamps are UTC, and each record carries
the venue and resolved pair. The candle's `close_time` is the exclusive end of its interval;
Kraken always includes its current uncommitted candle, which is marked `is_complete=false`.
Kraken limits OHLC history to its most recent 720 entries. Ticker snapshots and candles both come
from Kraken; CoinGecko metadata is kept in a separate contract and is never substituted for
venue prices. Kraken's ticker response does not provide a last-trade timestamp, so the snapshot's
source timestamp is the local UTC retrieval time.

See the [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data),
[AssetPairs](https://docs.kraken.com/api-reference/market-data/get-tradable-asset-pairs), and
[Ticker](https://docs.kraken.com/api-reference/market-data/get-ticker-information) API references.
Confirm product availability, pair support, and current terms for the intended region before use.

### Candle ingestion and data health

The API migrates its PostgreSQL candle-ingestion tables on container startup. Request candles for
one pair and interval through the selected venue with:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/candles/ingest `
  -ContentType "application/json" `
  -Body '{"base_symbol":"BTC","quote_symbol":"USD","interval":"1h"}'
```

Ingestion validates candle identity, OHLCV invariants, duplicate keys, gaps, stale completed
candles, and configurable-by-code price outlier thresholds before persistence. Exact duplicate
rows in a response are collapsed with a warning; conflicting duplicates and invalid/stale batches
are rejected with diagnostics. Persistence uses the unique `(venue, venue_pair, interval,
open_time)` key with PostgreSQL `ON CONFLICT DO UPDATE`, so repeating ingestion updates existing
candles instead of creating duplicates. Run records and provider health retain failures and
timestamps for diagnosis.

Inspect provider status, latest completed candle freshness, and recent failed runs at
`http://localhost:8000/api/v1/data-health`. This endpoint reports database-backed ingestion
health; `/health` remains the API process liveness endpoint.

## Planned repository structure

```text
apps/api/                   # Python/FastAPI application
  src/                      # API package source
  tests/                    # API tests
  pyproject.toml            # API dependencies and tooling
apps/web/                   # Next.js frontend
  package.json              # Frontend dependencies and scripts
  app/                      # Dashboard routes and shared styles
  lib/                      # Typed API boundary and UI helpers
migrations/                 # Shared database migrations
infrastructure/
docs/
docker-compose.yml
.env.example
README.md
```

## Delivery roadmap

1. **Data validation:** confirm venue, quote currency, symbol mappings, candle quality, provider terms and coverage.
2. **Market foundation:** implement universe selection, adapters, candle storage, scheduling and health reporting.
3. **Deterministic engine:** add indicators, regime features, ranking, risk gates, levels and `No Trade`.
4. **News intelligence:** add RSS/API ingestion, deduplication, tagging and grounded summaries.
5. **API integration:** expose overview, charts, daily brief, trade setup, news and multi-horizon outlook data for the separate frontend.
6. **Evaluation:** freeze recommendations before outcomes, paper-track them and run walk-forward, out-of-sample comparisons against simple baselines.

## Reliability and evaluation principles

- Use UTC timestamps, point-in-time universe membership and immutable daily briefs.
- Avoid look-ahead bias, survivorship bias, leakage and tuning on the reported test period.
- Include fees, spread, slippage and delayed fills in evaluation.
- Show stale data and provider errors instead of silently serving old results.
- Treat news and article content as untrusted input.
- Return `INSUFFICIENT_EVIDENCE` for unsupported scenarios.
- Measure forward returns, drawdown, expectancy after costs, adverse/favourable excursion, coverage, abstention and scenario calibration.

## Documentation

- [Business requirements](docs/business/Crypto_Market_Insights_Business_Requirements.md)
- [Architecture and technical design](docs/architechture/Crypto_Market_Insights_Architecture_Design.md)

The detailed documents define functional requirements, data sources, API routes, data model, testing strategy, risks and open MVP decisions. Provider terms and limits must be rechecked before implementation or public release.
