"""Small CLI for the reusable learning loop."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .clients import Budget
from .contracts import DigitalObject, Execution
from .execution import Runner
from .learning import BamlEvaluator, Campaign
from .memory import GitMemory
from .report import render
from .storage import Store, write_json


def parser():
    result = argparse.ArgumentParser(
        description="Run and improve a BAML digital object"
    )
    result.add_argument(
        "command",
        choices=[
            "run",
            "evaluate",
            "evolve",
            "audit",
            "rollback",
            "inspect",
            "dream",
            "capabilities",
        ],
    )
    result.add_argument("--object", required=True, type=Path)
    result.add_argument("--state", type=Path)
    result.add_argument(
        "--mode", choices=["fixture", "replay", "explore"], default="fixture"
    )
    result.add_argument("--case", type=Path)
    result.add_argument("--run-id")
    result.add_argument("--version")
    result.add_argument("--rounds", type=int)
    result.add_argument("--max-calls", type=int)
    result.add_argument("--commit-memory", action="store_true")
    result.add_argument("--resume", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    object = DigitalObject.load(args.object)
    state = (args.state or object.root / ".digital-object").resolve()
    store = Store(state)
    budget = Budget(
        args.max_calls
        if args.max_calls is not None
        else object.config["limits"]["fresh_calls"]
    )
    if budget.limit < 0:
        raise ValueError("Call budget cannot be negative")
    runner = Runner(state, budget, args.mode)
    if args.command == "capabilities":
        print(
            json.dumps(
                {
                    "baml": runner.binary,
                    "traces": "local BTEL via baml query",
                    "bcs": "wire adapter available; deployment not configured or verified",
                    "publication": "recommendations only",
                    "mode": args.mode,
                },
                indent=2,
            )
        )
        return
    if args.command == "rollback":
        if not args.version:
            raise ValueError("--version is required")
        store.retain(store.load(args.version))
        print(args.version)
        return
    if args.command == "inspect":
        report = json.loads((state / "campaign.json").read_text())
        print(render(report, state / "report.html"))
        return
    if args.command in ["evolve", "audit"]:
        campaign = Campaign(object, runner, store)
        report = (
            campaign.evolve(args.rounds, args.resume)
            if args.command == "evolve"
            else campaign.audit()
        )
        if args.command == "evolve":
            report["report"] = str(render(report, state / "report.html"))
        print(json.dumps(report, indent=2))
        return
    case = (
        json.loads(args.case.read_text()) if args.case else object.cases("feedback")[0]
    )
    memory_store = None
    if args.commit_memory:
        if args.mode == "fixture" or args.command == "evaluate":
            raise ValueError("Fixture/evaluation runs cannot commit live memory")
        memory_store = GitMemory(object.root / "memory")
        memory_store.initialize()
        parent, files = memory_store.snapshot()
        metadata = json.loads(
            files.pop("state.json", '{"last_dream_at":0,"experience_cursor":0}')
        )
        case["input"]["memory"].update(notes=files, revision=parent, **metadata)
    if args.command == "dream":
        case["input"]["manual_dream"] = True
    if args.command == "evaluate":
        if not args.run_id or not args.run_id.isalnum():
            raise ValueError("--run-id is required")
        execution = Execution(
            **json.loads((state / "runs" / args.run_id / "execution.json").read_text())
        )
    else:
        version = store.retained(object.source())
        store.save(version)
        execution = runner.execute(
            version, case, "feedback", object.config["models"]["solver"]
        )
    evaluation = BamlEvaluator(object, runner)(execution, case, 1)
    result = {"execution": asdict(execution), "evaluation": asdict(evaluation)}
    if execution.complete and evaluation.valid and object.config.get("export_files"):
        submission = execution.submission
        files = {
            name: (object.root / name).read_text()
            for name in object.config["export_files"]
        }
        package, _ = runner.function(
            files,
            {
                "case": case,
                "submission": submission,
                "run_id": execution.run_id,
                "source_version": execution.version,
            },
            "export_main",
        )
        destination = state / "exports" / f"{execution.run_id}.json"
        write_json(destination, package)
        result["recommendations"] = str(destination)
        if memory_store is not None and evaluation.valid:
            memory = submission["memory"]
            files = dict(memory["notes"])
            files["state.json"] = json.dumps(
                {
                    k: memory[k]
                    for k in [
                        "last_dream_at",
                        "experience_cursor",
                        "pending_experience",
                        "seen_experiences",
                    ]
                }
            )
            result["memory_revision"] = memory_store.commit(memory["revision"], files)
    print(json.dumps(result, indent=2))
    if not execution.complete or not evaluation.valid:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
