"""Layer 4 — Autonomous Investigation Agent.

Runs a deterministic 8-step investigation over available evidence. The agent is
explicitly allowed to conclude "insufficient evidence" and must never invent a
root cause. Every conclusion is tied to evidence, and data gaps are always listed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class Investigation:
    investigation_id: str
    finding_id: str
    currency: str
    status: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    causes: List[Dict[str, Any]] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def investigate(
    investigation_id: str,
    finding: Dict[str, Any],
    resource: Dict[str, Any] | None,
    daily_amounts: List[float],
) -> Investigation:
    """Execute the 8-step investigation for a finding."""
    currency = finding.get("currency", "USD")
    evidence = finding.get("evidence", []) or []
    steps: List[Dict[str, Any]] = []
    data_gaps: List[str] = []
    causes: List[Dict[str, Any]] = []

    # Step 1 — examine spending
    steps.append({
        "step": 1,
        "name": "Examine spending changes",
        "finding": f"Baseline monthly cost {finding.get('baseline_monthly_cost')} {currency}.",
    })

    # Step 2 — affected service
    steps.append({
        "step": 2,
        "name": "Identify affected service",
        "finding": f"Resource {finding.get('resource_id')} ({finding.get('finding_type')}).",
    })

    # Step 3 — retrieve metrics
    if resource:
        steps.append({
            "step": 3,
            "name": "Retrieve metrics",
            "finding": f"CPU {resource.get('cpu_pct')}%, memory {resource.get('memory_pct')}%.",
        })
    else:
        steps.append({"step": 3, "name": "Retrieve metrics", "finding": "Resource metadata unavailable."})
        data_gaps.append("No resource metadata found for this finding.")

    # Step 4 — deployment history
    steps.append({
        "step": 4,
        "name": "Examine deployment history",
        "finding": "No deployment events are available in this dataset.",
    })
    data_gaps.append("No deployment events recorded; deployment correlation is not possible.")

    # Step 5 — historical comparison
    if len(daily_amounts) >= 7:
        steps.append({
            "step": 5,
            "name": "Compare historical behavior",
            "finding": f"{len(daily_amounts)} days of history available for {currency}.",
        })
    else:
        steps.append({"step": 5, "name": "Compare historical behavior", "finding": "Limited history."})
        data_gaps.append("Fewer than 7 days of history for this currency.")

    # Step 6 — identify causes strictly from evidence
    if evidence:
        causes.append({
            "cause": "utilization_evidence",
            "likelihood": "medium",
            "supporting_evidence": evidence,
        })
        steps.append({
            "step": 6,
            "name": "Identify causes",
            "finding": f"{len(causes)} cause(s) identified from evidence.",
        })
    else:
        causes.append({
            "cause": "insufficient_evidence",
            "likelihood": "unknown",
            "supporting_evidence": [],
        })
        data_gaps.append("No supporting evidence was attached to this finding.")
        steps.append({
            "step": 6,
            "name": "Identify causes",
            "finding": "Insufficient evidence to identify a root cause.",
        })

    # Step 7 — present evidence and gaps
    steps.append({
        "step": 7,
        "name": "Present evidence and data gaps",
        "finding": f"{len(evidence)} evidence item(s); {len(data_gaps)} data gap(s).",
    })

    # Step 8 — recommend actions
    recommended = [
        "Have the resource owner confirm the workload can be changed.",
        "Run a Simulation Lab what-if before executing any change.",
        "Apply policy checks and require approval for production changes.",
    ]
    steps.append({
        "step": 8,
        "name": "Recommend actions",
        "finding": f"{len(recommended)} recommended action(s) generated.",
    })

    # Confidence from evidence quantity and coverage of gaps
    confidence = 0.0
    if evidence:
        confidence = min(0.8, 0.2 + 0.15 * len(evidence))
    if len(data_gaps) >= 3:
        confidence = max(0.1, confidence - 0.2)

    status = "complete" if evidence else "insufficient_evidence"

    return Investigation(
        investigation_id=investigation_id,
        finding_id=finding.get("id", ""),
        currency=currency,
        status=status,
        steps=steps,
        causes=causes,
        data_gaps=data_gaps,
        recommended_actions=recommended,
        confidence=round(confidence, 2),
    )
