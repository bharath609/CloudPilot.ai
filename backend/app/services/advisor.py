"""Evidence-bound advisor: bounded package, validation and safe fallback.

The advisor may only explain deterministic findings and forecasts. It cannot
change stored totals. Only a bounded, redacted package is sent to an optional
OpenAI-compatible provider; the default path is fully local and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import RiskLevel
from app.core.errors import AppError, NotFoundError
from app.core.time import utcnow
from app.db.models import AdvisorReport, AnalysisRun, Finding, ForecastRun
from app.llm.client import LLMError, OpenAICompatibleClient, create_client
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas.advisor import (
    AdvisorFindingOut,
    AdvisorOutputOut,
    ReportGenerateRequest,
)

MAX_TEXT = 160
MAX_NOTE = 240
REDACTED = "[redacted untrusted text]"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_LONG_DIGITS = re.compile(r"\b\d{12,}\b")
_INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instruction|prompt|rule|system)\b"
    r"|system\s*prompt|you\s+are\s+(an?\s+)?(ai|assistant|model)"
    r"|act\s+as|jailbreak|reveal\s+.{0,20}(secret|key|prompt)"
    r"|api\s*key|\bexecute\b|\btool\s*call\b",
    re.IGNORECASE | re.DOTALL,
)
_MAGNITUDE = re.compile(r"\b(million|billion|thousand)s?\b", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![\w.])(?:[$€£₹]\s*)?(?:USD|EUR|GBP|INR|CAD|AUD)?\s*-?\d[\d,]*(?:\.\d+)?\s*%?",
    re.IGNORECASE,
)
_CURRENCY_PREFIX = re.compile(r"^(USD|EUR|GBP|INR|CAD|AUD)\s*", re.IGNORECASE)
_CURRENCY_SYMBOLS = ("$", "€", "£", "₹")
_METRIC_KEYS = ("cpu_avg_pct", "cpu_p95_max_pct", "memory_avg_pct", "memory_p95_max_pct")


@dataclass(slots=True)
class ReportOutcome:
    report: AdvisorReport
    output: AdvisorOutputOut


@dataclass(slots=True)
class _Redactor:
    redacted_fields: int = 0
    instruction_like_fields: int = 0

    def text(self, value: Any, *, limit: int = MAX_TEXT) -> str | None:
        if value is None:
            return None
        cleaned = _CONTROL.sub(" ", str(value)).replace("\r", " ").replace("\n", " ")
        if _INSTRUCTION.search(cleaned):
            self.instruction_like_fields += 1
            return REDACTED
        if _EMAIL.search(cleaned) or _LONG_DIGITS.search(cleaned):
            self.redacted_fields += 1
            cleaned = _EMAIL.sub("[email]", cleaned)
            cleaned = _LONG_DIGITS.sub(lambda match: "****" + match.group()[-4:], cleaned)
        cleaned = " ".join(cleaned.split())
        if len(cleaned) > limit:
            cleaned = cleaned[: limit - 3].rstrip() + "..."
        return cleaned or None

    def texts(self, values: Any, *, limit: int = 6, max_len: int = MAX_NOTE) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        items: list[str] = []
        for value in values[:limit]:
            text = self.text(value, limit=max_len)
            if text:
                items.append(text)
        return items

    def mapping(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 2:
            return None
        if isinstance(value, dict):
            return {
                str(key)[:64]: self.mapping(item, depth=depth + 1)
                for key, item in list(value.items())[:40]
            }
        if isinstance(value, (list, tuple)):
            return [self.mapping(item, depth=depth + 1) for item in value[:20]]
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        return self.text(value, limit=MAX_NOTE)


def generate_report(
    db: Session,
    settings: Settings,
    request: ReportGenerateRequest,
    *,
    client: OpenAICompatibleClient | None = None,
) -> ReportOutcome:
    """Build evidence, optionally call the provider, validate, and persist."""
    started = time.perf_counter()
    analysis_run = _resolve_analysis_run(db, request.analysis_run_id)
    forecast_run = (
        _resolve_forecast_run(db, request.forecast_run_id)
        if request.include_forecast
        else None
    )
    if analysis_run is None and forecast_run is None:
        raise AppError(
            "No analysis or forecast data exists yet. Run /api/analysis/run or "
            "/api/forecasts/run first.",
            code="no_report_data",
            status_code=409,
        )

    findings = _findings_for(db, analysis_run) if analysis_run is not None else []
    redactor = _Redactor()
    package, omitted, fits = _build_package(
        analysis_run,
        findings,
        forecast_run,
        settings,
        redactor,
    )
    package_json = _serialize(package)
    evidence_sha256 = hashlib.sha256(package_json.encode("utf-8")).hexdigest()

    candidate: AdvisorOutputOut | None = None
    llm_response = None
    validation_errors: list[str] = []
    fallback_reason: str | None = None
    attempted = False

    if not fits:
        fallback_reason = "evidence_package_too_large"
        validation_errors = ["The bounded evidence package exceeded the configured limit."]
    elif client is None and not settings.llm_enabled:
        fallback_reason = "disabled"
    elif client is None and not _api_key(settings):
        fallback_reason = "missing_api_key"
        validation_errors = ["CLOUDPILOT_LLM_ENABLED is true but no API key is configured."]
    else:
        attempted = True
        active = client or create_client(settings)
        try:
            llm_response = active.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(
                    package, max_priority_findings=settings.llm_max_priority_findings
                ),
            )
            raw = _parse_json_object(llm_response.content)
            candidate = AdvisorOutputOut.model_validate(raw)
            validation_errors = _validate_candidate(candidate, package)
            if validation_errors:
                fallback_reason = _reason_from_errors(validation_errors)
                candidate = None
        except LLMError as exc:
            fallback_reason = exc.code
            validation_errors = [exc.message]
        except ValidationError as exc:
            fallback_reason = "schema_invalid"
            validation_errors = _schema_errors(exc)
        except (ValueError, TypeError) as exc:
            fallback_reason = "invalid_json"
            validation_errors = [str(exc)[:MAX_NOTE]]
        except Exception:  # noqa: BLE001 - provider failures must never break the API
            fallback_reason = "provider_error"
            validation_errors = ["The LLM provider failed unexpectedly."]

    fallback = _fallback_output(package, settings)
    output = candidate or fallback
    ai_used = candidate is not None
    synthetic = _contains_synthetic(package)

    notes = [
        (
            "AI explanation accepted after schema, evidence-ID and numeric-claim validation."
            if ai_used
            else "Deterministic explanation generated locally; no AI output was used."
        ),
        "Deterministic totals, assumptions and savings are unchanged by this report.",
        (
            "A bounded, redacted evidence package was eligible to be sent to the configured provider."
            if attempted
            else "No data left this machine for this report."
        ),
    ]
    if redactor.redacted_fields or redactor.instruction_like_fields:
        notes.append(
            f"Evidence redaction masked {redactor.redacted_fields} field(s) and replaced "
            f"{redactor.instruction_like_fields} instruction-like field(s)."
        )

    warnings = ["Human review is required before any cloud change."]
    if synthetic:
        warnings.append(
            "Evidence includes synthetic sample data or demo prices; this report is illustrative."
        )
    if omitted:
        warnings.append(
            f"{omitted} lower-priority finding(s) were omitted to keep the evidence package bounded."
        )
    if not ai_used and fallback_reason not in {"disabled", None}:
        warnings.append(
            "AI output was unavailable or rejected; the deterministic explanation was used instead."
        )

    provider = settings.llm_provider if attempted else None
    model = llm_response.model if llm_response is not None else (settings.llm_model if attempted else None)
    report = AdvisorReport(
        status="completed" if ai_used else "fallback",
        mode="llm" if ai_used else "deterministic",
        ai_used=ai_used,
        provider=provider,
        model=model,
        analysis_run_id=analysis_run.id if analysis_run is not None else None,
        forecast_run_id=forecast_run.id if forecast_run is not None else None,
        fallback_reason=fallback_reason,
        validation_errors=validation_errors[:20],
        evidence_sha256=evidence_sha256,
        evidence=package,
        output=output.model_dump(mode="json"),
        notes=notes,
        warnings=warnings,
        attempts=llm_response.attempts if llm_response is not None else 0,
        latency_ms=llm_response.latency_ms if llm_response is not None else 0,
        duration_ms=int((time.perf_counter() - started) * 1000),
        completed_at=utcnow(),
    )
    db.add(report)
    db.flush()
    return ReportOutcome(report=report, output=output)


# -- resolving ------------------------------------------------------------
def _resolve_analysis_run(db: Session, run_id: int | None) -> AnalysisRun | None:
    if run_id is not None:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            raise NotFoundError(f"Analysis run {run_id} was not found.")
        return run
    return db.scalar(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1))


def _resolve_forecast_run(db: Session, run_id: int | None) -> ForecastRun | None:
    if run_id is not None:
        run = db.get(ForecastRun, run_id)
        if run is None:
            raise NotFoundError(f"Forecast run {run_id} was not found.")
        return run
    return db.scalar(select(ForecastRun).order_by(ForecastRun.id.desc()).limit(1))


def _findings_for(db: Session, run: AnalysisRun) -> list[Finding]:
    return list(
        db.scalars(
            select(Finding)
            .where(Finding.run_id == run.id)
            .order_by(Finding.estimated_monthly_savings.desc(), Finding.id)
        )
    )


# -- evidence package -----------------------------------------------------
def _build_package(
    analysis_run: AnalysisRun | None,
    findings: list[Finding],
    forecast_run: ForecastRun | None,
    settings: Settings,
    redactor: _Redactor,
) -> tuple[dict[str, Any], int, bool]:
    package: dict[str, Any] = {
        "data_policy": {
            "deterministic_evidence_only": True,
            "currencies_never_combined": True,
            "untrusted_text_neutralized": True,
        },
    }
    omitted = 0
    if analysis_run is not None:
        included = findings[: settings.llm_max_package_findings]
        omitted = max(len(findings) - len(included), 0)
        analysis = {
            "run_id": analysis_run.id,
            "reference_date": _iso(analysis_run.reference_date),
            "cost_window": {
                "start": _iso(analysis_run.cost_window_start),
                "end": _iso(analysis_run.cost_window_end),
                "days": _span_days(
                    analysis_run.cost_window_start, analysis_run.cost_window_end
                ),
            },
            "currency": analysis_run.currency,
            "finding_count": max(analysis_run.finding_count, len(findings)),
            "findings_included": len(included),
            "findings_omitted": omitted,
            "total_savings_by_currency": {
                str(code): str(amount)
                for code, amount in sorted(analysis_run.total_savings_by_currency.items())
            },
            "uses_synthetic_prices": analysis_run.uses_synthetic_prices,
            "rule_config": redactor.mapping(analysis_run.rule_config),
            "notes": redactor.texts(analysis_run.notes, limit=6),
            "findings": [
                _finding_payload(finding, redactor) for finding in included
            ],
        }
        package["analysis"] = analysis

    if forecast_run is not None:
        package["forecast"] = _forecast_payload(forecast_run, redactor)

    package["data_policy"]["contains_synthetic_data"] = _contains_synthetic(package)
    package["data_policy"]["redacted_fields"] = redactor.redacted_fields
    package["data_policy"]["instruction_like_fields"] = redactor.instruction_like_fields

    fits = _bound_package(package, settings.llm_max_evidence_chars)
    if analysis_run is not None:
        bounded = package.get("analysis")
        if isinstance(bounded, dict):
            omitted = int(bounded.get("findings_omitted", omitted))
    return package, omitted, fits


def _finding_payload(finding: Finding, redactor: _Redactor) -> dict[str, Any]:
    evidence = finding.evidence if isinstance(finding.evidence, dict) else {}
    cost_ids = _int_ids(evidence.get("cost_record_ids"))
    metric_ids = _int_ids(evidence.get("metric_ids"))
    price_ids = _int_ids(evidence.get("price_entry_ids"))
    import_ids = _int_ids(evidence.get("import_ids"))
    evidence_ids = (
        [f"cost-{item}" for item in cost_ids[:25]]
        + [f"metric-{item}" for item in metric_ids[:25]]
        + [f"price-{item}" for item in price_ids[:10]]
        + [f"import-{item}" for item in import_ids[:10]]
    )[:40]
    metrics = {
        key: str(finding.metrics[key])
        for key in _METRIC_KEYS
        if isinstance(finding.metrics, dict) and key in finding.metrics
    }
    return {
        "finding_id": f"finding-{finding.id}",
        "finding_type": finding.finding_type.value,
        "provider": redactor.text(finding.provider, limit=32),
        "account": redactor.text(finding.account_id, limit=64),
        "service": redactor.text(finding.service, limit=80),
        "resource_id": redactor.text(finding.resource_id, limit=120),
        "region": redactor.text(finding.region, limit=64),
        "environment": redactor.text(finding.environment, limit=32),
        "project": redactor.text(finding.project, limit=120),
        "currency": finding.currency,
        "current_sku": redactor.text(finding.current_sku, limit=120),
        "recommended_sku": redactor.text(finding.recommended_sku, limit=120),
        "baseline_monthly_cost": str(finding.baseline_monthly_cost),
        "proposed_monthly_cost": str(finding.proposed_monthly_cost),
        "estimated_monthly_savings": str(finding.estimated_monthly_savings),
        "savings_pct": str(finding.savings_pct),
        "confidence": finding.confidence.value,
        "risk": finding.risk.value,
        "cost_window": {
            "start": _iso(finding.cost_window_start),
            "end": _iso(finding.cost_window_end),
            "days": _span_days(finding.cost_window_start, finding.cost_window_end),
        },
        "observation": {
            "start": _iso(finding.observation_start),
            "end": _iso(finding.observation_end),
            "days": finding.observation_days,
            "sample_count": finding.sample_count,
        },
        "metrics": metrics,
        "evidence_ids": evidence_ids,
        "evidence_counts": {
            "cost_records": evidence.get("cost_record_id_count", len(cost_ids)),
            "metrics": evidence.get("metric_id_count", len(metric_ids)),
            "prices": len(price_ids),
            "imports": len(import_ids),
        },
        "assumptions": redactor.texts(finding.assumptions, limit=6),
        "warnings": redactor.texts(finding.warnings, limit=6),
        "price_source": redactor.mapping(finding.price_source),
        "uses_synthetic_prices": finding.uses_synthetic_prices,
    }


def _forecast_payload(run: ForecastRun, redactor: _Redactor) -> dict[str, Any]:
    series: dict[str, Any] = {}
    for code, payload in sorted(run.evaluation.items()):
        if not isinstance(payload, dict):
            continue
        evaluation = payload.get("evaluation")
        series[str(code)] = {
            "history_days": payload.get("history_days"),
            "projected_total": payload.get("projected_total"),
            "projected_lower": payload.get("projected_lower"),
            "projected_upper": payload.get("projected_upper"),
            "evaluation": _forecast_evaluation(evaluation),
            "notes": redactor.texts(payload.get("notes"), limit=4),
        }
    return {
        "run_id": run.id,
        "method": run.method.value,
        "granularity": run.granularity.value,
        "reference_date": _iso(run.reference_date),
        "history": {"start": _iso(run.history_start), "end": _iso(run.history_end)},
        "horizon": {
            "start": _iso(run.horizon_start),
            "end": _iso(run.horizon_end),
            "days": _span_days(run.horizon_start, run.horizon_end),
        },
        "currency": run.currency,
        "series": series,
        "notes": redactor.texts(run.notes, limit=6),
        "warnings": redactor.texts(run.warnings, limit=6),
        "contains_sample_data": bool(run.stats.get("contains_sample_data")),
    }


def _forecast_evaluation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "method",
        "history_days",
        "train_days",
        "holdout_days",
        "mae",
        "rmse",
        "bias",
        "mape_pct",
        "mape_excluded_points",
        "interval_quantile",
        "interval_width",
        "confidence",
    )
    return {key: value[key] for key in keys if key in value}


def _bound_package(package: dict[str, Any], limit: int) -> bool:
    """Shrink the package until it fits the outbound character budget."""
    analysis = package.get("analysis")
    forecast = package.get("forecast")
    while _size(package) > limit and isinstance(analysis, dict) and analysis.get("findings"):
        removed = analysis["findings"].pop()
        analysis["findings_omitted"] = int(analysis.get("findings_omitted", 0)) + 1
        analysis["findings_included"] = len(analysis["findings"])
        if removed is None:  # pragma: no cover - defensive
            break
    if _size(package) > limit and isinstance(analysis, dict):
        analysis.pop("rule_config", None)
        analysis["notes"] = analysis.get("notes", [])[:2]
    if _size(package) > limit and isinstance(forecast, dict):
        forecast["notes"] = []
        forecast["warnings"] = []
    if _size(package) > limit and isinstance(analysis, dict):
        removed_count = len(analysis.get("findings", []))
        analysis["findings"] = []
        analysis["findings_included"] = 0
        analysis["findings_omitted"] = int(analysis.get("findings_omitted", 0)) + removed_count
    return _size(package) <= limit


# -- validation -----------------------------------------------------------
def _validate_candidate(output: AdvisorOutputOut, package: dict[str, Any]) -> list[str]:
    analysis = package.get("analysis") if isinstance(package.get("analysis"), dict) else {}
    packaged_findings = analysis.get("findings", []) if isinstance(analysis, dict) else []
    allowed_findings = {
        item.get("finding_id") for item in packaged_findings if isinstance(item, dict)
    }
    allowed_evidence: set[str] = set()
    for item in packaged_findings:
        if isinstance(item, dict):
            allowed_evidence.update(str(value) for value in item.get("evidence_ids", []))
    allowed_evidence.update(str(value) for value in allowed_findings if value)
    forecast = package.get("forecast")
    if isinstance(forecast, dict) and forecast.get("run_id") is not None:
        allowed_evidence.add(f"forecast-{forecast['run_id']}")

    errors: list[str] = []
    if packaged_findings and not output.priority_findings:
        errors.append("At least one priority finding is required when evidence contains findings.")
    seen: set[str] = set()
    for item in output.priority_findings:
        if item.finding_id not in allowed_findings:
            errors.append(f"Unknown finding ID: {item.finding_id}")
        if item.finding_id in seen:
            errors.append(f"Duplicate finding ID: {item.finding_id}")
        seen.add(item.finding_id)
        for evidence_id in item.evidence_ids:
            if evidence_id not in allowed_evidence:
                errors.append(f"Unknown evidence ID: {evidence_id}")
                break
    texts = [output.executive_summary]
    for item in output.priority_findings:
        texts.extend([item.explanation, item.recommended_next_step, *item.assumptions])
    texts.extend(output.unknowns)
    allowed_numbers = _allowed_numbers(package)
    for text in texts:
        error = _validate_numbers(text, allowed_numbers)
        if error:
            errors.append(error)
            break
    return errors


def _validate_numbers(text: str, allowed: set[str]) -> str | None:
    if _MAGNITUDE.search(text):
        return "Unsupported magnitude claim (million/billion/thousand)."
    for match in _NUMBER.finditer(text):
        token = match.group().strip()
        decimal = _decimal_from_token(token)
        if decimal is None:
            continue
        normalized = _number_forms(decimal)
        marked = (
            any(symbol in token for symbol in _CURRENCY_SYMBOLS)
            or "%" in token
            or bool(_CURRENCY_PREFIX.match(token))
            or "." in token
        )
        if (marked or abs(decimal) > 31) and not (normalized & allowed):
            return f"Unsupported numeric claim: {token}"
    return None


def _allowed_numbers(value: Any, found: set[str] | None = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, dict):
        for item in value.values():
            _allowed_numbers(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _allowed_numbers(item, found)
    elif isinstance(value, bool) or value is None:
        return found
    elif isinstance(value, (int, float, Decimal)):
        found.update(_number_forms(Decimal(str(value))))
    elif isinstance(value, str):
        for match in re.findall(r"-?\d[\d,]*(?:\.\d+)?", value):
            try:
                found.update(_number_forms(Decimal(match.replace(",", ""))))
            except InvalidOperation:
                continue
    return found


def _number_forms(value: Decimal) -> set[str]:
    forms = {format(value.normalize(), "f"), str(value)}
    if value == value.to_integral_value():
        forms.add(str(int(value)))
    if value != 0 and abs(value) < 1:
        percent = (value * 100).normalize()
        forms.add(format(percent, "f"))
    return forms


def _decimal_from_token(token: str) -> Decimal | None:
    cleaned = token.strip()
    for symbol in _CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(symbol, "")
    cleaned = _CURRENCY_PREFIX.sub("", cleaned).replace("%", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _reason_from_errors(errors: list[str]) -> str:
    joined = " ".join(errors)
    if "Unknown finding ID" in joined:
        return "unknown_finding_id"
    if "Unknown evidence ID" in joined:
        return "unknown_evidence_id"
    if "Unsupported numeric" in joined or "magnitude" in joined:
        return "unsupported_numeric_claim"
    if "At least one priority" in joined:
        return "missing_priority_finding"
    return "validation_failed"


def _schema_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for item in exc.errors()[:10]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "output"
        message = str(item.get("msg", "invalid value"))
        errors.append(f"{location}: {message}"[:MAX_NOTE])
    return errors or ["The AI output did not match the required schema."]


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("The AI response was not a JSON object.") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            raise ValueError("The AI response was not valid JSON.") from None
    if not isinstance(value, dict):
        raise ValueError("The AI response was not a JSON object.")
    return value


# -- deterministic fallback ----------------------------------------------
def _fallback_output(package: dict[str, Any], settings: Settings) -> AdvisorOutputOut:
    analysis: dict[str, Any] = (
        package["analysis"] if isinstance(package.get("analysis"), dict) else {}
    )
    findings = analysis.get("findings", []) if isinstance(analysis, dict) else []
    forecast: dict[str, Any] = (
        package["forecast"] if isinstance(package.get("forecast"), dict) else {}
    )
    synthetic = _contains_synthetic(package)

    summary = _fallback_summary(analysis, forecast)
    priority: list[AdvisorFindingOut] = []
    for item in findings[: settings.llm_max_priority_findings]:
        priority.append(_fallback_finding(item))

    unknowns: list[str] = []
    total = int(analysis.get("finding_count", len(findings))) if analysis else 0
    if analysis and total > len(findings):
        unknowns.append(
            f"Only {len(findings)} of {total} findings were included to bound the report."
        )
    if not findings:
        unknowns.append("No resource-level waste findings are stored for this analysis run.")
    if any(item.get("confidence") == "low" for item in findings):
        unknowns.append("At least one finding has low confidence and needs closer review.")
    if not forecast:
        unknowns.append("No forecast run was included in this report.")
    if synthetic:
        unknowns.append("The evidence includes synthetic sample data or demo prices.")
    unknowns.append(
        "Resource owner intent, workload schedules and dependencies are not known; "
        "human review is required."
    )
    unknowns.append("No cloud action was taken and none should be taken automatically.")

    return AdvisorOutputOut(
        executive_summary=summary,
        priority_findings=priority,
        unknowns=_unique(unknowns),
        human_review_required=True,
    )


def _fallback_summary(analysis: dict[str, Any], forecast: dict[str, Any]) -> str:
    parts: list[str] = []
    if analysis:
        total = analysis.get("total_savings_by_currency") or {}
        totals = "; ".join(f"{code} {amount}" for code, amount in total.items())
        window = analysis.get("cost_window") or {}
        parts.append(
            f"Analysis run {analysis.get('run_id')} contains "
            f"{analysis.get('finding_count', 0)} finding(s) covering "
            f"{window.get('start')} to {window.get('end')}."
        )
        if totals:
            parts.append(f"Estimated monthly savings are {totals}.")
        else:
            parts.append("No estimated monthly savings are stored for this run.")
    if forecast:
        for code, series in (forecast.get("series") or {}).items():
            horizon = forecast.get("horizon") or {}
            parts.append(
                f"The {forecast.get('method')} forecast for {code} projects "
                f"{series.get('projected_total')} from {horizon.get('start')} to "
                f"{horizon.get('end')} (range {series.get('projected_lower')} to "
                f"{series.get('projected_upper')})."
            )
    if not parts:
        parts.append("No analysis or forecast evidence was available.")
    parts.append("These figures come from stored billing, utilization and price evidence.")
    return " ".join(parts)


def _fallback_finding(item: dict[str, Any]) -> AdvisorFindingOut:
    finding_type = str(item.get("finding_type", ""))
    metrics = item.get("metrics") or {}
    currency = item.get("currency")
    baseline = item.get("baseline_monthly_cost")
    proposed = item.get("proposed_monthly_cost")
    savings = item.get("estimated_monthly_savings")
    resource = item.get("resource_id") or "the resource"
    confidence = item.get("confidence")
    observation = item.get("observation") or {}
    if finding_type == "idle_resource":
        detail = (
            f"CPU p95 peaked at {metrics.get('cpu_p95_max_pct')}% and memory p95 at "
            f"{metrics.get('memory_p95_max_pct')}% across {observation.get('sample_count')} "
            f"samples over {observation.get('days')} days. The scenario assumes a "
            "full-window stop with zero replacement spend."
        )
    elif finding_type == "over_provisioned":
        detail = (
            f"Mean CPU was {metrics.get('cpu_avg_pct')}% and mean memory "
            f"{metrics.get('memory_avg_pct')}%. The proposed SKU "
            f"{item.get('recommended_sku')} changes monthly cost from {currency} {baseline} "
            f"to {currency} {proposed}."
        )
    else:
        detail = (
            f"The rule engine flagged {resource} with a baseline of {currency} {baseline} "
            f"and proposed cost of {currency} {proposed}."
        )
    explanation = (
        f"{resource} was flagged as {finding_type} with {confidence} confidence. {detail} "
        f"The stored estimate is {currency} {savings} per month in savings."
    )
    assumptions = list(item.get("assumptions") or [])
    if not assumptions:
        assumptions = ["The finding uses only stored billing, utilization and price evidence."]
    evidence_ids = list(item.get("evidence_ids") or [])
    if not evidence_ids:
        evidence_ids = [f"finding-{str(item.get('finding_id', '0')).split('-')[-1]}"]
    evidence_ids = evidence_ids[:40]
    return AdvisorFindingOut(
        finding_id=str(item.get("finding_id")),
        explanation=explanation,
        evidence_ids=evidence_ids,
        assumptions=assumptions[:6],
        risk=cast(RiskLevel, str(item.get("risk", "medium"))),
        recommended_next_step=(
            "Ask the resource owner to validate the workload and dependencies, then record "
            "a human decision before any cloud change."
        ),
    )


# -- helpers --------------------------------------------------------------
def _contains_synthetic(package: dict[str, Any]) -> bool:
    analysis: dict[str, Any] = (
        package["analysis"] if isinstance(package.get("analysis"), dict) else {}
    )
    forecast: dict[str, Any] = (
        package["forecast"] if isinstance(package.get("forecast"), dict) else {}
    )
    if analysis.get("uses_synthetic_prices"):
        return True
    findings = analysis.get("findings", []) if isinstance(analysis, dict) else []
    if any(item.get("uses_synthetic_prices") for item in findings):
        return True
    if forecast.get("contains_sample_data"):
        return True
    texts = [*analysis.get("notes", []), *forecast.get("warnings", [])]
    return any("synthetic" in str(text).lower() for text in texts)


def _int_ids(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    return [int(item) for item in value if isinstance(item, int)]


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _span_days(start: date | None, end: date | None) -> int | None:
    if start is None or end is None:
        return None
    return (end - start).days + 1


def _serialize(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _size(value: Any) -> int:
    return len(_serialize(value))


def _api_key(settings: Settings) -> str:
    return settings.llm_api_key.get_secret_value().strip()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
