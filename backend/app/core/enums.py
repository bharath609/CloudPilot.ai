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


PROVIDERS = frozenset(provider.value for provider in Provider)
ENVIRONMENTS = frozenset(environment.value for environment in Environment)
