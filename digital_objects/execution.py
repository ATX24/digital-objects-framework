"""Isolate compilation and execution; derive outputs from native traces."""

import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from .clients import Broker, Budget
from .contracts import Execution, Version, serialize
from .storage import write_json
from .traces import LocalTraces, VERSION
from .process import bounded

ROOT = Path(__file__).resolve().parents[1]


def baml_binary() -> str:
    explicit = os.environ.get("DO_BAML_BINARY")
    pinned = Path.home() / ".baml" / "toolchains" / VERSION / "bin" / "baml-cli"
    binary = explicit or (str(pinned) if pinned.exists() else shutil.which("baml"))
    if not binary:
        raise RuntimeError("Install the pinned BAML toolchain")
    return str(Path(binary).resolve())


def environment(directory: Path) -> dict:
    home = directory / "home"
    home.mkdir(exist_ok=True)
    (directory / "tmp").mkdir(exist_ok=True)
    return {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "TMPDIR": str(directory / "tmp"),
        "BAML_VERSION": VERSION,
        "BOUNDARY_API_KEY": "local",
        "BAML_LOG": "off",
    }


def sandbox_profile(directory: Path, binary: str) -> str:
    runtime = [
        "/System",
        "/usr/lib",
        "/usr/share",
        "/usr/bin",
        "/bin",
        "/dev",
        "/opt/homebrew/Cellar",
        "/opt/homebrew/opt",
        sys.base_prefix,
        str(Path(binary).parent),
    ]
    reads = "\n".join(
        f"(subpath {json.dumps(path)})" for path in runtime + [str(directory)]
    )
    writes = "\n".join(
        f"(subpath {json.dumps(str(directory / name))})"
        for name in [".baml", "ipc", "home", "tmp"]
    )
    return f"""(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read-data (require-any (literal "/") {reads}))
(allow file-write* (require-any
    {writes} (literal "/dev/null")))
"""


class Runner:
    def __init__(self, root: Path, budget: Budget | None = None, mode: str = "fixture"):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget = budget or Budget()
        self.mode = mode
        self.binary = baml_binary()

    def invoke(
        self, directory: Path, target: str, config: dict, timeout: int = 180
    ) -> dict:
        if not Path("/usr/bin/sandbox-exec").exists():
            raise RuntimeError(
                "Verified macOS sandbox required; no unconfined fallback"
            )
        directory = directory.resolve()
        env = environment(directory)
        proxy = directory / "claude-proxy"
        proxy.write_text(
            f"#!{sys.executable}\n"
            + (ROOT / "runtime/claude_proxy.py").read_text().split("\n", 1)[1]
        )
        proxy.chmod(0o700)
        config["executable"] = str(proxy)
        request_path = directory / "request.json"
        request = json.loads(request_path.read_text())
        request["client"] = config
        write_json(request_path, request)
        profile = directory / "worker.sb"
        profile.write_text(sandbox_profile(directory, self.binary))
        command = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile),
            self.binary,
            "run",
            target,
            "--output-format",
            "json",
            "--log",
            "off",
            "--diagnostic-format",
            "concise",
            "--agent-skill-check",
            "off",
        ]
        with Broker(
            directory / "ipc",
            self.root / "cache",
            self.mode,
            config.get("model", "haiku"),
            self.budget,
        ) as broker:
            stdout_path, stderr_path = (
                directory / "stdout.txt",
                directory / "stderr.txt",
            )
            process = bounded(command, cwd=directory, env=env, timeout=timeout)
            stdout, stderr = process.stdout, process.stderr
            stdout_path.write_text(stdout)
            stderr_path.write_text(stderr)
            stats = {
                "invocations": broker.calls,
                "fresh": broker.fresh,
                "cache_hits": broker.hits,
            }
            write_json(directory / "transport.json", stats)
            if process.returncode:
                raise RuntimeError(
                    "; ".join(broker.errors)
                    or stderr[-4000:]
                    or stdout[-2000:]
                    or f"Worker exited {process.returncode}"
                )
            if len(stdout) > 4_000_000:
                raise RuntimeError("Worker output exceeds limit")
            return json.loads(stdout)

    def project(self, files: dict[str, str], request: dict) -> Path:
        directory = self.root / "runs" / request["run_id"]
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "baml.toml").write_text('[package]\nname = "object-worker"\n')
        for name, content in files.items():
            path = directory / name
            if not path.resolve().is_relative_to(directory):
                raise ValueError("Source path escapes worker")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        write_json(directory / "request.json", request)
        return directory

    def execute(
        self, version: Version, case: dict, split: str, model: str = "haiku"
    ) -> Execution:
        run_id = uuid.uuid4().hex
        files = dict(version.files)
        files["baml_src/clients.baml"] = (ROOT / "baml_src/clients.baml").read_text()
        files["baml_src/worker.baml"] = (ROOT / "runtime/worker.baml").read_text()
        config = {"mode": self.mode, "model": model, "replies": case.get("replies", [])}
        directory = self.project(
            files, {"run_id": run_id, "input": case["input"], "client": config}
        )
        execution = Execution(
            run_id, version.hash, case["input"]["case_id"], split, str(directory)
        )
        try:
            returned = self.invoke(directory, "main", config)
            traces = LocalTraces(self.binary, environment(directory)).read_run(
                directory, run_id
            )
            if traces["submission"] != returned:
                raise RuntimeError("Trace output disagrees with worker output")
            execution.submission = traces.pop("submission")
            execution.trace = traces
        except Exception as error:
            execution.errors.append(str(error))
        write_json(directory / "execution.json", serialize(execution))
        return execution

    def function(
        self,
        files: dict[str, str],
        payload: dict,
        target: str,
        replies: list | None = None,
        model: str = "haiku",
    ) -> tuple[dict, Path]:
        config = {"mode": self.mode, "model": model, "replies": replies or []}
        files = {
            **files,
            "baml_src/clients.baml": (ROOT / "baml_src/clients.baml").read_text(),
        }
        directory = self.project(
            files, {"run_id": uuid.uuid4().hex, "input": payload, "client": config}
        )
        return self.invoke(directory, target, config), directory
