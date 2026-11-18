"""Server-side exports: sanitized CSV and a Markdown optimization report.

Exports are generated from stored records only. Text cells are neutralised
against CSV formula injection (guide threat T1) and every currency stays in its
own column/section; no FX conversion is applied.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models import (
    AdvisorReport,
    AnalysisRun,
    Finding,
    ForecastPoint,
    ForecastRun,
    ImportRecord,
    SavingsScenario,
)
from app.services.analytics import CostScope, summarize
from app.services.decisions import latest_for
from app.services.forecasting import series_from_run

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _text(value: Any) -> str:
    """Neutralise spreadsheet formulas and collapse line breaks."""

    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _markdown(value: Any) -> str:
    return _text(value).replace("|", "\\|")


def _decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def findings_csv(db: Session, run_id: int | None) -> tuple[str, str]:
    run, findings = _findings_for(db, run_id)
    scenarios = _scenarios_for(db, [item.id for item in findings])
    decisions = latest_for(db, [item.id for item in findings])

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "finding_id",
            "run_id",
            "finding_type",
            "resource_id",
            "service",
            "region",
            "environment",
            "project",
            "currency",
            "current_sku",
            "recommended_sku",
            "baseline_monthly_cost",
            "proposed_monthly_cost",
            "estimated_monthly_savings",
            "savings_pct",
            "confidence",
            "risk",
            "observation_days",
            "sample_count",
            "cost_window_start",
            "cost_window_end",
            "uses_synthetic_prices",
            "latest_decision",
            "decision_actor",
            "decision_note",
            "decision_at",
            "assumptions",
            "warnings",
        ]
    )
    for item in findings:
        scenario = scenarios.get(item.id)
        decision = decisions.get(item.id)
        assumptions = item.assumptions or (scenario.assumptions if scenario else [])
        writer.writerow(
            [
                f"finding-{item.id}",
                item.run_id,
                item.finding_type.value,
                _text(item.resource_id),
                _text(item.service),
                _text(item.region),
                _text(item.environment),
                _text(item.project),
                item.currency,
                _text(item.current_sku),
                _text(item.recommended_sku),
                _decimal(item.baseline_monthly_cost),
                _decimal(item.proposed_monthly_cost),
                _decimal(item.estimated_monthly_savings),
                _decimal(item.savings_pct),
                item.confidence.value,
                item.risk.value,
                item.observation_days,
                item.sample_count,
                item.cost_window_start.isoformat(),
                item.cost_window_end.isoformat(),
                "true" if item.uses_synthetic_prices else "false",
                decision.decision.value if decision else "",
                _text(decision.actor) if decision else "",
                _text(decision.note) if decision else "",
                decision.created_at.isoformat() if decision else "",
                _text("; ".join(assumptions)),
                _text("; ".join(item.warnings)),
            ]
        )
    name = f"cloudpilot-findings-run{run.id}-{_stamp()}.csv" if run else f"cloudpilot-findings-{_stamp()}.csv"
    return name, buffer.getvalue()


def summary_markdown(
    db: Session,
    *,
    run_id: int | None,
    forecast_run_id: int | None,
) -> tuple[str, str]:
    run, findings = _findings_for(db, run_id)
    decisions = latest_for(db, [item.id for item in findings])
    totals = summarize(db, CostScope())
    imports = list(db.scalars(select(ImportRecord).order_by(ImportRecord.id)))
    forecast = _forecast(db, forecast_run_id)
    report = db.scalar(select(AdvisorReport).order_by(AdvisorReport.id.desc()).limit(1))

    lines: list[str] = []
    lines.append("# CloudPilot AI - cost optimization report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).isoformat(timespec='seconds')}")
    if totals.window.start and totals.window.end:
        lines.append(
            f"Billing window: {totals.window.start.isoformat()} to "
            f"{totals.window.end.isoformat()} ({totals.window.days} days)"
        )
    lines.append(
        "Data policy: amounts are exact decimals, currencies are never combined, "
        "and **no cloud action is performed**."
    )
    lines.append(
        "Synthetic data: "
        + ("**yes - illustrative sample data and/or demo prices**"
           if totals.contains_sample_data or (run and run.uses_synthetic_prices)
           else "no synthetic sample import detected")
    )
    lines.append("")

    lines.append("## Spend by currency")
    lines.append("")
    if totals.totals:
        lines.append("| Currency | Total | Rows |")
        lines.append("|---|---:|---:|")
        for item in totals.totals:
            lines.append(
                f"| {item.currency} | {_decimal(item.amount)} | {item.row_count} |"
            )
    else:
        lines.append("_No billing rows._")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if run is None or not findings:
        lines.append("_No analysis run or no findings._")
    else:
        lines.append(
            f"Analysis run {run.id}, created {run.created_at.isoformat()}, "
            f"{len(findings)} finding(s)."
        )
        lines.append("")
        lines.append("| Finding | Resource | Type | Currency | Monthly savings | Risk | Decision |")
        lines.append("|---|---|---|---|---:|---|---|")
        for item in findings:
            decision = decisions.get(item.id)
            lines.append(
                "| {fid} | {resource} | {kind} | {currency} | {saving} | {risk} | {decision} |".format(
                    fid=f"finding-{item.id}",
                    resource=_markdown(item.resource_id),
                    kind=item.finding_type.value,
                    currency=item.currency,
                    saving=_decimal(item.estimated_monthly_savings),
                    risk=item.risk.value,
                    decision=decision.decision.value if decision else "pending",
                )
            )
        for item in findings:
            decision = decisions.get(item.id)
            lines.append("")
            lines.append(f"### finding-{item.id} - {_markdown(item.resource_id)}")
            lines.append("")
            lines.append(
                f"- Type: `{item.finding_type.value}`; service {_markdown(item.service)}; "
                f"environment {_markdown(item.environment)}; project {_markdown(item.project)}"
            )
            lines.append(
                f"- Baseline {_decimal(item.baseline_monthly_cost)} {item.currency}; "
                f"proposed {_decimal(item.proposed_monthly_cost)}; "
                f"estimated monthly savings **{_decimal(item.estimated_monthly_savings)}** "
                f"({_decimal(item.savings_pct)}%)"
            )
            lines.append(
                f"- Confidence {item.confidence.value}; risk {item.risk.value}; "
                f"observation {item.observation_days} day(s), {item.sample_count} sample(s)"
            )
            if item.current_sku or item.recommended_sku:
                lines.append(
                    f"- SKU: {_markdown(item.current_sku or 'unknown')} -> "
                    f"{_markdown(item.recommended_sku or 'n/a')}"
                )
            if item.price_source:
                lines.append(
                    f"- Price source: {_markdown(item.price_source.get('source_name', 'unknown'))}"
                    f" (synthetic={item.uses_synthetic_prices})"
                )
            if item.assumptions:
                lines.append("- Assumptions:")
                lines.extend(f"  - {_markdown(text)}" for text in item.assumptions)
            if item.warnings:
                lines.append("- Warnings:")
                lines.extend(f"  - {_markdown(text)}" for text in item.warnings)
            lines.append(
                "- Latest human decision: "
                + (
                    f"{decision.decision.value} by {_markdown(decision.actor)} "
                    f"at {decision.created_at.isoformat()}"
                    + (f" - {_markdown(decision.note)}" if decision.note else "")
                    if decision
                    else "pending review"
                )
            )
    lines.append("")

    lines.append("## Forecast")
    lines.append("")
    if forecast is None:
        lines.append("_No forecast run stored._")
    else:
        points = list(
            db.scalars(
                select(ForecastPoint)
                .where(ForecastPoint.run_id == forecast.id)
                .order_by(ForecastPoint.currency, ForecastPoint.period)
            )
        )
        series = series_from_run(db, forecast, points)
        lines.append(
            f"Run {forecast.id}: `{forecast.method.value}` over "
            f"{forecast.history_start} to {forecast.history_end}; "
            f"horizon {forecast.horizon_start} to {forecast.horizon_end}."
        )
        lines.append("")
        lines.append("| Currency | Projected total | Lower | Upper | Interval quantile |")
        lines.append("|---|---:|---:|---:|---:|")
        for item in series:
            lines.append(
                f"| {item.currency} | {_decimal(item.projected_total)} | "
                f"{_decimal(item.projected_lower)} | {_decimal(item.projected_upper)} | "
                f"{_decimal(item.evaluation.interval_quantile)} |"
            )
        lines.append("")
        lines.append(
            "Error metrics are held-out estimates, not guarantees. See the API response "
            "or the Forecasts page for MAE, RMSE, bias, MAPE and warnings."
        )
    lines.append("")

    lines.append("## AI advisor")
    lines.append("")
    if report is None:
        lines.append("_No advisor report stored._")
    else:
        lines.append(
            f"Report {report.id}: status `{report.status}`, mode `{report.mode}`, "
            f"AI used: {str(report.ai_used).lower()}"
            + (f", fallback reason `{report.fallback_reason}`" if report.fallback_reason else "")
        )
        output = report.output if isinstance(report.output, dict) else {}
        summary_text = output.get("executive_summary")
        if summary_text:
            lines.append("")
            lines.append(_markdown(summary_text))
    lines.append("")

    lines.append("## Data lineage")
    lines.append("")
    if imports:
        lines.append("| Import | Kind | File | Status | Rows | Accepted | SHA-256 |")
        lines.append("|---|---|---|---|---:|---:|---|")
        for item in imports:
            lines.append(
                f"| {item.id} | {item.kind.value} | {_markdown(item.filename)} | "
                f"{item.status.value} | {item.row_count} | {item.accepted_row_count} | "
                f"`{item.content_sha256[:16]}...` |"
            )
    else:
        lines.append("_No imports._")
    lines.append("")

    lines.append("## Review notes")
    lines.append("")
    lines.append(
        "- Findings are candidates for human review, not instructions. No resource is "
        "stopped, resized or deleted by CloudPilot AI."
    )
    lines.append(
        "- Every savings estimate is reproducible from stored billing, utilization and "
        "sourced price records; see `GET /api/findings/{id}`."
    )
    lines.append(
        "- If synthetic prices are present, the savings are illustrative and must not be "
        "presented as vendor quotes."
    )
    lines.append("")
    return f"cloudpilot-report-{_stamp()}.md", "\n".join(lines)


def _findings_for(
    db: Session, run_id: int | None
) -> tuple[AnalysisRun | None, list[Finding]]:
    if run_id is not None:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            raise NotFoundError(f"Analysis run {run_id} was not found.")
    else:
        run = db.scalar(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1))
    if run is None:
        return None, []
    findings = list(
        db.scalars(
            select(Finding)
            .where(Finding.run_id == run.id)
            .order_by(Finding.estimated_monthly_savings.desc(), Finding.id)
        )
    )
    return run, findings


def _scenarios_for(db: Session, finding_ids: list[int]) -> dict[int, SavingsScenario]:
    if not finding_ids:
        return {}
    rows = db.scalars(
        select(SavingsScenario).where(SavingsScenario.finding_id.in_(finding_ids))
    )
    return {row.finding_id: row for row in rows}


def _forecast(db: Session, run_id: int | None) -> ForecastRun | None:
    if run_id is not None:
        run = db.get(ForecastRun, run_id)
        if run is None:
            raise NotFoundError(f"Forecast run {run_id} was not found.")
        return run
    return db.scalar(select(ForecastRun).order_by(ForecastRun.id.desc()).limit(1))


__all__ = ["findings_csv", "summary_markdown"]
