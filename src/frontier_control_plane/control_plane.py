"""Fail-closed run lifecycle and evidence ledger."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .hashing import sha256_file
from .models import (
    LEGACY_REQUIREMENTS_HASH,
    ArtifactReceipt,
    GateResult,
    GateStatus,
    Measurement,
    OutcomeClass,
    OutcomeRecord,
    ResidualRisk,
    RunIdentity,
    RunRecord,
    RunStatus,
    Verification,
)
from .store import AtomicJsonStore


BASELINE_GATES = frozenset({"clean_checkout", "unit_tests"})
RETRYABLE_OUTCOMES = frozenset(
    {
        OutcomeClass.timeout,
        OutcomeClass.oom,
        OutcomeClass.infrastructure,
        OutcomeClass.malformed_artifact,
        OutcomeClass.missing_artifact,
        OutcomeClass.transport_failure,
    }
)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_sha256(value: str, name: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{name} must be a 64-character SHA-256 digest")
    return normalized


class ControlPlaneError(RuntimeError):
    pass


class OwnershipConflict(ControlPlaneError):
    pass


class ControlPlane:
    def __init__(self, state_path: str | Path):
        self.store = AtomicJsonStore(state_path)

    @staticmethod
    def _event(state: dict[str, Any], run_id: str, action: str, detail: str) -> None:
        state.setdefault("events", []).append(
            {"at": utc_now(), "run_id": run_id, "action": action, "detail": detail}
        )
        state["updated_at"] = utc_now()

    @staticmethod
    def _get(state: dict[str, Any], run_id: str) -> RunRecord:
        raw = state.get("runs", {}).get(run_id)
        if raw is None:
            raise ControlPlaneError(f"unknown run {run_id}")
        return RunRecord.from_dict(raw)

    @staticmethod
    def _put(state: dict[str, Any], record: RunRecord) -> None:
        record.updated_at = utc_now()
        state.setdefault("runs", {})[record.identity.run_id] = record.to_dict()

    @staticmethod
    def _ensure_mutable(
        record: RunRecord, category: str, state: dict[str, Any]
    ) -> None:
        if record.status in {RunStatus.approved, RunStatus.submitted}:
            raise ControlPlaneError(
                f"cannot change {category} in {record.status.value}"
            )
        if any(
            (raw.get("metadata") or {}).get("retry_of")
            == record.identity.run_id
            for raw in state.get("runs", {}).values()
        ):
            raise ControlPlaneError(
                f"cannot change {category} after a clean retry was registered"
            )

    @staticmethod
    def _artifact_issues(
        record: RunRecord,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        missing = tuple(
            name for name in record.required_artifacts if name not in record.artifacts
        )
        stale: list[str] = []
        for name, receipt in record.artifacts.items():
            path = Path(receipt.path)
            try:
                if not path.is_file():
                    stale.append(name)
                    continue
                if path.stat().st_size != receipt.size:
                    stale.append(name)
                    continue
                if sha256_file(path) != receipt.sha256:
                    stale.append(name)
            except OSError:
                stale.append(name)
        return missing, tuple(stale)

    @classmethod
    def _verification_for(cls, record: RunRecord) -> Verification:
        missing_gates = tuple(
            name for name in record.required_gates if name not in record.gates
        )
        failed_gates = tuple(
            name
            for name in record.required_gates
            if name in record.gates
            and record.gates[name].status == GateStatus.failed
        )
        not_run_gates = tuple(
            name
            for name in record.required_gates
            if name in record.gates
            and record.gates[name].status == GateStatus.not_run
        )
        not_applicable_gates = tuple(
            name
            for name in record.required_gates
            if name in record.gates
            and record.gates[name].status == GateStatus.not_applicable
        )
        missing_artifacts, stale_artifacts = cls._artifact_issues(record)
        missing_fields: list[str] = []
        if not record.result_hash:
            missing_fields.append("result_hash")
        if not record.owner:
            missing_fields.append("owner")
        if record.outcome is None:
            missing_fields.append("outcome")
        blocking_outcome = None
        if record.outcome and record.outcome.outcome_class != OutcomeClass.solved:
            blocking_outcome = record.outcome.outcome_class.value
        passed = not any(
            (
                missing_gates,
                failed_gates,
                not_run_gates,
                missing_artifacts,
                stale_artifacts,
                missing_fields,
                blocking_outcome,
            )
        )
        return Verification(
            run_id=record.identity.run_id,
            passed=passed,
            missing_gates=missing_gates,
            failed_gates=failed_gates,
            not_run_gates=not_run_gates,
            not_applicable_gates=not_applicable_gates,
            missing_artifacts=missing_artifacts,
            stale_artifacts=stale_artifacts,
            missing_fields=tuple(missing_fields),
            blocking_outcome=blocking_outcome,
        )

    @classmethod
    def _record_verification(
        cls,
        state: dict[str, Any],
        record: RunRecord,
        verification: Verification,
    ) -> None:
        record.status = RunStatus.verified if verification.passed else RunStatus.failed
        cls._put(state, record)
        cls._event(
            state,
            record.identity.run_id,
            "verify",
            "PASS" if verification.passed else str(verification.to_dict()),
        )

    @classmethod
    def _validate_retry(
        cls,
        state: dict[str, Any],
        identity: RunIdentity,
        metadata: dict[str, Any],
        required_gates: tuple[str, ...],
        required_artifacts: tuple[str, ...],
    ) -> None:
        retry_of = metadata.get("retry_of")
        if not retry_of:
            return
        parent = cls._get(state, str(retry_of))
        if parent.metadata.get("retry_of"):
            raise ControlPlaneError("a retry attempt cannot be retried again")
        if not parent.outcome or parent.outcome.outcome_class not in RETRYABLE_OUTCOMES:
            raise ControlPlaneError(
                "retry_of must reference a typed non-semantic failure"
            )
        comparable_fields = (
            "task_id",
            "candidate_id",
            "starting_commit",
            "dataset_hash",
            "environment_hash",
            "requirements_hash",
        )
        if any(
            getattr(parent.identity, name) != getattr(identity, name)
            for name in comparable_fields
        ) or identity.attempt <= parent.identity.attempt:
            raise ControlPlaneError(
                "retry identity must match its parent and use a later attempt"
            )
        if (
            set(parent.required_gates) != set(required_gates)
            or set(parent.required_artifacts) != set(required_artifacts)
        ):
            raise ControlPlaneError(
                "retry gates and required artifacts must match the parent"
            )
        for raw in state.get("runs", {}).values():
            existing = RunRecord.from_dict(raw)
            if existing.metadata.get("retry_of") == retry_of:
                raise ControlPlaneError(f"{retry_of} already has a clean retry")

    def register(
        self,
        identity: RunIdentity,
        required_gates: Iterable[str],
        metadata: dict[str, Any] | None = None,
        required_artifacts: Iterable[str] = ("result",),
    ) -> RunRecord:
        required = tuple(
            dict.fromkeys(
                str(item).strip() for item in required_gates if str(item).strip()
            )
        )
        missing_baseline = sorted(BASELINE_GATES - set(required))
        if missing_baseline:
            raise ValueError(
                "required gates must include " + ", ".join(missing_baseline)
            )
        artifacts = tuple(
            dict.fromkeys(
                str(item).strip() for item in required_artifacts if str(item).strip()
            )
        )
        if not artifacts:
            raise ValueError("at least one required artifact is needed")
        require_sha256(identity.dataset_hash, "dataset_hash")
        require_sha256(identity.environment_hash, "environment_hash")
        require_sha256(identity.requirements_hash, "requirements_hash")
        if not COMMIT_PATTERN.fullmatch(identity.starting_commit):
            raise ValueError("starting_commit must be a 7-64 character hex digest")

        def mutate(state: dict[str, Any]) -> RunRecord:
            existing = state.setdefault("runs", {}).get(identity.run_id)
            if existing:
                record = RunRecord.from_dict(existing)
                if (
                    record.identity != identity
                    or record.required_gates != required
                    or record.required_artifacts != artifacts
                ):
                    raise ControlPlaneError(
                        f"run id collision for {identity.run_id}"
                    )
                return record
            run_metadata = dict(metadata or {})
            self._validate_retry(
                state, identity, run_metadata, required, artifacts
            )
            now = utc_now()
            record = RunRecord(
                identity=identity,
                required_gates=required,
                required_artifacts=artifacts,
                metadata=run_metadata,
                created_at=now,
                updated_at=now,
            )
            self._put(state, record)
            self._event(
                state,
                identity.run_id,
                "registered",
                f"required_gates={','.join(required)} "
                f"required_artifacts={','.join(artifacts)}",
            )
            return record

        return self.store.update(mutate)

    def claim(self, run_id: str, owner: str) -> RunRecord:
        if not owner.strip():
            raise ValueError("owner is required")

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            if record.owner and record.owner != owner:
                raise OwnershipConflict(f"{run_id} already owned by {record.owner}")
            self._ensure_mutable(record, "claim", state)
            record.owner = owner
            record.status = RunStatus.claimed
            self._put(state, record)
            self._event(state, run_id, "claimed", owner)
            return record

        return self.store.update(mutate)

    def record_gate(
        self,
        run_id: str,
        name: str,
        passed: bool | None,
        detail: str,
        evidence: Iterable[str],
        *,
        status: GateStatus | str | None = None,
        applicability_basis: str | None = None,
        residual_risk: str | None = None,
    ) -> RunRecord:
        if status is None:
            if passed is None:
                raise ValueError("gate status is required")
            gate_status = GateStatus.passed if passed else GateStatus.failed
        else:
            gate_status = GateStatus(status)
            if passed is not None and passed != (gate_status == GateStatus.passed):
                raise ValueError("passed and status disagree")
        gate = GateResult(
            name=name,
            status=gate_status,
            detail=detail,
            evidence=tuple(str(item) for item in evidence),
            applicability_basis=applicability_basis,
            residual_risk=residual_risk,
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "gates", state)
            record.gates[name] = gate
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "gate", f"{name}={gate_status.value}")
            return record

        return self.store.update(mutate)

    def record_artifact(
        self, run_id: str, name: str, path: str | Path
    ) -> ArtifactReceipt:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ControlPlaneError(f"missing artifact {resolved}")
        receipt = ArtifactReceipt(
            name=name,
            path=str(resolved),
            sha256=sha256_file(resolved),
            size=resolved.stat().st_size,
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> ArtifactReceipt:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "artifacts", state)
            record.artifacts[name] = receipt
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "artifact", f"{name}:{receipt.sha256}")
            return receipt

        return self.store.update(mutate)

    def set_result_hash(self, run_id: str, result_hash: str) -> RunRecord:
        normalized = require_sha256(result_hash, "result_hash")

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "result", state)
            record.result_hash = normalized
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "result", normalized)
            return record

        return self.store.update(mutate)

    def record_outcome(
        self,
        run_id: str,
        outcome_class: OutcomeClass | str,
        detail: str,
        evidence: Iterable[str],
    ) -> RunRecord:
        outcome = OutcomeRecord(
            outcome_class=OutcomeClass(outcome_class),
            detail=detail,
            evidence=tuple(str(item) for item in evidence),
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "outcome", state)
            record.outcome = outcome
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "outcome", outcome.outcome_class.value)
            return record

        return self.store.update(mutate)

    def record_measurement(
        self,
        run_id: str,
        name: str,
        value: float,
        unit: str,
        evidence: Iterable[str],
    ) -> RunRecord:
        if not math.isfinite(float(value)):
            raise ValueError("measurement value must be finite")
        measurement = Measurement(
            name=name,
            value=float(value),
            unit=unit,
            evidence=tuple(str(item) for item in evidence),
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "measurements", state)
            record.measurements[name] = measurement
            record.status = RunStatus.running
            self._put(state, record)
            self._event(
                state, run_id, "measurement", f"{name}={value} {unit}"
            )
            return record

        return self.store.update(mutate)

    def record_residual_risk(
        self,
        run_id: str,
        name: str,
        detail: str,
        evidence: Iterable[str],
    ) -> RunRecord:
        risk = ResidualRisk(
            name=name,
            detail=detail,
            evidence=tuple(str(item) for item in evidence),
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "residual risks", state)
            record.residual_risks[name] = risk
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "residual_risk", name)
            return record

        return self.store.update(mutate)

    def verify(self, run_id: str) -> Verification:
        def mutate(state: dict[str, Any]) -> Verification:
            record = self._get(state, run_id)
            verification = self._verification_for(record)
            if record.status in {RunStatus.approved, RunStatus.submitted}:
                return verification
            self._record_verification(state, record, verification)
            return verification

        return self.store.update(mutate)

    def approve(self, run_id: str, approver: str) -> RunRecord:
        if not approver.strip():
            raise ValueError("approver is required")

        def mutate(state: dict[str, Any]) -> RunRecord | Verification:
            record = self._get(state, run_id)
            self._ensure_mutable(record, "approval", state)
            verification = self._verification_for(record)
            if not verification.passed:
                self._record_verification(state, record, verification)
                return verification
            record.status = RunStatus.approved
            record.approved_by = approver
            self._put(state, record)
            self._event(state, run_id, "verify", "PASS")
            self._event(state, run_id, "approved", approver)
            return record

        result = self.store.update(mutate)
        if isinstance(result, Verification):
            raise ControlPlaneError(
                f"run {run_id} failed verification: {result.to_dict()}"
            )
        return result

    def submit(self, run_id: str) -> RunRecord:
        def mutate(state: dict[str, Any]) -> RunRecord | Verification:
            record = self._get(state, run_id)
            if record.status != RunStatus.approved:
                raise ControlPlaneError(
                    f"run {run_id} is {record.status.value}, not approved"
                )
            verification = self._verification_for(record)
            if not verification.passed:
                self._record_verification(state, record, verification)
                return verification
            record.status = RunStatus.submitted
            record.submitted_at = utc_now()
            self._put(state, record)
            self._event(state, run_id, "submit_verify", "PASS")
            self._event(state, run_id, "submitted", record.result_hash or "")
            return record

        result = self.store.update(mutate)
        if isinstance(result, Verification):
            raise ControlPlaneError(
                f"run {run_id} changed after approval: {result.to_dict()}"
            )
        return result

    def get(self, run_id: str) -> RunRecord:
        return self._get(self.store.load(), run_id)

    def list_runs(self) -> list[RunRecord]:
        state = self.store.load()
        return [
            RunRecord.from_dict(raw) for raw in state.get("runs", {}).values()
        ]

    @staticmethod
    def _comparison_mismatches(records: list[RunRecord]) -> dict[str, list[Any]]:
        fields: dict[str, list[Any]] = {
            "task_id": [record.identity.task_id for record in records],
            "starting_commit": [
                record.identity.starting_commit for record in records
            ],
            "dataset_hash": [record.identity.dataset_hash for record in records],
            "environment_hash": [
                record.identity.environment_hash for record in records
            ],
            "requirements_hash": [
                record.identity.requirements_hash for record in records
            ],
            "required_gates": [
                sorted(record.required_gates) for record in records
            ],
            "required_artifacts": [
                sorted(record.required_artifacts) for record in records
            ],
        }
        mismatches = {
            name: values
            for name, values in fields.items()
            if any(value != values[0] for value in values[1:])
        }
        if any(
            record.identity.requirements_hash == LEGACY_REQUIREMENTS_HASH
            for record in records
        ):
            mismatches["requirements_hash"] = fields["requirements_hash"]
        return mismatches

    def compare(self, run_ids: Iterable[str]) -> dict[str, Any]:
        ids = tuple(run_ids)
        if len(ids) < 2:
            raise ValueError("compare needs at least two runs")
        if len(set(ids)) != len(ids):
            raise ValueError("compare needs distinct run ids")
        state = self.store.load()
        records = [self._get(state, run_id) for run_id in ids]
        mismatches = self._comparison_mismatches(records)
        verifications = {
            record.identity.run_id: self._verification_for(record)
            for record in records
        }
        hashes = {
            record.identity.run_id: record.result_hash for record in records
        }
        values = [value for value in hashes.values() if value]
        hard_gate_failures: dict[str, dict[str, str]] = {}
        residual_risks: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            run_id = record.identity.run_id
            hard_gate_failures[run_id] = {
                name: (
                    record.gates[name].status.value
                    if name in record.gates
                    else "missing"
                )
                for name in record.required_gates
                if name not in record.gates
                or record.gates[name].status
                in {GateStatus.failed, GateStatus.not_run}
            }
            risks = [risk.to_dict() for risk in record.residual_risks.values()]
            risks.extend(
                {
                    "name": name,
                    "detail": gate.residual_risk,
                    "evidence": list(gate.evidence),
                    "recorded_at": gate.recorded_at,
                }
                for name, gate in record.gates.items()
                if gate.status == GateStatus.not_run
            )
            residual_risks[run_id] = risks
        all_verified = all(
            verification.passed for verification in verifications.values()
        )
        matching_hashes = (
            len(values) == len(records) and len(set(values)) == 1
        )
        comparable = not mismatches
        result = {
            "run_ids": list(ids),
            "comparable": comparable,
            "identity_mismatches": mismatches,
            "matching_result_hashes": matching_hashes,
            "all_verified": all_verified,
            "result_hashes": hashes,
            "verified": {
                run_id: verification.passed
                for run_id, verification in verifications.items()
            },
            "verifications": {
                run_id: verification.to_dict()
                for run_id, verification in verifications.items()
            },
            "outcomes": {
                record.identity.run_id: (
                    record.outcome.outcome_class.value if record.outcome else None
                )
                for record in records
            },
            "hard_gate_failures": hard_gate_failures,
            "not_applicable_gates": {
                record.identity.run_id: [
                    name
                    for name, gate in record.gates.items()
                    if gate.status == GateStatus.not_applicable
                ]
                for record in records
            },
            "measurements": {
                record.identity.run_id: {
                    name: measurement.to_dict()
                    for name, measurement in record.measurements.items()
                }
                for record in records
            },
            "residual_risks": residual_risks,
        }
        result["passed"] = comparable and all_verified and matching_hashes
        return result
