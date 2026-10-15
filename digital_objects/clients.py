"""Bounded native Claude transport and exact-response replay."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading

from .contracts import canonical
from .storage import write_json
from .process import bounded


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, limit: int = 32, used: int = 0):
        self.limit, self.used, self.hits = limit, used, 0
        self.lock = threading.Lock()
        self.path: Path | None = None

    def reserve(self):
        with self.lock:
            if self.used >= self.limit:
                raise BudgetExceeded("Fresh model-call budget exhausted")
            self.used += 1
            if self.path is not None:
                write_json(self.path, {"used": self.used, "limit": self.limit})


class Broker:
    def __init__(
        self, directory: Path, cache: Path, mode: str, model: str, budget: Budget
    ):
        self.directory, self.cache, self.mode = directory, cache, mode
        self.model, self.budget = model, budget
        self.calls = 0
        self.fresh = 0
        self.hits = 0
        self.errors: list[str] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        directory.mkdir(exist_ok=True)
        self.fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=130)
        os.close(self.fd)

    def read_request(self, name: str) -> dict:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "r") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
                raise ValueError("Invalid model request file")
            body = stream.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError("Model request exceeds limit")
            return json.loads(body)

    def respond(self, name: str, reply: dict):
        pending = name + ".pending"
        fd = os.open(
            pending,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.fd,
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(reply, stream)
        os.replace(pending, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)

    def serve(self):
        seen = set()
        while not self.stop.wait(0.025):
            for name in os.listdir(self.fd):
                if not name.endswith(".request") or name in seen:
                    continue
                seen.add(name)
                try:
                    reply = self.invoke(self.read_request(name)["args"])
                except Exception as error:
                    self.errors.append(str(error))
                    reply = {"returncode": 1, "stdout": "", "stderr": str(error)}
                try:
                    self.respond(name.removesuffix(".request") + ".response", reply)
                    os.unlink(name, dir_fd=self.fd)
                except OSError as error:
                    self.errors.append(str(error))

    def invoke(self, args: list[str]) -> dict:
        self.calls += 1
        if self.calls > 12:
            raise BudgetExceeded("Episode model-turn budget exhausted")
        # Accept only the native client's exact, tool-free CLI shape.
        prefix = ["-p", "--output-format", "stream-json", "--verbose", "--model"]
        if (
            not isinstance(args, list)
            or not all(isinstance(a, str) for a in args)
            or len(args) != 14
            or args[:5] != prefix
            or args[6:12]
            != [
                "--permission-mode",
                "default",
                "--no-session-persistence",
                "--tools",
                "",
                "--json-schema",
            ]
        ):
            raise ValueError("Unsupported Claude invocation")
        schema = args[12]
        json.loads(schema)
        safe_args = [*prefix, self.model, *args[6:]]
        fingerprint = hashlib.sha256(canonical(safe_args).encode()).hexdigest()
        cached = self.cache / f"{fingerprint}.json"
        if cached.exists():
            self.hits += 1
            self.budget.hits += 1
            return json.loads(cached.read_text())
        if self.mode != "explore":
            raise BudgetExceeded("Replay miss: no identical recorded request")
        self.budget.reserve()
        self.fresh += 1
        executable = shutil.which("claude")
        if not executable:
            raise RuntimeError("Claude Code is not installed")
        environment = dict(os.environ)
        for name in ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE"]:
            environment.pop(name, None)
        work = self.cache / "claude-work"
        work.mkdir(parents=True, exist_ok=True)
        result = bounded(
            [executable, *safe_args], cwd=work, env=environment, timeout=120
        )
        if len(result.stdout) + len(result.stderr) > 4_000_000:
            raise RuntimeError("Claude response exceeds 4 MB")
        reply = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if result.returncode == 0:
            write_json(cached, reply)
        return reply
