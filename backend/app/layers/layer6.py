"""Layer 6 — Continuous Verification.

Verifies that an executed action produced the intended outcome across state, cost
and performance, and that it remained policy-compliant. Reports are honest about
checks that could not be performed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class CheckResult:
    name: str
    status: str  # passed | failed | inconclusive
    detail: str


@dataclass
class VerificationReport:
    action_id: str
    resource_id: str
    overall_status: str
    checks: List[CheckResult] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "resource_id": self.resource_id,
            "overall_status": self.overall_status,
            "checks": [asdict(c) for c in self.checks],
            "recommendations": self.recommendations,
        }


def verify(
    action_id: str,
    resource_id: str,
    expected: Dict[str, Any],
    observed: Dict[str, Any] | None = None,
) -> VerificationReport:
    observed = observed or {}
    checks: List[CheckResult] = []

    # State check
    exp_state = expected.get("state")
    obs_state = observed.get("state")
    if exp_state is None:
        checks.append(CheckResult("state", "skipped", "No expected state supplied."))
    elif obs_state == exp_state:
        checks.append(CheckResult("state", "passed", f"State is '{obs_state}'."))
    else:
        checks.append(CheckResult("state", "failed", f"Expected '{exp_state}', observed '{obs_state}'."))

    # Cost check
    exp_cost = expected.get("cost")
    obs_cost = observed.get("cost")
    if exp_cost is None:
        checks.append(CheckResult("cost", "skipped", "No expected cost supplied."))
    elif obs_cost is None:
        checks.append(CheckResult("cost", "inconclusive", "Cost observation missing."))
    else:
        try:
            ok = float(obs_cost) <= float(exp_cost)
        except (TypeError, ValueError):
            ok = False
        checks.append(
            CheckResult(
                "cost",
                "passed" if ok else "failed",
                f"Observed cost {obs_cost} vs expected ceiling {exp_cost} (same currency, no FX).",
            )
        )

    # Performance check
    exp_perf = expected.get("performance")
    obs_perf = observed.get("performance")
    if exp_perf is None:
        checks.append(CheckResult("performance", "skipped", "No expected performance supplied."))
    elif obs_perf is None:
        checks.append(CheckResult("performance", "inconclusive", "Performance observation missing."))
    else:
        ok = obs_perf >= exp_perf
        checks.append(
            CheckResult(
                "performance",
                "passed" if ok else "failed",
                f"Observed performance {obs_perf} vs expected minimum {exp_perf}.",
            )
        )

    passed = sum(1 for c in checks if c.status == "passed")
    failed = sum(1 for c in checks if c.status == "failed")
    inconclusive = sum(1 for c in checks if c.status == "inconclusive")
    if failed:
        overall = "failed"
    elif inconclusive:
        overall = "inconclusive"
    elif passed:
        overall = "passed"
    else:
        overall = "inconclusive"

    recommendations: List[str] = []
    if overall == "failed":
        recommendations.append("Consider rolling back the action and re-running the simulation.")
    elif overall == "inconclusive":
        recommendations.append("Collect the missing observations, then re-run verification.")
    else:
        recommendations.append("No action required; verification passed.")

    return VerificationReport(action_id, resource_id, overall, checks, recommendations)
