"""Grounded in-app assistant.

The assistant answers questions by querying the local dataset and the same policy and
anomaly code the rest of the app uses. It is deliberately not a free-form text generator:
every number in an answer comes from a query, and the response lists the sources it used.
When a question is outside what the stored data can support, it says so and suggests a
question it can answer.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .config import ALLOWED_CURRENCIES, DATA_FRESHNESS_HOURS
from .layers.layer1 import assess_freshness
from .layers.layer3 import detect_capacity_exhaustion, detect_spending_anomaly
from .layers.layer5 import PolicyEngine

POLICY = PolicyEngine()

CAPABILITIES = [
    "What did we spend in EUR?",
    "What are the top services by cost?",
    "How does this month compare with last month?",
    "Show me the findings and their baseline cost.",
    "What is the forecast for the next 14 days?",
    "Is the data stale, and when was it last imported?",
    "Can I stop r-ec2-001?",
    "Are there any anomalies right now?",
    "How do I import my own billing data?",
]


def _money(amount: Any, currency: str) -> str:
    return f"{currency} {Decimal(str(amount)):,.2f}"


def _sources(*items: str) -> List[str]:
    return list(items)


def _result(
    answer: str,
    intent: str,
    currency: str,
    facts: Optional[List[Dict[str, str]]] = None,
    sources: Optional[List[str]] = None,
    confidence: str = "high",
) -> Dict[str, Any]:
    return {
        "answer": answer,
        "intent": intent,
        "currency": currency,
        "facts": facts or [],
        "sources": sources or [],
        "confidence": confidence,
        "grounded": True,
        "mode": "local-data",
        "suggestions": CAPABILITIES,
    }


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def _daily_totals(conn: sqlite3.Connection, currency: str) -> Dict[date, Decimal]:
    rows = conn.execute(
        "SELECT invoice_date, amount FROM billing WHERE currency=? ORDER BY invoice_date",
        (currency,),
    ).fetchall()
    totals: Dict[date, Decimal] = defaultdict(Decimal)
    for row in rows:
        totals[date.fromisoformat(row["invoice_date"])] += Decimal(str(row["amount"]))
    return dict(totals)


def _total(conn: sqlite3.Connection, currency: str) -> Tuple[Decimal, int, Optional[str], Optional[str]]:
    row = conn.execute(
        """SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) AS total, COUNT(*) AS rows,
                  MIN(invoice_date) AS start, MAX(invoice_date) AS end
           FROM billing WHERE currency=?""",
        (currency,),
    ).fetchone()
    daily = _daily_totals(conn, currency)
    exact = sum(daily.values(), Decimal("0"))
    return exact, int(row["rows"]), row["start"], row["end"]


def _service_totals(conn: sqlite3.Connection, currency: str) -> List[Tuple[str, Decimal]]:
    rows = conn.execute(
        "SELECT service, amount FROM billing WHERE currency=?", (currency,)
    ).fetchall()
    totals: Dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        totals[row["service"]] += Decimal(str(row["amount"]))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _detect_currency(question: str, fallback: str) -> str:
    upper = question.upper()
    mentioned = [c for c in ALLOWED_CURRENCIES if re.search(rf"\b{c}\b", upper)]
    return mentioned[0] if len(mentioned) == 1 else fallback


def _find_resources(conn: sqlite3.Connection, question: str) -> List[Dict[str, Any]]:
    words = question.lower()
    rows = [dict(r) for r in conn.execute("SELECT * FROM resources ORDER BY resource_id")]
    matches = [
        r
        for r in rows
        if r["resource_id"].lower() in words or r["name"].lower() in words
    ]
    return matches


# --------------------------------------------------------------------------- #
# Intent handlers
# --------------------------------------------------------------------------- #
def _answer_import(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    status = conn.execute("SELECT COUNT(*) FROM billing").fetchone()[0]
    answer = (
        "You can load your own data from the Imports page. Upload a CSV under "
        "'Import billing CSV' with at least these columns: invoice_date (YYYY-MM-DD), "
        "provider, service, amount, currency. Optional columns add region, environment, "
        "project, resource_id, usage_amount, unit, unit_price, and sku. "
        "Choose 'Replace current dataset' to remove the demo rows, or 'Append' to keep them. "
        "Amounts must already be in their own currency: USD, EUR, or INR - the app never converts. "
        "You can also download a ready-to-fill template there. For the Resources page you can "
        "upload an inventory CSV with resource_id, name, resource_type, provider, currency, "
        "cost_per_hour, and optional cpu_pct, memory_pct, environment, region, status, sku."
    )
    facts = [
        {"label": "Current billing rows", "value": str(status)},
        {"label": "Supported currencies", "value": ", ".join(ALLOWED_CURRENCIES)},
        {"label": "Where", "value": "Imports page -> Import billing CSV"},
    ]
    return _result(
        answer, "how_to_import", currency, facts, _sources("imports table"), "high"
    )


def _answer_dataset(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    rows = conn.execute(
        """SELECT currency, COUNT(*) AS rows, MIN(invoice_date) AS start, MAX(invoice_date) AS end
           FROM billing GROUP BY currency ORDER BY currency"""
    ).fetchall()
    last_import = conn.execute("SELECT MAX(imported_at) FROM imports").fetchone()[0]
    freshness = assess_freshness(last_import, DATA_FRESHNESS_HOURS)

    if not rows:
        return _result(
            "There are no billing rows in the database. Import a CSV from the Imports page "
            "to start, or restore the demo dataset.",
            "dataset",
            currency,
            [{"label": "Billing rows", "value": "0"}],
            _sources("billing table", "imports table"),
            "high",
        )

    parts = [
        f"{r['currency']}: {r['rows']} rows from {r['start']} to {r['end']}" for r in rows
    ]
    age = freshness.get("data_age_hours")
    stale_note = (
        f"The newest import is {age} hours old, so the data is marked stale."
        if freshness.get("freshness_warning")
        else f"The newest import is {age} hours old, so the data is fresh."
        if age is not None
        else "No import timestamp is recorded."
    )
    answer = (
        "The local dataset contains "
        + "; ".join(parts)
        + ". "
        + stale_note
        + " All amounts stay in their original currency."
    )
    facts = [
        {"label": "Currencies", "value": ", ".join(c["currency"] for c in rows)},
        {"label": "Total billing rows", "value": str(sum(c["rows"] for c in rows))},
        {"label": "Last import", "value": last_import or "not recorded"},
        {"label": "Data quality", "value": str(freshness.get("data_quality"))},
    ]
    return _result(
        answer, "dataset", currency, facts, _sources("billing table", "imports table"), "high"
    )


def _answer_total(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    total, row_count, start, end = _total(conn, currency)
    if row_count == 0:
        return _result(
            f"There is no billing data in {currency}. The active currency has no rows; "
            "import data or switch currency.",
            "total_spend",
            currency,
            [{"label": f"Rows in {currency}", "value": "0"}],
            _sources("billing table"),
            "high",
        )
    services = _service_totals(conn, currency)
    top = services[0] if services else None
    answer = (
        f"Total spend in {currency} is {_money(total, currency)} across {row_count} billing rows, "
        f"covering {start} to {end}."
    )
    if top:
        answer += f" The largest service is {top[0]} at {_money(top[1], currency)}."
    answer += " No cross-currency total is calculated."
    facts = [
        {"label": "Total", "value": _money(total, currency)},
        {"label": "Billing rows", "value": str(row_count)},
        {"label": "Window", "value": f"{start} to {end}"},
    ]
    if top:
        facts.append({"label": "Largest service", "value": f"{top[0]} ({_money(top[1], currency)})"})
    return _result(answer, "total_spend", currency, facts, _sources("billing table"), "high")


def _answer_top_services(conn: sqlite3.Connection, currency: str, limit: int = 5) -> Dict[str, Any]:
    services = _service_totals(conn, currency)
    if not services:
        return _result(
            f"There is no billing data in {currency} to break down.",
            "top_services",
            currency,
            [],
            _sources("billing table"),
            "high",
        )
    total = sum((amount for _, amount in services), Decimal("0"))
    ranked = services[:limit]
    lines = [
        f"{name}: {_money(amount, currency)} ({float(amount / total * 100):.1f}%)"
        for name, amount in ranked
    ]
    answer = f"Top services in {currency} by billed amount: " + "; ".join(lines) + "."
    facts = [
        {"label": name, "value": f"{_money(amount, currency)} ({float(amount / total * 100):.1f}%)"}
        for name, amount in ranked
    ]
    return _result(
        answer,
        "top_services",
        currency,
        facts,
        _sources(f"billing table ({len(services)} services)"),
        "high",
    )


def _answer_trend(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    daily = _daily_totals(conn, currency)
    if not daily:
        return _result(
            f"There is no billing history in {currency} for a comparison.",
            "trend",
            currency,
            [],
            _sources("billing table"),
            "high",
        )
    dates = sorted(daily)
    end = dates[-1]
    recent_start = date.fromordinal(end.toordinal() - 29)
    prior_end = date.fromordinal(end.toordinal() - 30)
    prior_start = date.fromordinal(end.toordinal() - 59)
    recent = sum((a for d, a in daily.items() if recent_start <= d <= end), Decimal("0"))
    prior = sum((a for d, a in daily.items() if prior_start <= d <= prior_end), Decimal("0"))
    if prior == 0:
        return _result(
            f"The last 30 days in {currency} total {_money(recent, currency)}, but there is no "
            "prior 30-day window to compare against.",
            "trend",
            currency,
            [{"label": "Recent 30 days", "value": _money(recent, currency)}],
            _sources("billing table"),
            "high",
        )
    change = (recent - prior) / prior * 100
    direction = "higher" if change > 0 else "lower"
    answer = (
        f"In {currency}, the last 30 days total {_money(recent, currency)} versus "
        f"{_money(prior, currency)} in the prior 30 days - {abs(change):.2f}% {direction}."
    )
    facts = [
        {"label": "Recent 30 days", "value": _money(recent, currency)},
        {"label": "Prior 30 days", "value": _money(prior, currency)},
        {"label": "Change", "value": f"{change:+.2f}%"},
    ]
    return _result(
        answer, "trend", currency, facts, _sources("billing table, 30-day windows"), "high"
    )


def _answer_forecast(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    daily = _daily_totals(conn, currency)
    if len(daily) < 8:
        return _result(
            f"Forecasting {currency} needs at least 8 daily data points; the dataset has "
            f"{len(daily)}. Import more history to enable it.",
            "forecast",
            currency,
            [{"label": "Daily points", "value": str(len(daily))}],
            _sources("billing table"),
            "high",
        )
    values = [float(daily[d]) for d in sorted(daily)]
    window = 7
    errors = [values[i] - sum(values[i - window:i]) / window for i in range(window, len(values))]
    mae = sum(abs(e) for e in errors) / len(errors)
    base = sum(values[-window:]) / window
    band = (sum((v - base) ** 2 for v in values[-window:]) / window) ** 0.5
    answer = (
        f"The 7-day moving-average baseline for {currency} is {_money(base, currency)} per day. "
        f"A 14-day projection is about {_money(base * 14, currency)}, with a historical "
        f"one-sigma daily band of {_money(band, currency)}. In-sample MAE is "
        f"{_money(mae, currency)}. This is an empirical baseline, not a trained model."
    )
    facts = [
        {"label": "Daily baseline", "value": _money(base, currency)},
        {"label": "14-day projection", "value": _money(base * 14, currency)},
        {"label": "In-sample MAE", "value": _money(mae, currency)},
        {"label": "History used", "value": f"{len(values)} days"},
    ]
    return _result(
        answer, "forecast", currency, facts, _sources("billing table, 7-day moving average"), "medium"
    )


def _answer_findings(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE currency=? ORDER BY baseline_monthly_cost DESC",
        (currency,),
    ).fetchall()
    if not rows:
        return _result(
            f"There are no findings for {currency}. Findings come from the resource inventory; "
            "import a resources CSV from the Imports page to generate threshold-based findings.",
            "findings",
            currency,
            [{"label": "Findings", "value": "0"}],
            _sources("findings table"),
            "high",
        )
    baseline = sum((Decimal(str(r["baseline_monthly_cost"])) for r in rows), Decimal("0"))
    lines = [
        f"{r['finding_type'].replace('_', ' ')} on {r['resource_id']} "
        f"(baseline {_money(r['baseline_monthly_cost'], currency)}, risk {r['risk']})"
        for r in rows[:5]
    ]
    answer = (
        f"{currency} has {len(rows)} finding(s) with a combined monthly baseline of "
        f"{_money(baseline, currency)}: "
        + "; ".join(lines)
        + ". Baseline is not the same as savings - run a simulation to size the change."
    )
    facts = [
        {"label": "Findings", "value": str(len(rows))},
        {"label": "Combined baseline", "value": _money(baseline, currency)},
        {"label": "Highest risk", "value": max((r["risk"] for r in rows), key=lambda v: ["low", "medium", "high"].index(v) if v in ("low", "medium", "high") else 0)},
    ]
    return _result(
        answer, "findings", currency, facts, _sources("findings table"), "medium"
    )


def _answer_resource(conn: sqlite3.Connection, question: str, currency: str, matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(matches) > 1:
        listing = "; ".join(
            f"{m['resource_id']} ({m['name']}, {m['currency']})" for m in matches[:6]
        )
        return _result(
            f"Several resources match that question: {listing}. Ask about one resource_id.",
            "resource_lookup",
            currency,
            [{"label": "Matches", "value": str(len(matches))}],
            _sources("resources table"),
            "medium",
        )
    r = matches[0]
    monthly = Decimal(str(r["cost_per_hour"])) * Decimal("730")
    answer = (
        f"{r['resource_id']} ({r['name']}) is a {r['resource_type']} {r['provider']} resource in "
        f"{r['region']}, environment {r['environment']}, billed in {r['currency']}. "
        f"CPU is {float(r['cpu_pct']):.1f}% and memory is {float(r['memory_pct']):.1f}%, "
        f"status {r['status']}. At {_money(r['cost_per_hour'], r['currency'])} per hour it costs "
        f"about {_money(monthly, r['currency'])} per month (730 hours, same currency, no FX)."
    )
    facts = [
        {"label": "Resource", "value": f"{r['resource_id']} / {r['name']}"},
        {"label": "CPU", "value": f"{float(r['cpu_pct']):.1f}%"},
        {"label": "Memory", "value": f"{float(r['memory_pct']):.1f}%"},
        {"label": "Cost per hour", "value": _money(r["cost_per_hour"], r["currency"])},
        {"label": "Monthly estimate", "value": _money(monthly, r["currency"])},
        {"label": "Status", "value": r["status"]},
    ]
    return _result(
        answer, "resource_lookup", r["currency"], facts, _sources("resources table"), "high"
    )


def _answer_policy(question: str, currency: str, matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    lower = question.lower()
    if "delete" in lower or "terminate" in lower or "remove" in lower:
        action = "delete_resource"
    elif "resize" in lower or "rightsize" in lower or "downsize" in lower:
        action = "resize_resource"
    else:
        action = "stop_resource"

    resource = matches[0] if matches else None
    environment = (
        resource["environment"]
        if resource
        else ("production" if "prod" in lower else "staging" if "staging" in lower else "production")
    )
    resource_id = resource["resource_id"] if resource else "unspecified"
    decision = POLICY.evaluate(action, resource_id, environment, "assistant", 0.0)
    verdict = "allowed" if decision.allowed else "blocked"
    approval = (
        " It requires human approval." if decision.requires_approval else " No approval is required."
    )
    answer = (
        f"Policy verdict for {action} on {resource_id} in {environment}: {verdict}.{approval}"
    )
    if decision.violations:
        answer += " Reasons: " + " ".join(decision.violations)
    facts = [
        {"label": "Action", "value": action},
        {"label": "Environment", "value": environment},
        {"label": "Allowed", "value": "yes" if decision.allowed else "no"},
        {"label": "Approval required", "value": "yes" if decision.requires_approval else "no"},
        {"label": "Rule", "value": decision.rule_id or "none"},
    ]
    return _result(
        answer, "policy", currency, facts, _sources("policy engine (layer 5)"), "high"
    )


def _answer_anomalies(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    daily = _daily_totals(conn, currency)
    values = [float(v) for _, v in sorted(daily.items())]
    facts: List[Dict[str, str]] = []
    parts: List[str] = []

    if len(values) >= 3:
        spend = detect_spending_anomaly(values[:-1], values[-1], currency)
        state = "detected" if spend.detected else "not detected"
        parts.append(
            f"Spending anomaly {state}: latest day {_money(values[-1], currency)}, "
            f"baseline {_money(spend.baseline, currency)} ({spend.change_pct:+.1f}%)."
        )
        facts.append({"label": "Spending anomaly", "value": state})
        facts.append({"label": "Latest day", "value": _money(values[-1], currency)})
    else:
        parts.append(f"Spending anomaly detection needs at least 3 days of {currency} data.")

    top = conn.execute(
        "SELECT * FROM resources WHERE currency=? ORDER BY cpu_pct DESC LIMIT 1", (currency,)
    ).fetchone()
    if top:
        capacity = detect_capacity_exhaustion(top["cpu_pct"], top["resource_id"], currency)
        parts.append(
            f"Highest CPU resource {top['resource_id']} is at {float(top['cpu_pct']):.1f}% "
            f"- capacity risk {'detected' if capacity.detected else 'not detected'}."
        )
        facts.append({"label": "Highest CPU", "value": f"{top['resource_id']} ({float(top['cpu_pct']):.1f}%)"})

    if not facts:
        return _result(
            f"Not enough data in {currency} to run anomaly detection.",
            "anomalies",
            currency,
            [],
            _sources("billing table", "resources table"),
            "low",
        )
    return _result(
        " ".join(parts),
        "anomalies",
        currency,
        facts,
        _sources("layer 3 detectors", "billing table", "resources table"),
        "medium",
    )


def _answer_currencies(conn: sqlite3.Connection, currency: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT currency, COUNT(*) AS rows FROM billing GROUP BY currency ORDER BY currency"
    ).fetchall()
    counted = {r["currency"]: r["rows"] for r in rows}
    totals = []
    for code in ALLOWED_CURRENCIES:
        if code in counted:
            total, row_count, _, _ = _total(conn, code)
            totals.append(f"{code}: {_money(total, code)} over {row_count} rows")
        else:
            totals.append(f"{code}: no rows")
    answer = (
        "USD, EUR, and INR are supported and kept separate. "
        + "; ".join(totals)
        + ". There is no FX conversion and no combined total by design."
    )
    facts = [{"label": code, "value": ("loaded" if code in counted else "no rows")} for code in ALLOWED_CURRENCIES]
    return _result(
        answer, "currencies", currency, facts, _sources("billing table"), "high"
    )


def _answer_help(currency: str) -> Dict[str, Any]:
    answer = (
        "I answer questions about the data stored in this app: spend totals, top services, "
        "month-over-month change, findings, forecasts, resource details, policy verdicts, "
        "anomalies, data freshness, and how to import your own CSV. "
        "I only use local queries - I will tell you when the data cannot answer a question."
    )
    facts = [
        {"label": "Scope", "value": "This app's local database"},
        {"label": "Currency", "value": currency},
        {"label": "Sources", "value": "billing, resources, findings, policy, layers 1-6"},
    ]
    return _result(answer, "help", currency, facts, _sources("local dataset metadata"), "high")


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def answer_question(conn: sqlite3.Connection, question: str, currency: str = "USD") -> Dict[str, Any]:
    text = (question or "").strip()
    if not text:
        return _result(
            "Ask me about spend, services, findings, resources, policy, anomalies, or importing data.",
            "empty",
            currency,
            [],
            [],
            "high",
        )

    lower = text.lower()
    active = _detect_currency(text, currency)
    matches = _find_resources(conn, text)

    if re.search(r"\b(help|what can you do|how do you work|capabilit)", lower):
        return _answer_help(active)
    if re.search(r"\b(import|upload|csv|my own data|add data|load data)\b", lower):
        return _answer_import(conn, active)
    if re.search(r"\b(stale|fresh|last import|data quality|data range|how many rows|dataset)\b", lower):
        return _answer_dataset(conn, active)
    if re.search(r"\b(currency|currencies|fx|exchange rate)\b", lower):
        return _answer_currencies(conn, active)
    if re.search(r"\b(allowed|policy|permission|can i (stop|delete|resize|terminate)|is it safe to)\b", lower):
        return _answer_policy(text, active, matches)
    if matches and not re.search(r"\b(top|biggest|total|forecast|anomal)\b", lower):
        return _answer_resource(conn, text, active, matches)
    if re.search(r"\b(anomal|unusual|spike|outlier)\b", lower):
        return _answer_anomalies(conn, active)
    if re.search(r"\b(finding|savings|waste|idle|rightsiz|opportunit)\b", lower):
        return _answer_findings(conn, active)
    if re.search(r"\b(forecast|projection|predict|next (week|month|14 days))\b", lower):
        return _answer_forecast(conn, active)
    if re.search(r"\b(trend|compare|comparison|last month|increase|decrease|change)\b", lower):
        return _answer_trend(conn, active)
    if re.search(r"\b(top|biggest|largest|most expensive|breakdown|which service)\b", lower):
        return _answer_top_services(conn, active)
    if re.search(r"\b(spend|spent|cost|bill|how much|total)\b", lower):
        return _answer_total(conn, active)

    result = _result(
        "I cannot answer that from the data stored in this app. I only report what I can "
        "compute from billing, resources, findings, and policy rules - I will not guess. "
        "Try one of the suggested questions, or ask about a specific resource_id.",
        "unsupported",
        active,
        [{"label": "Question", "value": text[:200]}],
        [],
        "low",
    )
    return result
