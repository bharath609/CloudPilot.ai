# CloudPilot AI

<img src="frontend/assets/logo-256.png" alt="CloudPilot AI" width="96" align="right" />

**Predict. Simulate. Investigate. Act.**

CloudPilot AI is a desktop FinOps / cloud-operations console. It ingests billing and
utilization data, detects waste and anomalies, investigates them with an evidence-first
agent, projects what-if savings in an isolated simulation, gates changes through a policy
engine, and verifies the outcome afterwards.

It ships as a Windows desktop application with a bundled Python runtime, so the installed
app needs no separate Python, Node.js, or cloud credentials.

## Download

Get the latest Windows installer from
[GitHub Releases](https://github.com/bharath609/CloudPilot.ai/releases/latest):

- **`CloudPilot AI Setup 2.1.0.exe`** (~129 MB, Windows 10/11 x64)
- Standard NSIS installer: choose the install location, desktop shortcut included.
- The app starts its own local backend and stores its database in `%APPDATA%\cloudpilot-ai`.

## What it does

| Layer | Responsibility | Where |
| --- | --- | --- |
| 1. Data Intelligence | Import validation, data freshness, native currency handling | `backend/app/layers/layer1.py` |
| 2. Simulation | What-if projections isolated from production | `backend/app/layers/layer2.py` |
| 3. Predictive Intelligence | Spending, capacity, and performance anomaly detection | `backend/app/layers/layer3.py` |
| 4. Investigation | 8-step evidence-first investigation; says "insufficient evidence" when true | `backend/app/layers/layer4.py` |
| 5. Policy Execution | Deterministic policy engine; destructive actions blocked or approval-gated | `backend/app/layers/layer5.py` |
| 6. Continuous Verification | Post-action state/cost/performance verification | `backend/app/layers/layer6.py` |

### Product surfaces

- **Command Center** — spend, row counts, 30-day change, data freshness, top services, and a
  badge that tells you whether you are looking at demo data or your own imported data.
- **AI Assistant** — ask questions about your costs, resources, findings, policy, and data
  quality. Answers are computed from the local database and cite the tables they used.
- **Cost Explorer** — daily/monthly series per currency.
- **Resources** — inventory with utilization and health status.
- **Findings** — waste and rightsizing opportunities with evidence, assumptions, warnings,
  confidence, risk, plus Accept / Reject / Defer decisions and on-demand investigation.
- **Forecasts** — empirical 14-day projection with MAE / RMSE / MAPE (in-sample).
- **Simulation Lab** — stop or rightsize a resource; shows assumptions and warnings.
- **Anomalies** — spending, capacity, and performance detection plus policy evaluation.
- **Imports** — bring your own CSV billing and resource inventory, with a row-level
  validation report (accepted/rejected with line numbers), replace/append modes, import
  history, and a one-click reset back to demo data.
- **Audit** — append-only decision trail.

## Currency policy (important)

USD, EUR, and INR are **native** currencies. Amounts are stored as exact decimal text with
their currency, and every query is scoped to one currency.

- There is **no FX conversion** anywhere in the codebase.
- There are **no combined cross-currency totals**.
- Switching currency in the UI switches the dataset, not the exchange rate.

## Architecture

```
frontend/               React 19 + TypeScript + Vite SPA
  electron/             Desktop shell: spawns the backend, loads the SPA
  src/                  Pages, API client, currency context
backend/                FastAPI + stdlib sqlite3 (exact decimals)
  app/layers/           The six engineering layers
  app/importer.py       CSV import, validation, findings generation, dataset reset
  app/agent.py          Grounded, local-only assistant (no external AI service)
  app/db.py             Schema + deterministic multi-currency seed
  app/main.py           JSON API + SPA hosting
scripts/                Sample data, release smoke test, desktop build
```

The desktop app binds the backend to `127.0.0.1` only. The renderer is sandboxed with
`contextIsolation` and no Node integration.

## Run from source

### Backend

```powershell
cd backend
python -m pip install -r requirements.txt
python run.py                     # http://127.0.0.1:8000
```

### Frontend (browser dev server with API proxy)

```powershell
cd frontend
npm install
npm run dev                       # http://127.0.0.1:5173
```

### Desktop app from source

```powershell
cd frontend
npm install
npm run build                     # builds the SPA into frontend/dist
npm run electron                  # Electron spawns the backend and opens the app
```

## Build the Windows installer

```powershell
# from the repository root
powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
```

The script:

1. Creates `frontend/pyrt`, a self-contained Python runtime with FastAPI/Uvicorn installed.
2. Builds the React SPA.
3. Packages Electron + backend + SPA + Python runtime with electron-builder (NSIS).
4. Writes the installer to `frontend/dist-electron/`.

Requirements on the build machine: Windows x64, Python 3.12+, Node.js 20+.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service status |
| GET | `/api/filters` | Currencies, providers, services, freshness |
| GET | `/api/summary?currency=USD` | Spend summary + top services |
| GET | `/api/costs?currency=USD&granularity=daily` | Time series |
| GET | `/api/resources` | Resource inventory |
| GET | `/api/findings` | Findings with latest decision |
| POST | `/api/findings/{id}/decisions` | Record accept / reject / defer |
| GET | `/api/forecasts?currency=USD` | History + 14-day forecast + metrics |
| GET | `/api/imports` | Import history |
| GET | `/api/data/status` | Demo / imported / mixed / empty dataset status |
| GET | `/api/imports/template?kind=billing` | Download a CSV template |
| POST | `/api/imports/billing` | Import billing CSV (`mode=replace\|append`) |
| POST | `/api/imports/resources` | Import resource inventory CSV (`currency` is the fallback when the file has none) |
| POST | `/api/data/reset` | Reset to the built-in demo dataset |
| POST | `/api/assistant/ask` | Ask the grounded local assistant |
| GET | `/api/audit` | Decision audit trail |
| POST | `/api/v1/anomalies/spending` | Spending anomaly |
| POST | `/api/v1/anomalies/capacity` | Capacity exhaustion risk |
| POST | `/api/v1/anomalies/performance` | Performance degradation |
| POST | `/api/v1/policies/evaluate` | Policy decision for an action |
| POST | `/api/v1/twin/simulate` | Isolated what-if projection |
| POST | `/api/v1/investigation/start` | 8-step investigation |
| POST | `/api/v1/verification/run` | Post-action verification |

Interactive docs: `http://127.0.0.1:8000/docs`.

## Tests

```powershell
cd backend
python smoke_api.py       # 28 checks across all currencies and layers
python smoke_import.py    # 44 checks for CSV import, dataset status, reset, assistant
python smoke_spa.py       # SPA hosting and fallback routing
```

## Data

The app ships with a deterministic synthetic dataset (no real cloud accounts): 60 days of
billing for USD, EUR, and INR, resource inventory, findings, and import records. It is
re-seeded automatically when the database is empty.

You are not limited to the demo data:

- **Imports → Billing** accepts a CSV with `invoice_date, provider, service, project,
  region, environment, amount, currency`. Rows are validated one by one; rejected rows are
  reported with their line number and the reason, and only accepted rows are written.
- **Imports → Resources** only requires `resource_id`; `name, resource_type, provider,
  region, environment, currency, cost_per_hour, cpu_pct, memory_pct, status, sku` are
  optional and get explicit defaults (plus a warning in the report). Imported inventory
  generates threshold-based findings: idle below 15% CPU, rightsizing below 45%. Repeated
  rows for the same `resource_id` collapse to the latest snapshot.
- Common export headers are recognised automatically: `usage_date` → `invoice_date`,
  `cost_amount` → `amount`, `currency_code` → `currency`, `cpu_avg_pct` → `cpu_pct`, and
  similar aliases for provider, service, project, region, environment, unit, and SKU.
- `replace` clears the target dataset before writing; `append` keeps what is there. The
  overview badge and `GET /api/data/status` always show which dataset you are looking at,
  and **Reset to demo** restores the seed data.

## Assistant scope

The assistant in the app is deterministic and grounded: it translates a question into a
local SQL query, then reports the result together with the facts it used and the tables it
read. It has no external AI service, no API key, and no network egress — your data never
leaves the machine. It answers questions about totals, top services, resources, findings,
policy outcomes, and data quality, and it explicitly refuses anything outside that scope
rather than guessing.

## Honest limitations

- This build **reads and simulates**; it never mutates a real cloud account.
- Forecasts are a flat 7-day moving average with a dispersion band, not a trained model.
- Findings are only actionable after an owner confirms the workload behavior; the UI and
  investigation output keep that warning visible.
- Findings generated from an imported resource inventory use two simple thresholds
  (idle < 15% CPU, rightsize < 45% CPU) and are labelled as such — they are a starting
  point for review, not a verdict.
- The assistant is a grounded query layer, not a language model: it is precise about your
  data and deliberately refuses questions it cannot answer from the database.

## License

Released for demonstration and evaluation. See the repository for details.
