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

### Configuration

Copy `.env.example` to `.env` when the application scaffolding is available. The planned configuration includes:

```env
APP_ENV=development
APP_TIMEZONE=America/Toronto
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
