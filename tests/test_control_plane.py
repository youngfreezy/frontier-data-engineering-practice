from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from frontier_control_plane import (
    ControlPlane,
    ControlPlaneError,
    GateResult,
    GateStatus,
    OwnershipConflict,
    RunIdentity,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
BASELINE_GATES = ("clean_checkout", "unit_tests")


def identity(
    run_id: str, attempt: int = 1, **overrides: str
) -> RunIdentity:
    values = {
        "run_id": run_id,
        "task_id": "task-1",
        "candidate_id": "candidate-a",
        "attempt": attempt,
        "starting_commit": "1" * 40,
        "dataset_hash": SHA_A,
        "environment_hash": SHA_B,
        "requirements_hash": SHA_C,
    }
    values.update(overrides)
    return RunIdentity(**values)


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state.json"
        self.plane = ControlPlane(self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_artifact(self, run_id: str, content: str = '{"ok":true}\n') -> Path:
        artifact = self.root / f"{run_id}-result.json"
        artifact.write_text(content, encoding="utf-8")
        return artifact

    def pass_gate(self, run_id: str, name: str) -> None:
        self.plane.record_gate(
            run_id,
            name,
            True,
            f"{name} passed",
            [f"command:{name}"],
        )

    def prepare_solved(
        self,
        run_id: str,
        *,
        run_identity: RunIdentity | None = None,
        gates: tuple[str, ...] = BASELINE_GATES,
        required_artifacts: tuple[str, ...] = ("result",),
    ) -> Path:
        self.plane.register(
            run_identity or identity(run_id),
            gates,
            required_artifacts=required_artifacts,
        )
        self.plane.claim(run_id, f"owner-{run_id}")
        for gate in gates:
            self.pass_gate(run_id, gate)
        artifact = self.write_artifact(run_id)
        self.plane.record_artifact(run_id, "result", artifact)
        self.plane.set_result_hash(run_id, SHA_D)
        self.plane.record_outcome(
            run_id,
            "solved",
            "all required work completed normally",
            [str(artifact)],
        )
        return artifact

    def test_register_requires_baseline_gates(self) -> None:
        with self.assertRaisesRegex(ValueError, "clean_checkout"):
            self.plane.register(identity("run-1"), ["unit_tests"])

    def test_claim_rejects_second_owner(self) -> None:
        self.plane.register(identity("run-1"), BASELINE_GATES)
        self.plane.claim("run-1", "worker-a")
        with self.assertRaises(OwnershipConflict):
            self.plane.claim("run-1", "worker-b")

    def test_verify_fails_closed_on_missing_gate_artifact_result_and_outcome(self) -> None:
        self.plane.register(identity("run-1"), BASELINE_GATES)
        self.plane.claim("run-1", "worker-a")
        self.pass_gate("run-1", "clean_checkout")
        result = self.plane.verify("run-1")
        self.assertFalse(result.passed)
        self.assertEqual(result.missing_gates, ("unit_tests",))
        self.assertEqual(result.missing_artifacts, ("result",))
        self.assertIn("result_hash", result.missing_fields)
        self.assertIn("outcome", result.missing_fields)

    def test_gate_requires_specific_evidence(self) -> None:
        self.plane.register(identity("run-1"), BASELINE_GATES)
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.plane.record_gate("run-1", "unit_tests", True, "pass", [])

    def test_not_run_blocks_but_quoted_not_applicable_can_satisfy_gate(self) -> None:
        gates = (*BASELINE_GATES, "delivery_semantics")
        self.plane.register(identity("run-1"), gates)
        self.plane.claim("run-1", "worker-a")
        for gate in BASELINE_GATES:
            self.pass_gate("run-1", gate)
        self.plane.record_gate(
            "run-1",
            "delivery_semantics",
            None,
            "the broker runtime was unavailable",
            ["runtime inventory: broker absent"],
            status="not_run",
            residual_risk="delivery behavior under redelivery remains unverified",
        )
        artifact = self.write_artifact("run-1")
        self.plane.record_artifact("run-1", "result", artifact)
        self.plane.set_result_hash("run-1", SHA_D)
        self.plane.record_outcome("run-1", "solved", "batch work completed", [str(artifact)])
        blocked = self.plane.verify("run-1")
        self.assertEqual(blocked.not_run_gates, ("delivery_semantics",))
        self.assertFalse(blocked.passed)

        self.plane.record_gate(
            "run-1",
            "delivery_semantics",
            None,
            "streaming is outside this batch-only task",
            ['task contract: "Input is a bounded batch file."'],
            status="not_applicable",
            applicability_basis='"Input is a bounded batch file."',
        )
        repaired = self.plane.verify("run-1")
        self.assertTrue(repaired.passed)
        self.assertEqual(repaired.not_applicable_gates, ("delivery_semantics",))

    def test_failed_gate_can_be_repaired_before_approval(self) -> None:
        artifact = self.prepare_solved("run-1")
        self.plane.record_gate(
            "run-1", "unit_tests", False, "one failure", ["pytest: 1 failed"]
        )
        self.assertFalse(self.plane.verify("run-1").passed)
        self.pass_gate("run-1", "unit_tests")
        self.plane.record_artifact("run-1", "result", artifact)
        self.plane.approve("run-1", "reviewer")
        self.plane.submit("run-1")
        self.assertEqual(self.plane.get("run-1").status.value, "submitted")

    def test_approval_rehashes_artifacts_and_submit_rechecks_them(self) -> None:
        artifact = self.prepare_solved("run-1")
        artifact.write_text('{"changed":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(ControlPlaneError, "stale_artifacts"):
            self.plane.approve("run-1", "reviewer")
        self.assertEqual(self.plane.get("run-1").status.value, "failed")

        self.plane.record_artifact("run-1", "result", artifact)
        self.plane.approve("run-1", "reviewer")
        artifact.write_text('{"changed_again":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(ControlPlaneError, "changed after approval"):
            self.plane.submit("run-1")
        self.assertEqual(self.plane.get("run-1").status.value, "failed")

    def test_required_artifact_names_fail_closed(self) -> None:
        self.prepare_solved(
            "run-1", required_artifacts=("result", "test_log")
        )
        result = self.plane.verify("run-1")
        self.assertEqual(result.missing_artifacts, ("test_log",))

    def test_non_semantic_outcome_is_typed_and_blocks_approval(self) -> None:
        self.prepare_solved("run-1")
        self.plane.record_outcome(
            "run-1",
            "infrastructure",
            "object storage was unavailable",
            ["runner.log: connection refused"],
        )
        result = self.plane.verify("run-1")
        self.assertEqual(result.blocking_outcome, "infrastructure")
        self.assertFalse(result.passed)

    def test_non_semantic_failure_allows_exactly_one_linked_clean_retry(self) -> None:
        self.plane.register(identity("run-1"), BASELINE_GATES)
        self.plane.record_outcome(
            "run-1",
            "timeout",
            "the runner exceeded its time budget",
            ["runner.log: deadline exceeded"],
        )
        retry_identity = identity("run-2", attempt=2)
        retry = self.plane.register(
            retry_identity,
            BASELINE_GATES,
            {"retry_of": "run-1"},
        )
        self.assertEqual(retry.metadata["retry_of"], "run-1")
        with self.assertRaisesRegex(ControlPlaneError, "clean retry was registered"):
            self.plane.record_outcome(
                "run-1",
                "solved",
                "attempted history rewrite",
                ["late summary"],
            )
        with self.assertRaisesRegex(ControlPlaneError, "already has a clean retry"):
            self.plane.register(
                identity("run-3", attempt=3),
                BASELINE_GATES,
                {"retry_of": "run-1"},
            )
        self.plane.record_outcome(
            "run-2",
            "infrastructure",
            "the retry runner lost storage",
            ["runner.log: storage unavailable"],
        )
        with self.assertRaisesRegex(ControlPlaneError, "cannot be retried again"):
            self.plane.register(
                identity("run-3", attempt=3),
                BASELINE_GATES,
                {"retry_of": "run-2"},
            )

    def test_result_hash_must_be_sha256(self) -> None:
        self.plane.register(identity("run-1"), BASELINE_GATES)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.plane.set_result_hash("run-1", "not-a-digest")

    def test_compare_requires_matching_identity_and_evaluation_contract(self) -> None:
        self.prepare_solved("run-1", run_identity=identity("run-1"))
        self.prepare_solved(
            "run-2",
            run_identity=identity("run-2", attempt=2, dataset_hash=SHA_D),
        )
        result = self.plane.compare(["run-1", "run-2"])
        self.assertFalse(result["comparable"])
        self.assertFalse(result["passed"])
        self.assertIn("dataset_hash", result["identity_mismatches"])

    def test_compare_surfaces_measurements_risks_and_gate_results(self) -> None:
        for number in (1, 2):
            run_id = f"run-{number}"
            self.prepare_solved(
                run_id, run_identity=identity(run_id, attempt=number)
            )
            self.plane.record_measurement(
                run_id,
                "elapsed",
                1.5 + number,
                "seconds",
                [f"{run_id}-timing.json"],
            )
            self.plane.record_residual_risk(
                run_id,
                "cost_sample",
                "cost was measured on a short sample",
                [f"{run_id}-billing.json"],
            )
            self.plane.approve(run_id, "reviewer")
        result = self.plane.compare(["run-1", "run-2"])
        self.assertTrue(result["comparable"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["hard_gate_failures"]["run-1"], {})
        self.assertEqual(
            result["measurements"]["run-1"]["elapsed"]["unit"], "seconds"
        )
        self.assertEqual(
            result["residual_risks"]["run-2"][0]["name"], "cost_sample"
        )

    def test_verify_does_not_reopen_approved_or_submitted_run(self) -> None:
        self.prepare_solved("run-1")
        self.plane.approve("run-1", "reviewer")
        self.assertTrue(self.plane.verify("run-1").passed)
        self.assertEqual(self.plane.get("run-1").status.value, "approved")
        self.plane.submit("run-1")
        self.assertTrue(self.plane.verify("run-1").passed)
        self.assertEqual(self.plane.get("run-1").status.value, "submitted")

    def test_legacy_boolean_gate_records_remain_readable(self) -> None:
        gate = GateResult.from_dict(
            {"name": "unit_tests", "passed": True, "detail": "legacy pass"}
        )
        self.assertEqual(gate.status, GateStatus.passed)
        self.assertTrue(gate.passed)

    def test_atomic_store_survives_concurrent_distinct_runs(self) -> None:
        errors: list[BaseException] = []

        def add(number: int) -> None:
            try:
                self.plane.register(
                    identity(f"run-{number}", attempt=number), BASELINE_GATES
                )
            except BaseException as exc:  # pragma: no cover - assertion reports details.
                errors.append(exc)

        threads = [
            threading.Thread(target=add, args=(number,))
            for number in range(1, 9)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.plane.list_runs()), 8)
        json.loads(self.state.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
