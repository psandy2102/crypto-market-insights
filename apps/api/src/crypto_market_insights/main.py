"""FastAPI application entry point."""

from fastapi import FastAPI

from crypto_market_insights.health import health_check

app = FastAPI(title="Crypto Market Insights API")


@app.get("/health")
def get_health() -> dict[str, str]:
    """Return API readiness status."""
    return health_check()
