# Crypto Market Insights Web

The Next.js dashboard for the Crypto Market Insights monorepo.

## Local development

From the repository root:

```powershell
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`. The shell intentionally displays empty states until the backend
publishes real data.

Set `NEXT_PUBLIC_API_BASE_URL` when the API is not running at `http://localhost:8000`.

## Validation

```powershell
npm run typecheck
npm run test
npm run build
```
