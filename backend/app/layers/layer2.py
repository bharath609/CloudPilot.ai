"""Layer 2 — Cloud Digital Twin Engine.

Models resources and runs isolated what-if simulations. A simulation never mutates
production state and always reports its assumptions and confidence. Currency is
preserved from the resource; no FX conversion is applied.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional


def _money(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def simulate(
    resource: Dict[str, Any],
    scenario: str,
    utilization_retention: float = 0.0,
    sku_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Run a what-if simulation for a single resource.

    scenario: "stop" or "rightsize".
    utilization_retention: 0..100, percent of baseline cost kept (stop scenario).
    sku_ratio: new/current SKU price ratio (rightsize scenario), 0.01..2.00.
    """
    currency = resource.get("currency", "USD")
    baseline = Decimal(str(resource.get("baseline_monthly_cost") or 0))
    assumptions: List[str] = []
    warnings: List[str] = []

    if scenario == "stop":
        retention = max(0.0, min(100.0, float(utilization_retention))) / 100.0
        projected = baseline * Decimal(str(retention))
        savings = baseline - projected
        assumptions.append(
            "Savings assume the resource is stopped for the full monthly window and "
            "no replacement resource is provisioned."
        )
        assumptions.append(
            f"All amounts remain in {currency}; no FX conversion is applied."
        )
        if retention >= 0.5:
            confidence = "high"
        elif retention > 0:
            confidence = "medium"
        else:
            confidence = "medium"
        warnings.append(
            "Low utilization is not proof of waste; an owner must confirm the workload can be stopped."
        )
    elif scenario == "rightsize":
        ratio = float(sku_ratio if sku_ratio is not None else 0.5)
        ratio = max(0.01, min(2.0, ratio))
        projected = baseline * Decimal(str(ratio))
        savings = baseline - projected
        if savings < 0:
            savings = Decimal("0")
        assumptions.append(
            f"Proposed cost scales the baseline by the catalogue price ratio "
            f"{ratio:.2f} for the same provider, region and currency ({currency})."
        )
        assumptions.append(
            f"No FX conversion or negotiated discount is applied. All amounts are in {currency}."
        )
        warnings.append(
            "No performance, network or storage requirement is modelled; the smaller SKU "
            "must be validated by the resource owner."
        )
        if ratio <= 0.5:
            confidence = "high"
        elif ratio <= 0.8:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return {
        "resource_id": resource.get("resource_id"),
        "scenario": scenario,
        "currency": currency,
        "baseline_monthly_cost": _money(baseline),
        "projected_monthly_cost": _money(projected),
        "projected_monthly_savings": _money(savings),
        "confidence": confidence,
        "assumptions": assumptions,
        "warnings": warnings,
        "production_isolated": True,
        "note": "Simulation is isolated from production; no real changes are applied.",
    }
