"""Layer 3 — Predictive Intelligence.

Statistical anomaly detection for spending, capacity pressure and performance
degradation. Spending is always evaluated per currency — values from different
currencies are never combined or converted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional


@dataclass
class AnomalyResult:
    kind: str
    currency: str
    detected: bool
    description: str
    confidence: str
    baseline: float
    current: float
    change_pct: float
    threshold: float
    evidence: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_spending_anomaly(
    daily_amounts: List[float],
    current_amount: float,
    currency: str,
    sensitivity: float = 2.0,
) -> AnomalyResult:
    """Z-score spending anomaly against a currency's own daily history."""
    if len(daily_amounts) < 7 or not daily_amounts:
        return AnomalyResult(
            kind="spending",
            currency=currency,
            detected=False,
            description="Insufficient history to evaluate spending anomaly.",
            confidence="low",
            baseline=0.0,
            current=round(current_amount, 2),
            change_pct=0.0,
            threshold=sensitivity,
            data_gaps=["Fewer than 7 days of history for this currency."],
        )

    mu = mean(daily_amounts)
    sigma = pstdev(daily_amounts)
    if sigma == 0:
        return AnomalyResult(
            kind="spending",
            currency=currency,
            detected=False,
            description="Spending is flat; no variance to evaluate.",
            confidence="low",
            baseline=round(mu, 2),
            current=round(current_amount, 2),
            change_pct=0.0,
            threshold=sensitivity,
            data_gaps=["Zero variance in history."],
        )

    z = (current_amount - mu) / sigma
    change_pct = ((current_amount - mu) / mu * 100.0) if mu else 0.0
    detected = abs(z) >= sensitivity
    confidence = "high" if abs(z) >= 3 else ("medium" if detected else "low")

    return AnomalyResult(
        kind="spending",
        currency=currency,
        detected=detected,
        description=(
            f"Spending is {'above' if z > 0 else 'below'} the {currency} historical mean "
            f"by {abs(z):.2f} sigma ({current_amount:.2f} vs {mu:.2f} mean)."
        ),
        confidence=confidence,
        baseline=round(mu, 2),
        current=round(current_amount, 2),
        change_pct=round(change_pct, 2),
        threshold=sensitivity,
        evidence=[
            f"mean_spend={mu:.2f} {currency}",
            f"pstdev={sigma:.2f} {currency}",
            f"z_score={z:.2f}",
        ],
        data_gaps=["Single-point evaluation; seasonal patterns are not modelled."],
        recommended_actions=[
            "Investigate recent deployments or resource provisioning.",
            "Check for SKU/size changes around the spike.",
            "Review billing period boundaries.",
        ],
    )


def detect_capacity_exhaustion(
    cpu_pct: float, resource_id: str, currency: str, threshold_pct: float = 80.0
) -> AnomalyResult:
    detected = cpu_pct >= threshold_pct
    return AnomalyResult(
        kind="capacity",
        currency=currency,
        detected=detected,
        description=(
            f"CPU utilisation is {cpu_pct:.1f}% (threshold {threshold_pct:.0f}%)."
            if detected
            else f"CPU utilisation is within range at {cpu_pct:.1f}%."
        ),
        confidence="high" if detected else "low",
        baseline=threshold_pct,
        current=round(cpu_pct, 2),
        change_pct=0.0,
        threshold=threshold_pct,
        evidence=[f"resource_id={resource_id}", f"cpu_pct={cpu_pct:.2f}"],
        data_gaps=["No memory/disk/network pressure inputs in this check."],
        recommended_actions=(
            ["Consider resizing or scaling out.", "Set an alert near the threshold."]
            if detected
            else []
        ),
    )


def detect_performance_degradation(
    historical: List[float],
    current: List[float],
    resource_id: str,
    currency: str,
    threshold_pct: float = -10.0,
) -> AnomalyResult:
    if not historical or not current:
        return AnomalyResult(
            kind="performance",
            currency=currency,
            detected=False,
            description="Insufficient metrics to evaluate performance.",
            confidence="low",
            baseline=0.0,
            current=0.0,
            change_pct=0.0,
            threshold=threshold_pct,
            data_gaps=["Missing historical or current metric windows."],
        )

    hist_mean = mean(historical)
    cur_mean = mean(current)
    change_pct = ((cur_mean - hist_mean) / hist_mean * 100.0) if hist_mean else 0.0
    detected = change_pct <= threshold_pct

    return AnomalyResult(
        kind="performance",
        currency=currency,
        detected=detected,
        description=(
            f"Performance changed {change_pct:+.1f}% vs baseline "
            f"(threshold {threshold_pct:+.0f}%)."
        ),
        confidence="medium" if detected else "low",
        baseline=round(hist_mean, 2),
        current=round(cur_mean, 2),
        change_pct=round(change_pct, 2),
        threshold=threshold_pct,
        evidence=[f"resource_id={resource_id}", f"baseline_mean={hist_mean:.2f}", f"current_mean={cur_mean:.2f}"],
        data_gaps=["Metric units are not normalized across providers."],
        recommended_actions=(
            ["Investigate recent deployments or contention.", "Review monitoring alerts."]
            if detected
            else []
        ),
    )
