"""Command-line interface for the reusable control plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .control_plane import ControlPlane
from .models import GateStatus, OutcomeClass, RunIdentity


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
    register.add_argument("--requirements-hash", required=True)
    register.add_argument("--gate", action="append", required=True)
    register.add_argument("--artifact-name", action="append", default=[])
    register.add_argument("--retry-of")

    claim = sub.add_parser("claim")
    claim.add_argument("run_id")
    claim.add_argument("--owner", required=True)

    gate = sub.add_parser("gate")
    gate.add_argument("run_id")
    gate.add_argument("name")
    gate.add_argument("--passed", action=argparse.BooleanOptionalAction)
    gate.add_argument("--status", choices=[item.value for item in GateStatus])
    gate.add_argument("--detail", required=True)
    gate.add_argument("--evidence", action="append", required=True)
    gate.add_argument("--applicability-basis")
    gate.add_argument("--residual-risk")

    artifact = sub.add_parser("artifact")
    artifact.add_argument("run_id")
    artifact.add_argument("name")
    artifact.add_argument("path", type=Path)

    result = sub.add_parser("result")
    result.add_argument("run_id")
    result.add_argument("sha256")

    outcome = sub.add_parser("outcome")
    outcome.add_argument("run_id")
    outcome.add_argument(
        "outcome_class", choices=[item.value for item in OutcomeClass]
    )
    outcome.add_argument("--detail", required=True)
    outcome.add_argument("--evidence", action="append", required=True)

    measure = sub.add_parser("measure")
    measure.add_argument("run_id")
    measure.add_argument("name")
    measure.add_argument("value", type=float)
    measure.add_argument("--unit", required=True)
    measure.add_argument("--evidence", action="append", required=True)

    risk = sub.add_parser("risk")
    risk.add_argument("run_id")
    risk.add_argument("name")
    risk.add_argument("--detail", required=True)
    risk.add_argument("--evidence", action="append", required=True)

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
                    requirements_hash=args.requirements_hash,
                ),
                args.gate,
                {"retry_of": args.retry_of} if args.retry_of else None,
                args.artifact_name or ("result",),
            )
        )
    elif args.command == "claim":
        emit(plane.claim(args.run_id, args.owner))
    elif args.command == "gate":
        if args.passed is None and args.status is None:
            raise SystemExit("gate requires --status or --passed/--no-passed")
        emit(
            plane.record_gate(
                args.run_id,
                args.name,
                args.passed,
                args.detail,
                args.evidence,
                status=args.status,
                applicability_basis=args.applicability_basis,
                residual_risk=args.residual_risk,
            )
        )
    elif args.command == "artifact":
        emit(plane.record_artifact(args.run_id, args.name, args.path))
    elif args.command == "result":
        emit(plane.set_result_hash(args.run_id, args.sha256))
    elif args.command == "outcome":
        emit(
            plane.record_outcome(
                args.run_id, args.outcome_class, args.detail, args.evidence
            )
        )
    elif args.command == "measure":
        emit(
            plane.record_measurement(
                args.run_id, args.name, args.value, args.unit, args.evidence
            )
        )
    elif args.command == "risk":
        emit(
            plane.record_residual_risk(
                args.run_id, args.name, args.detail, args.evidence
            )
        )
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
        return 0 if result["passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
