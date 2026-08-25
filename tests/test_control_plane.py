from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from frontier_control_plane import ControlPlane, OwnershipConflict, RunIdentity


def identity(run_id: str, attempt: int = 1) -> RunIdentity:
    return RunIdentity(
        run_id=run_id,
        task_id="task-1",
        candidate_id="candidate-a",
        attempt=attempt,
        starting_commit="abc123",
        dataset_hash="data123",
        environment_hash="env123",
    )


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.plane = ControlPlane(self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_claim_rejects_second_owner(self) -> None:
        self.plane.register(identity("run-1"), ["tests"])
        self.plane.claim("run-1", "worker-a")
        with self.assertRaises(OwnershipConflict):
            self.plane.claim("run-1", "worker-b")

    def test_verify_fails_closed(self) -> None:
        self.plane.register(identity("run-1"), ["tests", "recovery"])
        self.plane.claim("run-1", "worker-a")
        self.plane.record_gate("run-1", "tests", True, "12 passed")
        result = self.plane.verify("run-1")
        self.assertFalse(result.passed)
        self.assertEqual(result.missing_gates, ("recovery",))
        self.assertIn("result_hash", result.missing_fields)

    def test_failed_gate_can_be_repaired_before_approval(self) -> None:
        self.plane.register(identity("run-1"), ["tests"])
        self.plane.claim("run-1", "worker-a")
        self.plane.record_gate("run-1", "tests", False, "one failure")
        self.assertFalse(self.plane.verify("run-1").passed)
        self.plane.record_gate("run-1", "tests", True, "all pass")
        self.plane.set_result_hash("run-1", "result123")
        self.plane.approve("run-1", "reviewer")
        self.plane.submit("run-1")
        self.assertEqual(self.plane.get("run-1").status.value, "submitted")

    def test_artifact_receipt_detects_content(self) -> None:
        artifact = Path(self.tmp.name) / "result.json"
        artifact.write_text('{"ok":true}\n', encoding="utf-8")
        self.plane.register(identity("run-1"), ["tests"])
        receipt = self.plane.record_artifact("run-1", "result", artifact)
        self.assertEqual(receipt.size, artifact.stat().st_size)
        self.assertEqual(len(receipt.sha256), 64)

    def test_compare_requires_matching_verified_results(self) -> None:
        for number in (1, 2):
            run_id = f"run-{number}"
            self.plane.register(identity(run_id, attempt=number), ["tests"])
            self.plane.claim(run_id, f"worker-{number}")
            self.plane.record_gate(run_id, "tests", True, "pass")
            self.plane.set_result_hash(run_id, "same-hash")
            self.plane.approve(run_id, "reviewer")
        result = self.plane.compare(["run-1", "run-2"])
        self.assertTrue(result["matching_result_hashes"])
        self.assertTrue(result["all_verified"])

    def test_atomic_store_survives_concurrent_distinct_runs(self) -> None:
        errors: list[BaseException] = []

        def add(number: int) -> None:
            try:
                self.plane.register(identity(f"run-{number}", attempt=number), ["tests"])
            except BaseException as exc:  # pragma: no cover - assertion reports details.
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(number,)) for number in range(1, 9)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.plane.list_runs()), 8)
        json.loads(self.state.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
