"""Typed records serialized by the control plane."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


LEGACY_REQUIREMENTS_HASH = "legacy-unrecorded"


class RunStatus(str, Enum):
    registered = "registered"
    claimed = "claimed"
    running = "running"
    verified = "verified"
    approved = "approved"
    submitted = "submitted"
    failed = "failed"


class GateStatus(str, Enum):
    passed = "pass"
    failed = "fail"
    not_run = "not_run"
    not_applicable = "not_applicable"


class OutcomeClass(str, Enum):
    solved = "solved"
    completed_semantic_failure = "completed_semantic_failure"
    timeout = "timeout"
    oom = "oom"
    infrastructure = "infrastructure"
    malformed_artifact = "malformed_artifact"
    missing_artifact = "missing_artifact"
    transport_failure = "transport_failure"


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    task_id: str
    candidate_id: str
    attempt: int
    starting_commit: str
    dataset_hash: str
    environment_hash: str
    requirements_hash: str

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "task_id",
            "candidate_id",
            "starting_commit",
            "dataset_hash",
            "environment_hash",
            "requirements_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunIdentity":
        payload = dict(data)
        payload.setdefault("requirements_hash", LEGACY_REQUIREMENTS_HASH)
        return cls(**payload)


@dataclass(frozen=True)
class GateResult:
    name: str
    status: GateStatus
    detail: str
    evidence: tuple[str, ...]
    applicability_basis: str | None = None
    residual_risk: str | None = None
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("gate name is required")
        if not self.detail.strip():
            raise ValueError("gate detail is required")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise ValueError("at least one non-empty evidence item is required")
        if self.status == GateStatus.not_applicable and not (
            self.applicability_basis and self.applicability_basis.strip()
        ):
            raise ValueError("not_applicable requires the quoted task basis")
        if self.status == GateStatus.not_run and not (
            self.residual_risk and self.residual_risk.strip()
        ):
            raise ValueError("not_run requires a residual risk")

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": list(self.evidence),
            "applicability_basis": self.applicability_basis,
            "residual_risk": self.residual_risk,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateResult":
        status = data.get("status")
        if status is None:
            status = GateStatus.passed if data.get("passed") else GateStatus.failed
        evidence = tuple(str(item) for item in data.get("evidence") or ())
        if not evidence:
            evidence = ("legacy record: evidence was not captured",)
        return cls(
            name=str(data["name"]),
            status=GateStatus(status),
            detail=str(data["detail"]),
            evidence=evidence,
            applicability_basis=data.get("applicability_basis"),
            residual_risk=data.get("residual_risk"),
            recorded_at=str(data.get("recorded_at") or ""),
        )


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_class: OutcomeClass
    detail: str
    evidence: tuple[str, ...]
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("outcome detail is required")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise ValueError("at least one non-empty outcome evidence item is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_class": self.outcome_class.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeRecord":
        return cls(
            outcome_class=OutcomeClass(data["outcome_class"]),
            detail=str(data["detail"]),
            evidence=tuple(str(item) for item in data.get("evidence") or ()),
            recorded_at=str(data.get("recorded_at") or ""),
        )


@dataclass(frozen=True)
class Measurement:
    name: str
    value: float
    unit: str
    evidence: tuple[str, ...]
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.unit.strip():
            raise ValueError("measurement name and unit are required")
        if not math.isfinite(self.value):
            raise ValueError("measurement value must be finite")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise ValueError("measurement evidence is required")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Measurement":
        return cls(
            name=str(data["name"]),
            value=float(data["value"]),
            unit=str(data["unit"]),
            evidence=tuple(str(item) for item in data.get("evidence") or ()),
            recorded_at=str(data.get("recorded_at") or ""),
        )


@dataclass(frozen=True)
class ResidualRisk:
    name: str
    detail: str
    evidence: tuple[str, ...]
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.detail.strip():
            raise ValueError("risk name and detail are required")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise ValueError("risk evidence is required")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResidualRisk":
        return cls(
            name=str(data["name"]),
            detail=str(data["detail"]),
            evidence=tuple(str(item) for item in data.get("evidence") or ()),
            recorded_at=str(data.get("recorded_at") or ""),
        )


@dataclass(frozen=True)
class ArtifactReceipt:
    name: str
    path: str
    sha256: str
    size: int
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.path.strip() or not self.sha256.strip():
            raise ValueError("artifact name, path, and sha256 are required")
        if self.size < 0:
            raise ValueError("artifact size cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactReceipt":
        return cls(**data)


@dataclass(frozen=True)
class Verification:
    run_id: str
    passed: bool
    missing_gates: tuple[str, ...] = ()
    failed_gates: tuple[str, ...] = ()
    not_run_gates: tuple[str, ...] = ()
    not_applicable_gates: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    stale_artifacts: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    blocking_outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in (
            "missing_gates",
            "failed_gates",
            "not_run_gates",
            "not_applicable_gates",
            "missing_artifacts",
            "stale_artifacts",
            "missing_fields",
        ):
            data[name] = list(data[name])
        return data


@dataclass
class RunRecord:
    identity: RunIdentity
    required_gates: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    status: RunStatus = RunStatus.registered
    owner: str | None = None
    result_hash: str | None = None
    gates: dict[str, GateResult] = field(default_factory=dict)
    artifacts: dict[str, ArtifactReceipt] = field(default_factory=dict)
    outcome: OutcomeRecord | None = None
    measurements: dict[str, Measurement] = field(default_factory=dict)
    residual_risks: dict[str, ResidualRisk] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    approved_by: str | None = None
    submitted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "required_gates": list(self.required_gates),
            "required_artifacts": list(self.required_artifacts),
            "status": self.status.value,
            "owner": self.owner,
            "result_hash": self.result_hash,
            "gates": {name: gate.to_dict() for name, gate in self.gates.items()},
            "artifacts": {
                name: artifact.to_dict() for name, artifact in self.artifacts.items()
            },
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "measurements": {
                name: measurement.to_dict()
                for name, measurement in self.measurements.items()
            },
            "residual_risks": {
                name: risk.to_dict() for name, risk in self.residual_risks.items()
            },
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_by": self.approved_by,
            "submitted_at": self.submitted_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            identity=RunIdentity.from_dict(data["identity"]),
            required_gates=tuple(str(item) for item in data.get("required_gates") or ()),
            required_artifacts=tuple(
                str(item) for item in data.get("required_artifacts") or ("result",)
            ),
            status=RunStatus(data.get("status") or RunStatus.registered.value),
            owner=data.get("owner"),
            result_hash=data.get("result_hash"),
            gates={
                name: GateResult.from_dict(value)
                for name, value in (data.get("gates") or {}).items()
            },
            artifacts={
                name: ArtifactReceipt.from_dict(value)
                for name, value in (data.get("artifacts") or {}).items()
            },
            outcome=(
                OutcomeRecord.from_dict(data["outcome"])
                if data.get("outcome")
                else None
            ),
            measurements={
                name: Measurement.from_dict(value)
                for name, value in (data.get("measurements") or {}).items()
            },
            residual_risks={
                name: ResidualRisk.from_dict(value)
                for name, value in (data.get("residual_risks") or {}).items()
            },
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            approved_by=data.get("approved_by"),
            submitted_at=data.get("submitted_at"),
        )
