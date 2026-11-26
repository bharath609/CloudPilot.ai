"""Layer 5 — Policy-Based Execution.

The execution engine — not a language model — enforces policy. Destructive actions
are blocked or require approval; environments and spending deltas are constrained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class ActionType(str, Enum):
    READ_CLOUD_METRICS = "read_cloud_metrics"
    INVESTIGATE_ANOMALY = "investigate_anomaly"
    GENERATE_SIMULATION = "generate_simulation"
    STOP_RESOURCE = "stop_resource"
    RESIZE_RESOURCE = "resize_resource"
    DELETE_RESOURCE = "delete_resource"
    MODIFY_SECURITY_POLICY = "modify_security_policy"


@dataclass
class PolicyRule:
    rule_id: str
    name: str
    action_type: ActionType
    allow: bool = True
    allowed_environments: Set[str] = field(default_factory=set)
    max_spending_delta: Optional[float] = None
    requires_approval: bool = False
    destructive: bool = False


@dataclass
class PolicyDecision:
    allowed: bool
    action_type: str
    resource_id: str
    environment: str
    requires_approval: bool
    rule_id: Optional[str]
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def default_rules() -> List[PolicyRule]:
    return [
        PolicyRule("allow_read", "Read cloud metrics", ActionType.READ_CLOUD_METRICS, allow=True),
        PolicyRule("allow_investigate", "Investigate anomalies", ActionType.INVESTIGATE_ANOMALY, allow=True),
        PolicyRule("allow_simulate", "Generate simulations", ActionType.GENERATE_SIMULATION, allow=True),
        PolicyRule(
            "stop_prod_approval", "Stopping production requires approval",
            ActionType.STOP_RESOURCE, allow=True,
            allowed_environments={"production", "staging", "development"},
            requires_approval=True, destructive=True,
        ),
        PolicyRule(
            "resize_approval", "Resizing requires approval over threshold",
            ActionType.RESIZE_RESOURCE, allow=True,
            allowed_environments={"production", "staging", "development"},
            max_spending_delta=100.0, requires_approval=True,
        ),
        PolicyRule(
            "block_delete", "Deleting resources is prohibited",
            ActionType.DELETE_RESOURCE, allow=False, destructive=True, requires_approval=True,
        ),
        PolicyRule(
            "security_approval", "Security policy changes require approval",
            ActionType.MODIFY_SECURITY_POLICY, allow=True, requires_approval=True,
        ),
    ]


class PolicyEngine:
    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self.rules: Dict[str, PolicyRule] = {}
        for rule in rules or default_rules():
            self.rules[rule.rule_id] = rule

    def evaluate(
        self,
        action_type: str,
        resource_id: str,
        environment: str,
        requesting_user: str,
        spending_delta: float = 0.0,
    ) -> PolicyDecision:
        try:
            action = ActionType(action_type)
        except ValueError:
            return PolicyDecision(
                allowed=False, action_type=action_type, resource_id=resource_id,
                environment=environment, requires_approval=True, rule_id=None,
                violations=[f"Unknown action type: {action_type}"],
            )

        matching = [r for r in self.rules.values() if r.action_type == action]
        if not matching:
            # Fail closed for destructive/unknown actions, open for read-only.
            if action in (ActionType.READ_CLOUD_METRICS, ActionType.INVESTIGATE_ANOMALY, ActionType.GENERATE_SIMULATION):
                return PolicyDecision(True, action.value, resource_id, environment, False, None)
            return PolicyDecision(
                False, action.value, resource_id, environment, True, None,
                [f"No policy configured for action {action.value}."],
            )

        rule = matching[0]
        violations: List[str] = []

        if not rule.allow:
            violations.append(f"Action {action.value} is prohibited by policy '{rule.rule_id}'.")

        if rule.allowed_environments and environment not in rule.allowed_environments:
            violations.append(
                f"Environment '{environment}' is not allowed by policy '{rule.rule_id}'."
            )

        if rule.max_spending_delta is not None and abs(spending_delta) > rule.max_spending_delta:
            violations.append(
                f"Spending delta {abs(spending_delta):.2f} exceeds policy limit "
                f"{rule.max_spending_delta:.2f}."
            )

        allowed = not violations
        return PolicyDecision(
            allowed=allowed,
            action_type=action.value,
            resource_id=resource_id,
            environment=environment,
            requires_approval=rule.requires_approval,
            rule_id=rule.rule_id,
            violations=violations,
        )
