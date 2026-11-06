# Crypto Market Insights — Business Requirements Document

**Version:** 1.0 | **Status:** Proposed MVP | **Repository:** `crypto-market-insights`

> Research and decision-support software only. The MVP does not execute trades and does not provide personalized financial advice.

## 1. Executive summary

Crypto Market Insights monitors a configurable universe of ten liquid crypto assets and produces a transparent **Coin of the Day** research brief. It combines market data, deterministic technical analysis, relevant news/fundamental events and AI-assisted explanation. The dashboard presents a conditional trade plan and bull/base/bear scenarios for the next week, month and year.

The product must also be willing to say **No Trade**. It must distinguish observed facts, calculated indicators, model interpretation and uncertain scenarios.

## 2. Vision and objectives

Build a local-first crypto research cockpit that:
- Tracks ten leading, liquid non-stablecoin assets.
- Ranks candidates using a versioned, explainable scoring model.
- Identifies one daily candidate only when minimum quality and risk criteria pass.
- Calculates venue-specific entry zones, targets and invalidation levels.
- Connects market moves to timestamped news and fundamental events.
- Produces week/month/year scenario analysis with explicit uncertainty.
- Preserves historical recommendations for honest evaluation.
- Uses free or low-cost sources during the prototype phase.

## 3. Users and problem

**Users:** individual crypto researchers, technical traders, fundamental/news-oriented researchers, and product evaluators.

**Problem:** information is fragmented across exchanges, charting tools, market-data APIs and news sites. Comparing assets, calculating levels, assessing news and forming multi-horizon views is manual and inconsistent. The platform should reduce this effort without replacing independent judgement.

## 4. Product principles

1. Evidence before narrative; compute indicators and scores in deterministic code.
2. No forced trade; No Trade is a valid daily outcome.
3. Every price level identifies venue, pair, quote currency and timestamp.
4. Show data freshness and source provenance.
5. Use scenario ranges, not falsely precise future prices.
6. Store inputs, strategy/model versions and outputs for reproducibility.
7. News-derived claims link to sources; AI must not invent facts.
8. MVP is read-only; no exchange credentials or order submission.
9. Historical evaluation must prevent look-ahead and survivorship bias.

## 5. Scope

### MVP
- Configure and display a ten-asset watchlist.
- Refresh market-cap, volume and asset metadata.
- Collect OHLCV from one selected venue per asset.
- Calculate indicators, trend/regime and relative-strength features.
- Rank candidates and return Coin of the Day or No Trade.
- Generate conditional entry zone, stop/invalidation, targets, risk/reward and expiry.
- Ingest RSS news and optionally one news API.
- Deduplicate, classify and summarize relevant stories.
- Generate week/month/year bull/base/bear scenarios.
- Dashboard with charts, news, analysis and history.
- Persist daily snapshots and evaluate historical calls.
- Local deployment with Docker Compose and a local-LLM adapter.

### Later releases
- Multi-exchange comparison; on-chain and derivatives data.
- Macro calendar and broader market risk indicators.
- Calibrated probabilistic models and regime detection.
- Alerts, paper-trading simulation and portfolio risk analytics.
- Optional cloud/multi-user deployment.
- Exchange execution only after separate security, regulatory and operational review.

### Explicit non-goals
No live trading, custody, wallet transfers, automated order sizing/submission, guaranteed predictions, high-frequency trading or personalized financial/tax/legal advice.

## 6. Functional requirements

### FR-01 — Asset universe
Maintain ten configurable assets. Rank eligible assets using market capitalization, quote volume, exchange availability, data quality and history. Exclude stablecoins, wrapped/bridged duplicates, leveraged tokens, illiquid assets and unreliable listings. Persist point-in-time universe membership.

### FR-02 — Market data
Fetch price, market cap, volume and asset metadata from an aggregator. Fetch candles from the selected venue. Normalize symbols, quote currencies and UTC timestamps. Detect missing candles, stale responses, duplicates and outliers. Store provider, venue, pair, source timestamp and retrieval timestamp.

### FR-03 — Candidate ranking
Use a versioned scoring model with trend, momentum, relative strength, volume, setup quality, liquidity and news/event risk. Display component scores. Apply hard risk gates. Do not force a selection if no asset passes.

### FR-04 — Daily trade plan
Display asset, venue, pair, as-of time, directional bias, conditional entry zone, invalidation/stop, target zones, estimated risk/reward after fee/slippage assumptions, setup expiry and recalculation triggers. Any risk-budget illustration is hypothetical; it does not submit orders.

### FR-05 — Technical analysis
Initial indicators: EMA 20/50/200, RSI 14, MACD, ATR 14, VWAP where supported by intraday volume, relative volume, rolling highs/lows, pivots and realized volatility. Use tested deterministic calculations, specify timeframe, and do not use unfinished candles unless clearly labelled.

### FR-06 — News/fundamentals
Ingest RSS/API articles; normalize title, publisher, URL, published/retrieved times and language. Deduplicate syndicated stories. Classify regulation, ETF/institutional flows, upgrades, exploits, token unlocks, listings/delistings, macro, litigation and governance. Show source links, relevance, direction, impact horizon and whether claims are confirmed, reported or interpreted.

### FR-07 — Daily viewpoint
Explain why the candidate ranks first, supporting and contradicting evidence, key risks and thesis invalidation. Combine deterministic features with retrieved news. Link news-derived claims. Label AI interpretation and store model/prompt versions.

### FR-08 — Multi-horizon outlook
For 1 week, 1 month and 1 year, provide bull/base/bear ranges, assumptions, drivers, invalidation and uncertainty. Short horizons emphasize trend/volatility/events; the one-year view emphasizes fundamentals, adoption, token supply, sector and macro risks. If evidence is insufficient, say so.

### FR-09 — Dashboard
Show ten-asset overview, market regime, data freshness, Coin of the Day/No Trade, score breakdown, interactive candlestick chart, indicators and levels, relevant news, daily thesis, trade plan, multi-horizon scenarios and past picks.

### FR-10 — Evaluation
Persist every ranking/brief before outcomes are known. Evaluate forward returns, hit rate, expectancy after costs, drawdown, volatility, maximum adverse/favourable excursion, calibration and coverage. Compare with simple baselines. Use chronological walk-forward and out-of-sample testing.

### FR-11 — Configuration
Configure assets, venue, quote currency, time zone, analysis schedule, thresholds, indicators and news sources. Store API keys outside source control. Show ingestion errors and run logs.

## 7. Dashboard information architecture

1. **Market Overview:** ten assets, movers, regime, data freshness.
2. **Coin of the Day:** candidate or No Trade, score and thesis.
3. **Trade Setup:** entry, stop/invalidation, targets, risk/reward, expiry.
4. **Chart:** candles, volume, overlays, support/resistance and levels.
5. **News & Events:** source, time, topic, asset relevance and impact.
6. **Outlook:** week/month/year bull/base/bear scenarios.
7. **Performance:** historical picks, outcomes and benchmark.
8. **Settings & Data Health:** universe, providers, venue and thresholds.

## 8. Initial ranking hypothesis

| Component | Weight | Inputs |
|---|---:|---|
| Trend alignment | 25% | EMA alignment, multi-timeframe structure |
| Momentum/relative strength | 20% | RSI regime, MACD, return vs BTC/universe |
| Volume confirmation | 15% | Relative volume and quote-volume trend |
| Setup quality | 20% | Level proximity, ATR stop distance, reward/risk |
| Liquidity quality | 10% | Quote volume, spread/depth proxy |
| News/event context | 10% | Source quality, novelty, relevance, event risk |

Weights are hypotheses, not proven alpha. Record component scores and strategy version. Tune only on training/validation periods and reserve an untouched out-of-sample period. Severe negative event risk can veto a candidate; positive sentiment cannot override a security/regulatory risk gate.

## 9. Trade-level methodology

- Calculate levels from the selected venue's candles and market data.
- Use swing structure, support/resistance, ATR, pivots, VWAP and volume zones.
- Entry must include a trigger, not simply “buy now”.
- Stop is thesis invalidation, not guaranteed maximum loss; slippage/gaps can worsen execution.
- Targets are conditional zones with rationale.
- Include fee/slippage assumptions and plan expiry.
- Recompute after material price movement, key-level break or important news.
- Suppress plans when data is stale, liquidity is poor or volatility is abnormal.

## 10. Non-functional requirements

| Area | Requirement |
|---|---|
| Reliability | Visible failures, safe retries, no silent stale dashboard |
| Performance | Daily ten-asset analysis completes within a few minutes on a typical dev PC |
| Data integrity | UTC, idempotent ingestion, unique candle keys and provenance |
| Security | No exchange trading keys in MVP; secrets outside Git |
| Privacy | Local-first; no external LLM by default |
| Explainability | Scores decomposed into measurable features and cited context |
| Reproducibility | Store input snapshots and strategy/model versions |
| Extensibility | Provider adapters for market data, news and LLM |
| Observability | Structured logs, run IDs, provider health and freshness |
| Cost | Free tiers/RSS and conservative polling for prototype |

## 11. Success metrics

- 100% of briefs show venue, source timestamps and data freshness.
- 100% of setups include invalidation and expiry.
- 100% of news-derived claims link to a source or are marked unverified.
- At least 95% of scheduled runs complete or report a visible failure.
- Zero live orders in MVP.
- Historical performance reported after estimated fees/slippage and against baselines.
- No predictive accuracy target until a meaningful out-of-sample sample exists.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Free API limits/changes | Cache, throttle, adapter abstraction, fallback |
| Exchange price differences | Explicit venue/pair; never silently mix candles |
| News misinformation/duplicates | Source allowlist, provenance, deduplication |
| LLM hallucinations | Retrieval grounding, schema validation, deterministic calculations |
| Backtest overfitting | Walk-forward, out-of-sample, costs and survivorship controls |
| Forecast overconfidence | Scenario ranges, calibration and insufficient-evidence state |
| Sudden events | Risk gate, freshness check, setup expiry and No Trade |
| Provider licensing | Review terms, attribution and commercial-use rights |
| Local resource limits | Scheduled batch jobs, small model, sequential inference |
| Regulatory exposure | Personal/read-only MVP; legal review before distributing signals or execution |

## 13. MVP acceptance criteria

- Ten assets can be configured and displayed.
- Market metadata and OHLCV persist with source/timestamps.
- Indicators match independently verified test fixtures.
- Ranking exposes component scores and risk-gate decisions.
- No Trade is supported.
- Trade plan includes venue, pair, timestamp, entry, invalidation, targets, assumptions and expiry.
- News shows publisher, URL, publication and retrieval times.
- LLM summaries are grounded in supplied articles and do not calculate indicators.
- Outlooks show bull/base/bear scenarios and uncertainty.
- Historical recommendations are immutable and evaluable without look-ahead bias.
- Dashboard exposes stale data and provider failures.
- No trading credentials or order endpoints exist.

## 14. Delivery phases

**Phase 0 — Data validation:** verify provider coverage, terms, quote currency, venue, timestamps and sample candles.  
**Phase 1 — Market foundation:** universe, adapters, candle storage, scheduler and health.  
**Phase 2 — Deterministic engine:** indicators, regime, ranking, risk gates and levels.  
**Phase 3 — News intelligence:** RSS/API, deduplication, tagging and grounded summaries.  
**Phase 4 — Dashboard:** chart, Coin of the Day/No Trade, news, plan and outlook.  
**Phase 5 — Evaluation:** walk-forward backtest, paper ledger and benchmark comparison.

## 15. Open decisions

1. USD or CAD quote currency?
2. Which venue should define tradable prices/levels, after regional availability and liquidity checks?
3. Spot-long/neutral only, or short setups as research-only?
4. Daily analysis time and timezone?
5. Which universe and exclusion rules?
6. Which news sources and attribution/licensing constraints?
7. Personal tool only, or possible public/commercial product later?

**Recommended MVP defaults:** personal/local use, USD-quoted spot pairs, one venue chosen after regional/API validation, spot-long/neutral, No Trade enabled and configurable daily run time.

## 16. Glossary

- **OHLCV:** open, high, low, close and volume.
- **ATR:** Average True Range, a volatility measure.
- **VWAP:** Volume Weighted Average Price.
- **Invalidation:** price/action that disproves the setup thesis.
- **Walk-forward:** repeatedly train/tune on past data and test on later unseen data.
- **Look-ahead bias:** using information unavailable at the historical decision time.
- **No Trade:** explicit decision not to publish a setup because risk/quality criteria fail.
