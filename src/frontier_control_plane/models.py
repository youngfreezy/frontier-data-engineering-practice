"""Typed records serialized by the control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    registered = "registered"
    claimed = "claimed"
    running = "running"
    verified = "verified"
    approved = "approved"
    submitted = "submitted"
    failed = "failed"


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    task_id: str
    candidate_id: str
    attempt: int
    starting_commit: str
    dataset_hash: str
    environment_hash: str

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "task_id",
            "candidate_id",
            "starting_commit",
            "dataset_hash",
            "environment_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunIdentity":
        return cls(**data)


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str
    evidence: tuple[str, ...] = ()
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("gate name is required")
        if not self.detail.strip():
            raise ValueError("gate detail is required")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateResult":
        return cls(
            name=str(data["name"]),
            passed=bool(data["passed"]),
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
    missing_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in ("missing_gates", "failed_gates", "missing_fields"):
            data[name] = list(data[name])
        return data


@dataclass
class RunRecord:
    identity: RunIdentity
    required_gates: tuple[str, ...]
    status: RunStatus = RunStatus.registered
    owner: str | None = None
    result_hash: str | None = None
    gates: dict[str, GateResult] = field(default_factory=dict)
    artifacts: dict[str, ArtifactReceipt] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    approved_by: str | None = None
    submitted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "required_gates": list(self.required_gates),
            "status": self.status.value,
            "owner": self.owner,
            "result_hash": self.result_hash,
            "gates": {name: gate.to_dict() for name, gate in self.gates.items()},
            "artifacts": {
                name: artifact.to_dict() for name, artifact in self.artifacts.items()
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
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            approved_by=data.get("approved_by"),
            submitted_at=data.get("submitted_at"),
        )
