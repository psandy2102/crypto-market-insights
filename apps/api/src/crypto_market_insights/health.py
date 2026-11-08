"""Application health contract."""

from typing import Final

SERVICE_NAME: Final = "crypto-market-insights"


def health_check() -> dict[str, str]:
    """Return the service health payload used by the API and smoke tests."""
    return {"service": SERVICE_NAME, "status": "ok"}
