from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / ".cursor" / "skills" / "frontier-data-engineering" / "scripts" / "control_plane.py"
DATASET_HASH = "a" * 64
ENVIRONMENT_HASH = "b" * 64
REQUIREMENTS_HASH = "c" * 64
RESULT_HASH = "d" * 64


def invoke(state: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), "--state", str(state), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_skill_wrapper_runs_two_full_lifecycles_and_compares_results() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "control-plane.json"
        artifact = root / "result.json"
        artifact.write_text('{"ok":true}\n', encoding="utf-8")

        for attempt in (1, 2):
            run_id = f"skill-e2e-{attempt}"
            invoke(
                state,
                "register",
                run_id,
                "--task",
                "control-plane-smoke",
                "--candidate",
                "candidate-a",
                "--attempt",
                str(attempt),
                "--commit",
                "1" * 40,
                "--dataset-hash",
                DATASET_HASH,
                "--environment-hash",
                ENVIRONMENT_HASH,
                "--requirements-hash",
                REQUIREMENTS_HASH,
                "--gate",
                "clean_checkout",
                "--gate",
                "unit_tests",
                "--gate",
                "recovery",
            )
            invoke(state, "claim", run_id, "--owner", f"worker-{attempt}")
            invoke(
                state,
                "gate",
                run_id,
                "clean_checkout",
                "--passed",
                "--detail",
                "worktree was clean",
                "--evidence",
                "git status --porcelain returned empty",
            )
            invoke(
                state,
                "gate",
                run_id,
                "unit_tests",
                "--passed",
                "--detail",
                "pipeline tests passed",
                "--evidence",
                "pytest: all tests passed",
            )
            invoke(
                state,
                "gate",
                run_id,
                "recovery",
                "--passed",
                "--detail",
                "rollback and retry passed",
                "--evidence",
                "recovery fixture completed without duplicates",
            )
            invoke(state, "artifact", run_id, "result", str(artifact))
            invoke(state, "result", run_id, RESULT_HASH)
            invoke(
                state,
                "outcome",
                run_id,
                "solved",
                "--detail",
                "the run completed normally",
                "--evidence",
                str(artifact),
            )
            assert invoke(state, "verify", run_id)["passed"] is True
            invoke(state, "approve", run_id, "--by", "smoke-reviewer")
            assert invoke(state, "submit", run_id)["status"] == "submitted"

        comparison = invoke(state, "compare", "skill-e2e-1", "skill-e2e-2")
        assert comparison["matching_result_hashes"] is True
        assert comparison["all_verified"] is True
        assert comparison["comparable"] is True
        assert comparison["passed"] is True
