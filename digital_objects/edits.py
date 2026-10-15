"""Atomic exact edits inside one declared BAML namespace."""

from pathlib import PurePosixPath

from .contracts import Version, text_hash


def apply(version: Version, proposal: dict, namespace: str) -> Version:
    if proposal["parent_hash"] != version.hash:
        raise ValueError("Stale parent")
    if proposal.get("no_change"):
        if proposal.get("edits"):
            raise ValueError("no_change cannot include edits")
        return version
    if not proposal.get("edits"):
        raise ValueError("Empty proposal")
    files = dict(version.files)
    grouped: dict[str, list[dict]] = {}
    for edit in proposal["edits"]:
        name = edit["path"]
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or str(path) != name
            or not name.startswith(namespace.rstrip("/") + "/")
            or path.suffix != ".baml"
        ):
            raise ValueError("Edit escapes mutable namespace")
        grouped.setdefault(name, []).append(edit)
    for name, edits in grouped.items():
        if name not in files:
            if (
                len(edits) != 1
                or edits[0].get("expected_hash") is not None
                or edits[0].get("search") is not None
            ):
                raise ValueError("Invalid new file edit")
            files[name] = edits[0]["replacement"]
            continue
        original = files[name]
        replacements = []
        for edit in edits:
            if edit.get("expected_hash") != text_hash(original):
                raise ValueError("Stale file hash")
            search = edit.get("search")
            if not search or original.count(search) != 1:
                raise ValueError("Search must match exactly once")
            start = original.index(search)
            replacements.append((start, start + len(search), edit["replacement"]))
        replacements.sort()
        if any(a[1] > b[0] for a, b in zip(replacements, replacements[1:])):
            raise ValueError("Overlapping edits")
        for start, end, replacement in reversed(replacements):
            original = original[:start] + replacement + original[end:]
        files[name] = original
    if sum(len(text.encode()) for text in files.values()) > 256_000:
        raise ValueError("Source bundle exceeds 256 KB")
    return Version(files, version.hash)
