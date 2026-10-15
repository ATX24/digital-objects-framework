"""Pair a trace-driven evaluator with a replaceable optimizer function."""

from dataclasses import asdict
import difflib
import json
from pathlib import Path

from .contracts import DigitalObject, Evaluation, Execution, Version, text_hash, digest
from .edits import apply
from .execution import ROOT, Runner
from .storage import Store, write_json
from .traces import LocalTraces
from .execution import environment


class BamlEvaluator:
    def __init__(self, object: DigitalObject, runner: Runner):
        self.runner = runner
        self.files = {
            name: (object.root / name).read_text()
            for name in object.config["evaluation_files"]
        }
        self.version = object.objective_version

    def __call__(self, execution: Execution, case: dict, seed: int) -> Evaluation:
        if not execution.complete:
            return Evaluation(
                execution.run_id,
                None,
                failures=execution.errors or ["incomplete_trace"],
                complete=False,
                objective_version=self.version,
            )
        try:
            native = LocalTraces(
                self.runner.binary, environment(Path(execution.directory))
            ).read_run(Path(execution.directory), execution.run_id)
            request = json.loads(
                (Path(execution.directory) / "request.json").read_text()
            )
            if request["input"] != case["input"]:
                raise ValueError("Evaluation case differs from executed input")
            result, directory = self.runner.function(
                self.files,
                {
                    "case": case,
                    "submission": native["submission"],
                    "seed": seed,
                    "mode": self.runner.mode,
                    "span_names": [s["span_name"] for s in native["spans"]],
                },
                "evaluate_main",
            )
            evaluation = Evaluation(
                execution.run_id,
                result["score"],
                result["metrics"],
                result["failures"],
                [execution.trace["root_span_id"]],
                result["complete"],
                self.version,
            )
            evaluation.diagnostics = [
                {
                    "span_id": s["span_id"],
                    "function": s["span_name"],
                    "duration_ns": s["duration"],
                    "output_excerpt": json.dumps(s["output_value"], ensure_ascii=False)[
                        :900
                    ],
                }
                for s in native["spans"]
                if ".harness." in s["span_name"]
                and s["output_value"] is not None
                and not s["span_name"].endswith("agent_record")
            ][:10]
            write_json(directory / "evaluation.json", asdict(evaluation))
            return evaluation
        except Exception as error:
            return Evaluation(
                execution.run_id,
                None,
                failures=[str(error)],
                complete=False,
                objective_version=self.version,
            )


class BamlOptimizer:
    def __init__(self, object: DigitalObject, runner: Runner):
        self.object, self.runner = object, runner

    def __call__(
        self, source: Version, feedback: list[Evaluation], history: list[dict]
    ) -> dict:
        context = {
            "objective": self.object.config["objective"],
            "parent_hash": source.hash,
            "files": source.files,
            "file_hashes": {n: text_hash(t) for n, t in source.files.items()},
            "evaluation": [asdict(e) for e in feedback],
            "history": history[-6:],
        }
        if self.runner.mode == "fixture":
            name = self.object.config.get("fixture_optimizer")
            if not name:
                return {
                    "parent_hash": source.hash,
                    "no_change": True,
                    "edits": [],
                    "hypothesis": "No scripted optimizer configured",
                    "expected_benefit": "",
                    "risks": [],
                }
            proposal = json.loads((self.object.root / name).read_text())
            proposal["parent_hash"] = source.hash
            for edit in proposal["edits"]:
                content = source.files.get(edit["path"], "")
                if content.count(edit["search"]) != 1:
                    proposal.update(no_change=True, edits=[])
                    break
                edit["expected_hash"] = text_hash(content)
            replies = [proposal]
        else:
            replies = []
        files = {
            "baml_src/" + name: (ROOT / "baml_src" / name).read_text()
            for name in ["proposer.prompt.baml", "main.baml"]
        }
        proposal, _ = self.runner.function(
            files,
            context,
            "optimize",
            replies,
            self.object.config["models"]["optimizer"],
        )
        return proposal


def comparison(
    parent: list[Evaluation], candidate: list[Evaluation], threshold: float
) -> dict:
    complete = (
        bool(parent)
        and len(parent) == len(candidate)
        and all(e.valid for e in parent + candidate)
    )
    if not complete:
        return {
            "retain": False,
            "reason": "invalid_or_incomplete_comparison",
            "delta": None,
        }
    baseline = sum(e.score for e in parent) / len(parent)
    proposed = sum(e.score for e in candidate) / len(candidate)
    return {
        "retain": proposed - baseline >= threshold,
        "parent_score": baseline,
        "candidate_score": proposed,
        "delta": proposed - baseline,
        "reason": "improved" if proposed - baseline >= threshold else "not_improved",
    }


def source_diff(parent: Version, candidate: Version) -> str:
    return "".join(
        line
        for name in sorted(set(parent.files) | set(candidate.files))
        for line in difflib.unified_diff(
            parent.files.get(name, "").splitlines(True),
            candidate.files.get(name, "").splitlines(True),
            fromfile="parent/" + name,
            tofile="candidate/" + name,
        )
    )


class Campaign:
    def __init__(self, object: DigitalObject, runner: Runner, store: Store):
        self.object, self.runner, self.store = object, runner, store
        self.evaluator = object.evaluator or BamlEvaluator(object, runner)
        self.optimizer = object.optimizer or BamlOptimizer(object, runner)
        self.objective_version = object.objective_version
        self.cases = {
            split: object.cases(split) for split in ["feedback", "selection", "audit"]
        }

    def evaluate(self, version: Version, split: str, seed: int) -> list[Evaluation]:
        output = []
        for frozen in self.cases[split]:
            case = json.loads(json.dumps(frozen))
            execution = self.runner.execute(
                version, case, split, self.object.config["models"]["solver"]
            )
            output.append(self.evaluator(execution, case, seed))
        return output

    def evolve(self, rounds: int | None = None, resume: bool = False) -> dict:
        parent = self.store.retained(self.object.source())
        self.store.save(parent)
        results = []
        failures = 0
        maximum = (
            rounds if rounds is not None else self.object.config["limits"]["rounds"]
        )
        if maximum < 1:
            raise ValueError("Rounds must be positive")
        identity = digest(
            {
                "objective": self.objective_version,
                "cases": self.cases,
                "config": self.object.config,
                "mode": self.runner.mode,
            }
        )
        checkpoint = self.store.root / "campaign-state.json"
        budget_file = self.store.root / "budget.json"
        if resume:
            saved = json.loads(checkpoint.read_text())
            if saved["identity"] != identity:
                raise ValueError(
                    "Cannot resume after cases, evaluator, mode, or configuration change"
                )
            parent = self.store.load(saved["parent"])
            results, failures = saved["results"], saved["failures"]
            if budget_file.exists():
                self.runner.budget.used = json.loads(budget_file.read_text())["used"]
        self.runner.budget.path = budget_file
        write_json(
            budget_file,
            {"used": self.runner.budget.used, "limit": self.runner.budget.limit},
        )
        write_json(
            checkpoint,
            {
                "identity": identity,
                "parent": parent.hash,
                "results": results,
                "failures": failures,
            },
        )
        seeds = self.object.config.get("seed_panels", [1, 7])
        completed = sum("panels" in result for result in results)
        for _ in range(completed, maximum):
            if self.object.objective_version != self.objective_version:
                raise RuntimeError("Evaluator changed during the campaign")
            feedback = self.evaluate(parent, "feedback", seeds[0])
            if not all(e.complete for e in feedback):
                results.append(
                    {
                        "reason": "feedback_incomplete",
                        "feedback": [asdict(e) for e in feedback],
                    }
                )
                break
            # Only compact dispositions cross from selection into proposal context.
            history = [
                {k: h.get(k) for k in ["parent", "candidate", "reason", "delta"]}
                for h in self.store.history()
            ]
            try:
                proposal = self.optimizer(parent, feedback, history)
                if proposal.get("no_change"):
                    results.append({"reason": "optimizer_no_change"})
                    break
                candidate = apply(parent, proposal, self.object.config["mutable"])
                self.store.save(candidate)
            except Exception as error:
                results.append({"reason": "invalid_proposal", "error": str(error)})
                break
            panels = []
            for seed in seeds:
                baseline = self.evaluate(parent, "selection", seed)
                trial = self.evaluate(candidate, "selection", seed)
                panel = comparison(
                    baseline,
                    trial,
                    self.object.config["objective"]["improvement_threshold"],
                )
                panel.update(
                    seed=seed,
                    parent=[asdict(e) for e in baseline],
                    candidate=[asdict(e) for e in trial],
                )
                panels.append(panel)
                if not panel["retain"]:
                    break
            retained = len(panels) == len(seeds) and all(p["retain"] for p in panels)
            result = {
                "parent": parent.hash,
                "candidate": candidate.hash,
                "proposal": proposal,
                "diff": source_diff(parent, candidate),
                "panels": panels,
                "retained": retained,
                "reason": "retained" if retained else panels[-1]["reason"],
                "delta": panels[-1]["delta"],
                "objective_version": self.objective_version,
                "fresh_calls": self.runner.budget.used,
                "cache_hits": self.runner.budget.hits,
            }
            self.store.append(result)
            results.append(result)
            if retained:
                self.store.retain(candidate)
                parent, failures = candidate, 0
            else:
                failures += 1
            write_json(
                checkpoint,
                {
                    "identity": identity,
                    "parent": parent.hash,
                    "results": results,
                    "failures": failures,
                },
            )
            if failures >= 2 or self.runner.budget.used >= self.runner.budget.limit:
                break
        report = {
            "retained": parent.hash,
            "results": results,
            "mode": self.runner.mode,
            "fresh_calls": self.runner.budget.used,
            "objective_version": self.objective_version,
        }
        write_json(self.store.root / "campaign.json", report)
        return report

    def audit(self) -> dict:
        version = self.store.retained(self.object.source())
        result = {
            "frozen_version": version.hash,
            "objective_version": self.objective_version,
            "evaluations": [asdict(e) for e in self.evaluate(version, "audit", 31)],
        }
        write_json(self.store.root / "audit.json", result)
        return result
