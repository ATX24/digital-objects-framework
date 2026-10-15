"""Git-versioned file snapshots; the harness owns their meaning and policy."""

from contextlib import contextmanager
import fcntl
from pathlib import Path, PurePosixPath
import subprocess


class GitMemory:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Digital Object",
                "-c",
                "user.email=memory@localhost",
                *args,
            ],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    @contextmanager
    def writer(self):
        with (self.root.parent / f".{self.root.name}.lock").open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def initialize(self):
        with self.writer():
            if not (self.root / ".git").exists():
                self.git("init", "-q")
                self.git("add", ".")
                self.git(
                    "commit", "-q", "--allow-empty", "-m", "Initialize task memory"
                )

    def snapshot(self) -> tuple[str, dict[str, str]]:
        if self.git("status", "--porcelain"):
            raise ValueError("Memory has uncommitted human edits; commit them first")
        files = {}
        for name in self.git("ls-files").splitlines():
            path = self.root / name
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError("Memory symlink is not allowed")
            files[name] = path.read_text()
        return self.git("rev-parse", "HEAD"), files

    def commit(self, parent: str, files: dict[str, str]) -> str:
        with self.writer():
            current, previous = self.snapshot()
            if current != parent:
                raise ValueError("Stale memory revision")
            for name, content in files.items():
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(p.lower() == ".git" for p in path.parts)
                    or str(path) != name
                    or "\\" in name
                    or len(content) > 12000
                ):
                    raise ValueError("Invalid memory file")
                target = self.root / name
                if target.is_symlink() or not target.resolve().is_relative_to(
                    self.root
                ):
                    raise ValueError("Memory path escapes store")
            if files == previous:
                return current
            try:
                for name in previous.keys() - files.keys():
                    (self.root / name).unlink()
                for name, content in files.items():
                    path = self.root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                self.git("add", ".")
                self.git("commit", "-q", "-m", "Consolidate episode memory")
            except Exception:
                # Only restore paths owned by this failed write.
                for name in files.keys() - previous.keys():
                    (self.root / name).unlink(missing_ok=True)
                for name, content in previous.items():
                    (self.root / name).write_text(content)
                self.git("reset", "-q", "HEAD", "--", ".")
                raise
            return self.git("rev-parse", "HEAD")
