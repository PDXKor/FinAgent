# Frontend

Web UI for FinAgent. Design: [design.md](design.md).

Today: the **Ingestion** page runs recon jobs and shows their status and history.

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
