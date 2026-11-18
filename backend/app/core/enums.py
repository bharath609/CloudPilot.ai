"""Domain enumerations shared by the API, services and ORM models."""

from __future__ import annotations

from enum import StrEnum


class ImportKind(StrEnum):
    BILLING = "billing"
    UTILIZATION = "utilization"


class ImportStatus(StrEnum):
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    PARTIAL = "partial"
    INVALID = "invalid"
    FAILED = "failed"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Provider(StrEnum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    SAMPLE = "sample"


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"
    UNKNOWN = "unknown"


class CostDimension(StrEnum):
    """Dimensions that spend can be grouped by."""

    SERVICE = "service"
    PROJECT = "project"
    REGION = "region"
    ENVIRONMENT = "environment"
    PROVIDER = "provider"
    ACCOUNT = "account"
    RESOURCE = "resource"


class TrendGranularity(StrEnum):
    DAY = "day"
    MONTH = "month"


class FindingType(StrEnum):
    IDLE_RESOURCE = "idle_resource"
    OVER_PROVISIONED = "over_provisioned"


class FindingStatus(StrEnum):
    OPEN = "open"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScenarioMethod(StrEnum):
    STOP_RESOURCE = "stop_resource"
    RIGHTSIZE_SKU = "rightsize_sku"


class DecisionKind(StrEnum):
    """A human reviewer's recorded response to one finding."""

    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_OWNER_REVIEW = "needs_owner_review"


class ForecastMethod(StrEnum):
    """Transparent, deterministic baseline models only."""

    SEASONAL_NAIVE = "seasonal_naive"
    MOVING_AVERAGE = "moving_average"


class ForecastGranularity(StrEnum):
    DAY = "day"


PROVIDERS = frozenset(provider.value for provider in Provider)
ENVIRONMENTS = frozenset(environment.value for environment in Environment)
