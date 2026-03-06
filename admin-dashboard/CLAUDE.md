# CLAUDE.md — Admin Dashboard


> ⚠️ **All changes must go through GitHub pull requests.** Never push to `main` directly. See root `CLAUDE.md` for the full PR workflow.

## Code Review Tools

When your PR is open, NHC runs automated LLM review via `scripts/mr-review`.
- Reviews are SHA-tagged — new pushes invalidate old reviews
- Model chain: Kimi K2.5 → GLM5 → OpenRouter free → DeepSeek V3.2
- Critical findings block approval; warnings/info are advisory
- To run locally: `export $(grep -v '^#' admin-dashboard/.env | xargs) && scripts/mr-review <PR_NUMBER>`
- API keys in `admin-dashboard/.env` (gitignored). GitHub auth comes from `gh auth`.

Read `docs/admin-dashboard.md` for full architecture, endpoints, and deploy process.

## Quick Context

- **Python:** `admin-dashboard/.venv/bin/python` — **always use this, never system Python**
- **Setup:** `cd admin-dashboard && python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
- **Backend:** `backend/main.py` — FastAPI + asyncpg, read-only SQL
- **Frontend:** `frontend/` — React + Vite + TypeScript
- **Tests:** `backend/tests/test_api.py` (28 tests)
- **Deploy:** `scripts/deploy-dashboard --all` — blue-green on ports 8000/8001. **The ONLY way to deploy.**
  - ⚠️ **NEVER run uvicorn or `cloudflared` directly.** NEVER kill server processes manually. The deploy script handles everything.
  - If the deploy script is broken, fix the script — don't work around it.
- **Public URL:** `https://<your-domain>`
- **Auth:** Cloudflare Access (team emails from `ALLOWED_EMAILS`)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/databases` | GET | List available databases |
| `/api/tables` | GET | List all tables (auto-discovered) with row counts + database |
| `/api/tables/{name}/schema` | GET | Column info |
| `/api/tables/{name}/data` | GET | Paginated rows with operator-based filters & sorting |
| `/api/tables/{name}/grouped` | GET | Group-by aggregation |
| `/api/query` | POST | Run arbitrary read-only SQL (`db` param selects database) |
| `/api/nl-query` | POST | Natural language → SQL (`db` param selects database) |
| `/api/usage` | GET | OpenClaw session token usage + model aggregates + Claude rate-limit telemetry |
| `/api/nhl/bankroll` | GET | Current bankroll balance + recent transactions |
| `/api/nhl/bankroll/deposit` | POST | Add bankroll funds |
| `/api/nhl/bankroll/withdrawal` | POST | Remove bankroll funds |
| `/api/nhl/bankroll/summary` | GET | Daily P/L, balance chart, win rate, ROI |

## Multi-Database

Tables are **auto-discovered** from all configured databases on startup. No hardcoded allowlist.
- `nhl_betting` — NHL data (28 tables)
- `polymarket` — Polymarket + crypto data (7+ tables)
- Adding a new DB: add it to `DATABASE_URLS` dict in `main.py`, restart server. Tables appear automatically.

## Frontend Features

- Virtualized scrolling (@tanstack/react-virtual) — infinite scroll, loads 200 rows at a time
- NHL bankroll tracker page — balance, manual ledger entry, transaction history, and chart
- Operator-based filters: "+ Add Filter" → column → operator → value. Stacked AND logic
- Group-by with click-to-filter
- NL Query page: "Ask in English" + "Raw SQL" toggle
- Full viewport layout — table fills remaining space below nav

## Deployment Security Model

The dashboard is **only accessible via Cloudflare Tunnel + Access**. This is non-negotiable.

```
Internet → Cloudflare Tunnel + Access → localhost:8000 (uvicorn)
```

- **uvicorn binds to `127.0.0.1:8000`** — NOT `0.0.0.0`, not accessible from outside
- **Cloudflare Tunnel** is the ONLY public entry point. Fixed domain, not random URLs.
- **Cloudflare Access** — only team emails listed in `ALLOWED_EMAILS` env var can access
- **CORS** locked to `<your-domain>` + localhost
- **Never use Cloudflare quick tunnels** — no auth, guessable URLs
- **Never expose port 8000 directly** — always go through Cloudflare
- **Deploy ONLY via `scripts/deploy-dashboard --all`** — handles blue-green swap, health checks, and tunnel restart

## Frontend Stack & Best Practices

- **React 18+** with Vite + TypeScript
- **Tailwind CSS** for styling (utility-first, no custom CSS unless necessary)
- **@tanstack/react-virtual** for virtualized lists/tables
- **@tanstack/react-query** for server state management
- Charts: **Recharts** or **visx** for data visualization
- Forms: controlled components, no form libraries unless complexity warrants it

### Component Guidelines
- Keep components < 200 LOC — extract hooks and subcomponents
- Use TypeScript interfaces for all props and API responses
- Colocate styles (Tailwind classes) with components
- Use `useMemo`/`useCallback` for expensive computations and stable references
- Error boundaries around major sections

### Vercel Deployment (Future)
- Dashboard frontend can be deployed to Vercel for CDN + edge performance
- API stays on Mac Mini behind Cloudflare Tunnel
- Frontend would call API via `VITE_API_URL` env var
- `vercel.json` rewrites for SPA routing: `{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }`

## Rules

- **All filtering/sorting is server-side** — parameterized SQL, never client-side on 200K+ row tables
- **Tables auto-discovered** — add a DB to `DATABASE_URLS` in `main.py`, tables appear on restart
- **NL query uses OpenRouter free tier** — API key in `.env` (gitignored), fallback chain across free models
- **Update `docs/admin-dashboard.md`** when you add endpoints or change architecture
