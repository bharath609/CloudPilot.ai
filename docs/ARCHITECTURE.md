# Architecture

CloudPilot AI is a single-user desktop application. Electron hosts the shell, a local
FastAPI process serves both the JSON API and the built React SPA, and SQLite stores
everything on disk. No external services are contacted at runtime.

```
┌──────────────────────────── Electron (desktop) ────────────────────────────┐
│  BrowserWindow (contextIsolation, no Node integration)                     │
│      │                                                                     │
│      │ HTTP on 127.0.0.1:<port>                                            │
│      ▼                                                                     │
│  FastAPI  ── serves /api/* and the SPA build                               │
│      │                                                                     │
│      ├── layers/layer1  freshness + native currency validation            │
│      ├── layers/layer2  isolated what-if simulation                        │
│      ├── layers/layer3  spending / capacity / performance anomalies        │
│      ├── layers/layer4  8-step evidence-first investigation                │
│      ├── layers/layer5  deterministic policy engine                        │
│      └── layers/layer6  post-action verification                           │
│      │                                                                     │
│      ▼                                                                     │
│  SQLite (stdlib sqlite3)  billing, resources, findings, decisions, imports │
└────────────────────────────────────────────────────────────────────────────┘
```

## Process lifecycle

1. Electron starts and spawns the backend with the embedded Python interpreter
   (`resources/python/python.exe` in an installed build).
2. It waits for `GET /api/health` to return 200, then loads the SPA.
3. The backend seeds a deterministic synthetic dataset when the database is empty.
4. On quit, Electron terminates the backend.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLOUDPILOT_HOST` | `127.0.0.1` | Backend bind address |
| `CLOUDPILOT_PORT` | `8000` | Backend port |
| `CLOUDPILOT_DB` | `<repo>/cloudpilot.db` | SQLite path (installed app: `%APPDATA%\cloudpilot-ai\cloudpilot.db`) |
| `CLOUDPILOT_FRONTEND_DIST` | `<repo>/frontend/dist` | Built SPA directory |
| `CLOUDPILOT_FRESHNESS_HOURS` | `24` | Staleness threshold |

## Money

Amounts are stored as exact decimal `TEXT` paired with an ISO currency code. All reads and
aggregations are filtered by a single currency. There is no FX rate table, no conversion
function, and no cross-currency total anywhere in the stack.

## Security posture

- The backend binds to loopback only.
- The renderer has no Node integration and communicates through HTTP.
- Policy decisions are evaluated in code, not by a language model.
- Destructive actions (delete, production stop) are blocked or approval-gated.
- The app never mutates a real cloud account; it reads data and simulates changes.
