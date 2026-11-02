# Frontend

Web UI for FinAgent. Design: [design.md](design.md).

Pages: **Ingestion** (run recon jobs; filter and sort run history) and **Data viewer** (browse any table or view with filters, sorting, paging). Page state lives in the URL, so views can be bookmarked.

## Run

```bash
# 1. Data API (in ../data; needs FINAGENT_SEC_USER_AGENT in data/.env)
finagent-data serve                 # http://127.0.0.1:8765

# 2. UI
cp .env.example .env                # set FINAGENT_DATA_TOKEN if the API uses one
npm install
npm run dev                         # http://localhost:5173
```

| Script | Does |
|---|---|
| `npm run dev` | Dev server; proxies `/api/data` to `FINAGENT_DATA_URL` |
| `npm test` | Vitest (MSW fakes the API) |
| `npm run typecheck` | `tsc` |
| `npm run build` | Typecheck + static build to `dist/` |
| `npm run gen:api` | Regenerate `src/api/generated/data.d.ts` from the running API |
