"""Command-line interface for the reusable control plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .control_plane import ControlPlane
from .models import RunIdentity


def emit(value) -> None:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("run_id")
    register.add_argument("--task", required=True)
    register.add_argument("--candidate", required=True)
    register.add_argument("--attempt", type=int, default=1)
    register.add_argument("--commit", required=True)
    register.add_argument("--dataset-hash", required=True)
    register.add_argument("--environment-hash", required=True)
    register.add_argument("--gate", action="append", required=True)

    claim = sub.add_parser("claim")
    claim.add_argument("run_id")
    claim.add_argument("--owner", required=True)

    gate = sub.add_parser("gate")
    gate.add_argument("run_id")
    gate.add_argument("name")
    gate.add_argument("--passed", action=argparse.BooleanOptionalAction, required=True)
    gate.add_argument("--detail", required=True)
    gate.add_argument("--evidence", action="append", default=[])

    artifact = sub.add_parser("artifact")
    artifact.add_argument("run_id")
    artifact.add_argument("name")
    artifact.add_argument("path", type=Path)

    result = sub.add_parser("result")
    result.add_argument("run_id")
    result.add_argument("sha256")

    verify = sub.add_parser("verify")
    verify.add_argument("run_id")

    approve = sub.add_parser("approve")
    approve.add_argument("run_id")
    approve.add_argument("--by", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("run_id")

    status = sub.add_parser("status")
    status.add_argument("run_id", nargs="?")

    compare = sub.add_parser("compare")
    compare.add_argument("run_ids", nargs="+")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    plane = ControlPlane(args.state)
    if args.command == "register":
        emit(
            plane.register(
                RunIdentity(
                    run_id=args.run_id,
                    task_id=args.task,
                    candidate_id=args.candidate,
                    attempt=args.attempt,
                    starting_commit=args.commit,
                    dataset_hash=args.dataset_hash,
                    environment_hash=args.environment_hash,
                ),
                args.gate,
            )
        )
    elif args.command == "claim":
        emit(plane.claim(args.run_id, args.owner))
    elif args.command == "gate":
        emit(plane.record_gate(args.run_id, args.name, args.passed, args.detail, args.evidence))
    elif args.command == "artifact":
        emit(plane.record_artifact(args.run_id, args.name, args.path))
    elif args.command == "result":
        emit(plane.set_result_hash(args.run_id, args.sha256))
    elif args.command == "verify":
        result = plane.verify(args.run_id)
        emit(result)
        return 0 if result.passed else 1
    elif args.command == "approve":
        emit(plane.approve(args.run_id, args.by))
    elif args.command == "submit":
        emit(plane.submit(args.run_id))
    elif args.command == "status":
        emit(plane.get(args.run_id) if args.run_id else [run.to_dict() for run in plane.list_runs()])
    elif args.command == "compare":
        result = plane.compare(args.run_ids)
        emit(result)
        return 0 if result["matching_result_hashes"] and result["all_verified"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
