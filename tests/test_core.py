"""Learning and data-integrity contracts without live inference."""

import json
from pathlib import Path
import tempfile
import unittest

from digital_objects.contracts import Evaluation, Version, text_hash
from digital_objects.edits import apply
from digital_objects.learning import comparison
from digital_objects.memory import GitMemory
from digital_objects.storage import Store
from digital_objects.traces import decode, TraceUnavailable


class EditsTest(unittest.TestCase):
    def setUp(self):
        self.name = "baml_src/ns_harness/main.baml"
        self.version = Version({self.name: "function f() -> int { 1 }\n"})
        self.proposal = {
            "parent_hash": self.version.hash,
            "edits": [
                {
                    "path": self.name,
                    "expected_hash": text_hash(self.version.files[self.name]),
                    "search": "{ 1 }",
                    "replacement": "{ 2 }",
                }
            ],
        }

    def test_patch_preserves_parent(self):
        candidate = apply(self.version, self.proposal, "baml_src/ns_harness")
        self.assertIn("{ 2 }", candidate.files[self.name])
        self.assertIn("{ 1 }", self.version.files[self.name])
        self.assertEqual(candidate.parent, self.version.hash)

    def test_reject_stale_ambiguous_and_outside(self):
        for change in [
            {"expected_hash": "bad"},
            {"search": "missing"},
            {"path": "baml_src/ns_harness/../evaluator.baml"},
            {"path": "baml_src/evaluator.baml"},
        ]:
            p = json.loads(json.dumps(self.proposal))
            p["edits"][0].update(change)
            with self.assertRaises(ValueError):
                apply(self.version, p, "baml_src/ns_harness")

    def test_overlapping_edits_reject_whole_patch(self):
        self.proposal["edits"].append({**self.proposal["edits"][0], "search": "1"})
        with self.assertRaises(ValueError):
            apply(self.version, self.proposal, "baml_src/ns_harness")

    def test_comparison_requires_complete_valid_evidence(self):
        baseline = [Evaluation("a", 0.2)]
        self.assertTrue(comparison(baseline, [Evaluation("b", 0.3)], 0.02)["retain"])
        for bad in [
            Evaluation("b", None),
            Evaluation("b", 1, complete=False),
            Evaluation("b", 1, failures=["brand"]),
            Evaluation("b", 0.1),
        ]:
            self.assertFalse(comparison(baseline, [bad], 0.02)["retain"])


class TraceTest(unittest.TestCase):
    def test_local_and_cloud_frames(self):
        rows, _ = decode('{"value":2}\n{"outcome":{"status":"complete"}}')
        self.assertEqual(rows, [{"value": 2}])
        rows, _ = decode(
            '{"columns":[{"name":"value"}]}\n{"row":[2]}\n'
            '{"queryOutcome":{"status":"complete"}}'
        )
        self.assertEqual(rows, [{"value": 2}])

    def test_incomplete_never_means_zero(self):
        for body in [
            "",
            '{"value":2}',
            '{"outcome":{"status":"truncated"}}',
            '{"outcome":{"status":"complete","source_missing":true}}',
            '{"outcome":{"status":"complete"}}\n{"value":2}',
        ]:
            with self.assertRaises(TraceUnavailable):
                decode(body)


class StorageTest(unittest.TestCase):
    def test_exact_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            first, second = Version({"a": "1"}), Version({"a": "2"})
            store.retain(first)
            store.retain(second)
            store.retain(store.load(first.hash))
            self.assertEqual(store.retained(second).files, first.files)

    def test_memory_stale_writes_and_dirty_human_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = GitMemory(Path(directory) / "memory")
            (memory.root / "MEMORY.md").write_text("Keep my preference")
            memory.initialize()
            parent, files = memory.snapshot()
            revision = memory.commit(
                parent, {**files, "lessons.md": "Source-linked lesson"}
            )
            self.assertNotEqual(revision, parent)
            with self.assertRaises(ValueError):
                memory.commit(parent, files)
            (memory.root / "MEMORY.md").write_text("A human correction")
            with self.assertRaises(ValueError):
                memory.snapshot()


if __name__ == "__main__":
    unittest.main()
