"""Fail-closed run lifecycle and evidence ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .hashing import sha256_file
from .models import (
    ArtifactReceipt,
    GateResult,
    RunIdentity,
    RunRecord,
    RunStatus,
    Verification,
)
from .store import AtomicJsonStore


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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

    def register(
        self,
        identity: RunIdentity,
        required_gates: Iterable[str],
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        required = tuple(dict.fromkeys(str(item).strip() for item in required_gates if str(item).strip()))
        if not required:
            raise ValueError("at least one required gate is needed")

        def mutate(state: dict[str, Any]) -> RunRecord:
            existing = state.setdefault("runs", {}).get(identity.run_id)
            if existing:
                record = RunRecord.from_dict(existing)
                if record.identity != identity or record.required_gates != required:
                    raise ControlPlaneError(f"run id collision for {identity.run_id}")
                return record
            now = utc_now()
            record = RunRecord(
                identity=identity,
                required_gates=required,
                metadata=dict(metadata or {}),
                created_at=now,
                updated_at=now,
            )
            self._put(state, record)
            self._event(state, identity.run_id, "registered", f"required={','.join(required)}")
            return record

        return self.store.update(mutate)

    def claim(self, run_id: str, owner: str) -> RunRecord:
        if not owner.strip():
            raise ValueError("owner is required")

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            if record.owner and record.owner != owner:
                raise OwnershipConflict(f"{run_id} already owned by {record.owner}")
            if record.status in {RunStatus.approved, RunStatus.submitted}:
                raise ControlPlaneError(f"cannot claim {run_id} in {record.status.value}")
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
        passed: bool,
        detail: str,
        evidence: Iterable[str] = (),
    ) -> RunRecord:
        gate = GateResult(
            name=name,
            passed=passed,
            detail=detail,
            evidence=tuple(str(item) for item in evidence),
            recorded_at=utc_now(),
        )

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            if record.status in {RunStatus.approved, RunStatus.submitted}:
                raise ControlPlaneError(f"cannot change gates in {record.status.value}")
            record.gates[name] = gate
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "gate", f"{name}={'PASS' if passed else 'FAIL'}")
            return record

        return self.store.update(mutate)

    def record_artifact(self, run_id: str, name: str, path: str | Path) -> ArtifactReceipt:
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
            if record.status in {RunStatus.approved, RunStatus.submitted}:
                raise ControlPlaneError(f"cannot change artifacts in {record.status.value}")
            record.artifacts[name] = receipt
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "artifact", f"{name}:{receipt.sha256}")
            return receipt

        return self.store.update(mutate)

    def set_result_hash(self, run_id: str, result_hash: str) -> RunRecord:
        if not result_hash.strip():
            raise ValueError("result hash is required")

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            if record.status in {RunStatus.approved, RunStatus.submitted}:
                raise ControlPlaneError(f"cannot change result in {record.status.value}")
            record.result_hash = result_hash
            record.status = RunStatus.running
            self._put(state, record)
            self._event(state, run_id, "result", result_hash)
            return record

        return self.store.update(mutate)

    def verify(self, run_id: str) -> Verification:
        def mutate(state: dict[str, Any]) -> Verification:
            record = self._get(state, run_id)
            missing = tuple(name for name in record.required_gates if name not in record.gates)
            failed = tuple(
                name
                for name in record.required_gates
                if name in record.gates and not record.gates[name].passed
            )
            missing_fields = []
            if not record.result_hash:
                missing_fields.append("result_hash")
            if not record.owner:
                missing_fields.append("owner")
            passed = not missing and not failed and not missing_fields
            record.status = RunStatus.verified if passed else RunStatus.failed
            self._put(state, record)
            detail = (
                "PASS"
                if passed
                else f"missing={','.join(missing)} failed={','.join(failed)} fields={','.join(missing_fields)}"
            )
            self._event(state, run_id, "verify", detail)
            return Verification(
                run_id=run_id,
                passed=passed,
                missing_gates=missing,
                failed_gates=failed,
                missing_fields=tuple(missing_fields),
            )

        return self.store.update(mutate)

    def approve(self, run_id: str, approver: str) -> RunRecord:
        verification = self.verify(run_id)
        if not verification.passed:
            raise ControlPlaneError(f"run {run_id} failed verification: {verification.to_dict()}")

        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            record.status = RunStatus.approved
            record.approved_by = approver
            self._put(state, record)
            self._event(state, run_id, "approved", approver)
            return record

        return self.store.update(mutate)

    def submit(self, run_id: str) -> RunRecord:
        def mutate(state: dict[str, Any]) -> RunRecord:
            record = self._get(state, run_id)
            if record.status != RunStatus.approved:
                raise ControlPlaneError(f"run {run_id} is {record.status.value}, not approved")
            record.status = RunStatus.submitted
            record.submitted_at = utc_now()
            self._put(state, record)
            self._event(state, run_id, "submitted", record.result_hash or "")
            return record

        return self.store.update(mutate)

    def get(self, run_id: str) -> RunRecord:
        return self._get(self.store.load(), run_id)

    def list_runs(self) -> list[RunRecord]:
        state = self.store.load()
        return [RunRecord.from_dict(raw) for raw in state.get("runs", {}).values()]

    def compare(self, run_ids: Iterable[str]) -> dict[str, Any]:
        ids = tuple(run_ids)
        if len(ids) < 2:
            raise ValueError("compare needs at least two runs")
        records = [self.get(run_id) for run_id in ids]
        hashes = {record.identity.run_id: record.result_hash for record in records}
        verified = {
            record.identity.run_id: record.status in {RunStatus.verified, RunStatus.approved, RunStatus.submitted}
            for record in records
        }
        values = [value for value in hashes.values() if value]
        return {
            "run_ids": list(ids),
            "matching_result_hashes": len(values) == len(records) and len(set(values)) == 1,
            "all_verified": all(verified.values()),
            "result_hashes": hashes,
            "verified": verified,
        }
