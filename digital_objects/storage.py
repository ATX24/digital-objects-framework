"""Immutable snapshots and atomic pointers, separate from BAML traces."""

from pathlib import Path
import json
import os
import tempfile

from .contracts import Version, canonical


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, version: Version) -> str:
        path = self.root / "versions" / f"{version.hash}.json"
        if not path.exists():
            write_json(
                path,
                {
                    "hash": version.hash,
                    "parent": version.parent,
                    "files": version.files,
                },
            )
        return version.hash

    def load(self, version_hash: str) -> Version:
        if len(version_hash) != 64 or any(
            c not in "0123456789abcdef" for c in version_hash
        ):
            raise ValueError("Invalid version hash")
        value = json.loads(
            (self.root / "versions" / f"{version_hash}.json").read_text()
        )
        version = Version(value["files"], value["parent"])
        if version.hash != version_hash:
            raise ValueError("Snapshot hash mismatch")
        return version

    def retain(self, version: Version) -> None:
        self.save(version)
        write_json(self.root / "retained.json", {"hash": version.hash})

    def retained(self, default: Version) -> Version:
        path = self.root / "retained.json"
        return (
            self.load(json.loads(path.read_text())["hash"])
            if path.exists()
            else default
        )

    def append(self, result: dict) -> None:
        with (self.root / "history.jsonl").open("a") as stream:
            stream.write(canonical(result) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def history(self) -> list[dict]:
        path = self.root / "history.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
