# Contributing

## MVP boundary

Crypto Market Insights is local-first research and decision-support software. The MVP is
read-only: it does not execute trades, manage wallets, custody assets, or provide personalized
financial, tax, or legal advice. Recommendations are hypothetical and may explicitly return
**No Trade**.

## Supported toolchain

- Python 3.11 or newer
- Node.js 22 or newer for the dashboard
- Docker Desktop with Compose for PostgreSQL and local services
- Ollama installed locally when local LLM features are enabled

Create a virtual environment at the repository root and install the API project with development
dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "apps/api[dev]"
```

## Validation commands

Run these commands from the repository root:

```powershell
python -m ruff format --check apps/api
python -m ruff check apps/api
python -m mypy apps/api/src
python -m pytest apps/api/tests
```

Install and validate the frontend from its directory:

```powershell
cd apps/web
npm install
npm run typecheck
npm run test
npm run build
```

## Code conventions

- Use UTC timestamps at service boundaries and preserve source and retrieval timestamps.
- Keep calculations deterministic and independently test them with fixed fixtures.
- Prefer explicit types and small functions over implicit global state.
- Keep provider credentials in local environment variables, never in source control.
- Treat article content and provider responses as untrusted input.
- Preserve the local-first, read-only MVP boundary.
- Use the repository formatter and linter rather than editor-specific formatting.

## Configuration and secrets

Copy `.env.example` to `.env` for local configuration. The `.env` file is ignored by Git.
Never commit API keys, database passwords, tokens, private keys, or exported provider responses
containing credentials. Use the documented placeholder values in examples and tests.
