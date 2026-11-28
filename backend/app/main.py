"""CloudPilot AI — FastAPI application.

Serves a JSON API and the built React SPA from the same origin. All monetary
values keep their original currency; no FX conversion is applied anywhere.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIST, DATA_FRESHNESS_HOURS
from .db import get_db, init_db, money
from .layers.layer1 import assess_freshness
from .layers.layer2 import simulate
from .layers.layer3 import (
    detect_capacity_exhaustion,
    detect_performance_degradation,
    detect_spending_anomaly,
)
from .layers.layer4 import investigate
from .layers.layer5 import PolicyEngine
from .layers.layer6 import verify
from .agent import answer_question
from .importer import (
    ImportRejected,
    data_status,
    import_billing,
    import_resources,
    reset_data,
    template,
)

app = FastAPI(title="CloudPilot AI", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

POLICY = PolicyEngine()

# Initialize eagerly so the API works regardless of server lifecycle hooks.
init_db(seed=True)


@app.on_event("startup")
def _startup() -> None:
    init_db(seed=True)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _daily_amounts(conn: sqlite3.Connection, currency: str) -> Dict[date, Decimal]:
    rows = conn.execute(
        "SELECT invoice_date, amount FROM billing WHERE currency=? ORDER BY invoice_date",
        (currency,),
    ).fetchall()
    out: Dict[date, Decimal] = {}
    for r in rows:
        d = date.fromisoformat(r["invoice_date"])
        out[d] = out.get(d, Decimal("0")) + _dec(r["amount"])
    return out


def _finding_dict(row: Dict[str, Any], decision: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    item = dict(row)
    for key in ("evidence", "assumptions", "warnings"):
        try:
            item[key] = json.loads(item[key])
        except (TypeError, ValueError):
            item[key] = []
    item["latest_decision"] = decision
    return item


# --------------------------------------------------------------------------- #
# API: health / filters
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "version": "2.0.0", "layers": 6}


@app.get("/api/filters")
def filters(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    def distinct(col: str) -> List[str]:
        return [r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM billing ORDER BY {col}")]

    win = conn.execute(
        "SELECT MIN(invoice_date), MAX(invoice_date), COUNT(*) FROM billing"
    ).fetchone()
    last_import = conn.execute(
        "SELECT imported_at FROM imports ORDER BY imported_at DESC LIMIT 1"
    ).fetchone()

    freshness = assess_freshness(last_import[0] if last_import else None, DATA_FRESHNESS_HOURS)
    sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM imports")]
    if not sources:
        data_source = "empty"
    elif sources == ["sample"]:
        data_source = "demo"
    elif "sample" in sources:
        data_source = "mixed"
    else:
        data_source = "imported"
    return {
        "currencies": distinct("currency"),
        "providers": distinct("provider"),
        "services": distinct("service"),
        "projects": distinct("project"),
        "regions": distinct("region"),
        "environments": distinct("environment"),
        "billing": {
            "start": win[0],
            "end": win[1],
            "row_count": win[2],
            "days": (
                (date.fromisoformat(win[1]) - date.fromisoformat(win[0])).days + 1
                if win[0] and win[1]
                else 0
            ),
        },
        "last_import_at": last_import[0] if last_import else None,
        "freshness": freshness,
        "synthetic_data": data_source == "demo",
        "data_source": data_source,
        "note": "All amounts are in their original currency; no FX conversion is applied.",
    }


# --------------------------------------------------------------------------- #
# API: summary / costs
# --------------------------------------------------------------------------- #
@app.get("/api/summary")
def summary(currency: str = "USD", conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    daily = _daily_amounts(conn, currency)
    if not daily:
        return {
            "currency": currency, "total_spend": "0.00", "row_count": 0,
            "window": {"start": None, "end": None, "days": 0},
            "recent_vs_prior_pct": None, "top_services": [],
        }

    dates = sorted(daily)
    start, end = dates[0], dates[-1]
    total = sum(daily.values(), Decimal("0"))
    row_count = conn.execute(
        "SELECT COUNT(*) FROM billing WHERE currency=?", (currency,)
    ).fetchone()[0]

    recent_start = end - timedelta(days=29)
    prior_end = end - timedelta(days=30)
    prior_start = end - timedelta(days=59)
    recent = sum((a for d, a in daily.items() if recent_start <= d <= end), Decimal("0"))
    prior = sum((a for d, a in daily.items() if prior_start <= d <= prior_end), Decimal("0"))
    change_pct = float((recent - prior) / prior * 100) if prior else None

    svc_rows = conn.execute(
        "SELECT service, SUM(CAST(amount AS REAL)) AS amt FROM billing WHERE currency=? "
        "GROUP BY service ORDER BY amt DESC",
        (currency,),
    ).fetchall()
    top_services = []
    for r in svc_rows:
        amt = _dec(r["amt"])
        pct = float(amt / total * 100) if total else 0.0
        top_services.append({"service": r["service"], "amount": _q(amt), "pct": round(pct, 1)})

    return {
        "currency": currency,
        "total_spend": _q(total),
        "row_count": row_count,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
        "recent_vs_prior_pct": round(change_pct, 2) if change_pct is not None else None,
        "top_services": top_services,
    }


@app.get("/api/costs")
def costs(
    currency: str = "USD",
    granularity: str = "daily",
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    daily = _daily_amounts(conn, currency)
    if granularity == "monthly":
        agg: Dict[str, Decimal] = {}
        for d, a in daily.items():
            key = d.strftime("%Y-%m")
            agg[key] = agg.get(key, Decimal("0")) + a
        series = [{"period": k, "amount": _q(v), "currency": currency} for k, v in sorted(agg.items())]
    else:
        series = [
            {"period": d.isoformat(), "amount": _q(a), "currency": currency}
            for d, a in sorted(daily.items())
        ]
    return {"currency": currency, "granularity": granularity, "series": series}


# --------------------------------------------------------------------------- #
# API: resources / findings / decisions
# --------------------------------------------------------------------------- #
@app.get("/api/resources")
def resources(
    currency: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    if currency:
        rows = _rows(conn, "SELECT * FROM resources WHERE currency=? ORDER BY resource_id", (currency,))
    else:
        rows = _rows(conn, "SELECT * FROM resources ORDER BY currency, resource_id")
    return {"resources": rows}


@app.get("/api/findings")
def findings(
    currency: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    if currency:
        rows = _rows(conn, "SELECT * FROM findings WHERE currency=? ORDER BY id", (currency,))
    else:
        rows = _rows(conn, "SELECT * FROM findings ORDER BY currency, id")
    result = []
    for row in rows:
        dec = conn.execute(
            "SELECT decision, note, reviewer, created_at FROM decisions WHERE finding_id=? "
            "ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        result.append(_finding_dict(row, dict(dec) if dec else None))
    return {"findings": result}


class DecisionIn(BaseModel):
    decision: str
    note: str = ""
    reviewer: str = "operator"


@app.post("/api/findings/{finding_id}/decisions")
def record_decision(
    finding_id: str, payload: DecisionIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    exists = conn.execute("SELECT 1 FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Finding not found")
    if payload.decision not in ("accept", "reject", "defer"):
        raise HTTPException(status_code=400, detail="decision must be accept|reject|defer")
    conn.execute(
        "INSERT INTO decisions (finding_id, decision, note, reviewer, created_at) VALUES (?,?,?,?,?)",
        (finding_id, payload.decision, payload.note, payload.reviewer,
         datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
    )
    conn.commit()
    return {"ok": True, "finding_id": finding_id, "decision": payload.decision}


# --------------------------------------------------------------------------- #
# API: imports / audit
# --------------------------------------------------------------------------- #
@app.get("/api/imports")
def imports(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    return {"imports": _rows(conn, "SELECT * FROM imports ORDER BY imported_at DESC")}


# --------------------------------------------------------------------------- #
# API: user data ingestion
# --------------------------------------------------------------------------- #
class BillingImportIn(BaseModel):
    filename: str = "billing.csv"
    content: str
    mode: str = "replace"


class ResourceImportIn(BaseModel):
    filename: str = "resources.csv"
    content: str
    mode: str = "replace"
    currency: str = "USD"


@app.post("/api/imports/billing")
def import_billing_csv(
    payload: BillingImportIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return import_billing(conn, payload.filename, payload.content, payload.mode)
    except ImportRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/imports/resources")
def import_resources_csv(
    payload: ResourceImportIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return import_resources(
            conn, payload.filename, payload.content, payload.mode, default_currency=payload.currency
        )
    except ImportRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/imports/template")
def import_template(dataset: str = "billing") -> Response:
    if dataset not in ("billing", "resources"):
        raise HTTPException(status_code=400, detail="dataset must be 'billing' or 'resources'")
    return Response(
        content=template(dataset),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="cloudpilot-{dataset}-template.csv"'
        },
    )


@app.get("/api/data/status")
def dataset_status(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    return data_status(conn)


class ResetIn(BaseModel):
    mode: str = "demo"


@app.post("/api/data/reset")
def dataset_reset(
    payload: Optional[ResetIn] = None, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return reset_data(conn, payload.mode if payload else "demo")
    except ImportRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- #
# API: grounded assistant
# --------------------------------------------------------------------------- #
class AskIn(BaseModel):
    question: str
    currency: str = "USD"


@app.post("/api/assistant/ask")
def assistant_ask(
    payload: AskIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    return answer_question(conn, payload.question, payload.currency)


@app.get("/api/audit")
def audit(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    rows = _rows(
        conn,
        """SELECT d.id, d.finding_id, d.decision, d.note, d.reviewer, d.created_at,
                  f.resource_id, f.finding_type, f.currency
           FROM decisions d LEFT JOIN findings f ON f.id = d.finding_id
           ORDER BY d.id DESC""",
    )
    return {"decisions": rows}


# --------------------------------------------------------------------------- #
# API: forecasts
# --------------------------------------------------------------------------- #
@app.get("/api/forecasts")
def forecasts(
    currency: str = "USD", horizon: int = 14, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    daily = _daily_amounts(conn, currency)
    if not daily:
        return {"currency": currency, "history": [], "forecast": [], "metrics": None}
    dates = sorted(daily)
    values = [float(daily[d]) for d in dates]

    # In-sample 7-day moving-average evaluation
    errors: List[float] = []
    pct_errors: List[float] = []
    window = 7
    for i in range(window, len(values)):
        pred = sum(values[i - window:i]) / window
        err = values[i] - pred
        errors.append(err)
        if values[i]:
            pct_errors.append(abs(err) / values[i])
    mae = sum(abs(e) for e in errors) / len(errors) if errors else 0.0
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5 if errors else 0.0
    mape = (sum(pct_errors) / len(pct_errors) * 100) if pct_errors else 0.0

    base = sum(values[-window:]) / min(window, len(values))
    band = (sum((v - base) ** 2 for v in values[-window:]) / min(window, len(values))) ** 0.5
    last_date = dates[-1]
    forecast = []
    for h in range(1, horizon + 1):
        d = last_date + timedelta(days=h)
        forecast.append({
            "date": d.isoformat(),
            "amount": _q(Decimal(str(base))),
            "low": _q(Decimal(str(max(0.0, base - band)))),
            "high": _q(Decimal(str(base + band))),
            "currency": currency,
        })

    history = [{"date": d.isoformat(), "amount": _q(a)} for d, a in zip(dates, [daily[x] for x in dates])]
    return {
        "currency": currency,
        "history": history,
        "forecast": forecast,
        "metrics": {"mae": round(mae, 2), "rmse": round(rmse, 2), "mape": round(mape, 2)},
    }


# --------------------------------------------------------------------------- #
# API v1: layers
# --------------------------------------------------------------------------- #
class SpendAnomalyIn(BaseModel):
    currency: str = "USD"
    current_spend: Optional[float] = None


@app.post("/api/v1/anomalies/spending")
def anomaly_spending(
    payload: SpendAnomalyIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    daily = _daily_amounts(conn, payload.currency)
    values = [float(v) for _, v in sorted(daily.items())]
    current = payload.current_spend if payload.current_spend is not None else (values[-1] if values else 0.0)
    result = detect_spending_anomaly(values[:-1] if payload.current_spend is None and len(values) > 1 else values,
                                     current, payload.currency)
    return result.to_dict()


class CapacityIn(BaseModel):
    resource_id: str


@app.post("/api/v1/anomalies/capacity")
def anomaly_capacity(payload: CapacityIn, conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM resources WHERE resource_id=?", (payload.resource_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    r = dict(row)
    return detect_capacity_exhaustion(r["cpu_pct"], r["resource_id"], r["currency"]).to_dict()


class PerformanceIn(BaseModel):
    resource_id: str
    historical: Optional[List[float]] = None
    current: Optional[List[float]] = None


@app.post("/api/v1/anomalies/performance")
def anomaly_performance(
    payload: PerformanceIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM resources WHERE resource_id=?", (payload.resource_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    r = dict(row)
    hist = payload.historical or [r["cpu_pct"] + 12, r["cpu_pct"] + 14, r["cpu_pct"] + 13]
    cur = payload.current or [r["cpu_pct"], r["cpu_pct"] - 1, r["cpu_pct"]]
    return detect_performance_degradation(hist, cur, r["resource_id"], r["currency"]).to_dict()


class PolicyIn(BaseModel):
    action_type: str
    resource_id: str = ""
    environment: str = "production"
    requesting_user: str = "operator"
    spending_delta: float = 0.0


@app.post("/api/v1/policies/evaluate")
def policies_evaluate(payload: PolicyIn) -> Dict[str, Any]:
    return POLICY.evaluate(
        payload.action_type, payload.resource_id, payload.environment,
        payload.requesting_user, payload.spending_delta,
    ).to_dict()


class SimulateIn(BaseModel):
    resource_id: str
    scenario: str = "stop"
    utilization_retention: float = 0.0
    sku_ratio: Optional[float] = None


@app.post("/api/v1/twin/simulate")
def twin_simulate(payload: SimulateIn, conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    res = conn.execute("SELECT * FROM resources WHERE resource_id=?", (payload.resource_id,)).fetchone()
    finding = conn.execute(
        "SELECT baseline_monthly_cost, currency FROM findings WHERE resource_id=? LIMIT 1",
        (payload.resource_id,),
    ).fetchone()
    if res:
        r = dict(res)
        baseline = finding["baseline_monthly_cost"] if finding else _q(_dec(r["cost_per_hour"]) * Decimal("730"))
        currency = finding["currency"] if finding else r["currency"]
    elif finding:
        r = {"resource_id": payload.resource_id}
        baseline = finding["baseline_monthly_cost"]
        currency = finding["currency"]
    else:
        raise HTTPException(status_code=404, detail="Resource/finding not found")

    resource_ctx = {"resource_id": payload.resource_id, "currency": currency, "baseline_monthly_cost": baseline}
    return simulate(resource_ctx, payload.scenario, payload.utilization_retention, payload.sku_ratio)


class InvestigateIn(BaseModel):
    finding_id: str


@app.post("/api/v1/investigation/start")
def investigation_start(
    payload: InvestigateIn, conn: sqlite3.Connection = Depends(get_db)
) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM findings WHERE id=?", (payload.finding_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    finding = _finding_dict(dict(row), None)
    res = conn.execute(
        "SELECT * FROM resources WHERE resource_id=?", (finding["resource_id"],)
    ).fetchone()
    daily = _daily_amounts(conn, finding["currency"])
    inv = investigate(
        f"inv-{payload.finding_id}",
        finding,
        dict(res) if res else None,
        [float(v) for _, v in sorted(daily.items())],
    )
    return inv.to_dict()


class VerifyIn(BaseModel):
    action_id: str
    resource_id: str
    expected: Dict[str, Any] = {}
    observed: Optional[Dict[str, Any]] = None


@app.post("/api/v1/verification/run")
def verification_run(payload: VerifyIn) -> Dict[str, Any]:
    return verify(payload.action_id, payload.resource_id, payload.expected, payload.observed).to_dict()


# --------------------------------------------------------------------------- #
# SPA serving
# --------------------------------------------------------------------------- #
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/")
def index():
    idx = FRONTEND_DIST / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"message": "CloudPilot AI API", "docs": "/docs", "health": "/api/health"})


@app.get("/logo.svg")
def logo():
    path = FRONTEND_DIST / "logo.svg"
    if path.exists():
        return FileResponse(str(path), media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Logo not found")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    idx = FRONTEND_DIST / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"detail": "Frontend not built. Run: cd frontend && npm run build"}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
