"""The small, task-independent learning contract."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import math


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Version:
    files: dict[str, str]
    parent: str | None = None

    @property
    def hash(self) -> str:
        return digest(self.files)


@dataclass
class Execution:
    run_id: str
    version: str
    case_id: str
    split: str
    directory: str
    submission: dict | None = None
    trace: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (
            self.submission is not None
            and not self.errors
            and self.trace.get("complete", False)
        )


@dataclass
class Evaluation:
    run_id: str
    score: float | None
    metrics: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    complete: bool = True
    objective_version: str = ""
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return (
            self.complete
            and not self.failures
            and isinstance(self.score, (int, float))
            and math.isfinite(self.score)
        )


@dataclass
class DigitalObject:
    root: Path
    config: dict
    evaluator: Callable | None = None
    optimizer: Callable | None = None

    @classmethod
    def load(cls, path: str | Path) -> "DigitalObject":
        root = Path(path).resolve()
        config = json.loads((root / "task.json").read_text())
        if config.get("mutable") != "baml_src/ns_harness":
            raise ValueError(
                "The runtime reserves baml_src/ns_harness for mutable code"
            )
        if config.get("trace_source", "local") != "local":
            raise ValueError("Only local native traces are configured in this release")
        seeds = config.get("seed_panels", [1, 7])
        if (
            len(seeds) < 2
            or len(set(seeds)) != len(seeds)
            or any(not isinstance(s, int) or s < 0 for s in seeds)
        ):
            raise ValueError("Use at least two distinct nonnegative selection seeds")
        if config["objective"]["improvement_threshold"] <= 0:
            raise ValueError("Improvement threshold must be positive")
        names = config["evaluation_files"] + config.get("export_files", [])
        if config.get("fixture_optimizer"):
            names.append(config["fixture_optimizer"])
        for name in names:
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Configuration path escapes object")
        for split in ["feedback", "selection", "audit"]:
            if not config["cases"][split]:
                raise ValueError("Every evaluation split needs at least one case")
        return cls(root, config)

    def source(self) -> Version:
        prefix = self.config.get("mutable", "baml_src/ns_harness")
        files = {}
        base = (self.root / prefix).resolve()
        if not base.is_relative_to(self.root):
            raise ValueError("Mutable namespace escapes object")
        for path in sorted(base.rglob("*.baml")):
            if path.is_symlink() or not path.resolve().is_relative_to(base):
                raise ValueError("Source symlinks are not allowed")
            files[path.relative_to(self.root).as_posix()] = path.read_text()
        if not files:
            raise ValueError("Empty harness")
        return Version(files)

    def cases(self, split: str) -> list[dict]:
        names = self.config["cases"][split]
        result = []
        for name in names:
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root / "cases"):
                raise ValueError("Case path escapes cases directory")
            result.append(json.loads(path.read_text()))
        return result

    @property
    def objective_version(self) -> str:
        fixed = {
            name: (self.root / name).read_text()
            for name in self.config["evaluation_files"]
        }
        return digest({"objective": self.config["objective"], "evaluator": fixed})


def serialize(value: Any) -> dict:
    return asdict(value)
