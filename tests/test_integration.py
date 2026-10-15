"""Real BAML execution, native traces, confinement, and revision selection."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from digital_objects import DigitalObject, Version
from digital_objects.execution import Runner
from digital_objects.learning import BamlEvaluator, Campaign
from digital_objects.storage import Store

OBJECT = Path(
    os.environ.get(
        "DO_MEDIA_OBJECT", Path(__file__).resolve().parents[2] / "objects/media-object"
    )
)


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.object = DigitalObject.load(OBJECT) if OBJECT.exists() else None
        self.runner = Runner(self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def run_source(self, source: str):
        return self.runner.execute(
            Version({"baml_src/ns_harness/main.baml": source}),
            {"input": {"case_id": "minimal"}, "replies": []},
            "feedback",
        )

    def test_framework_runs_non_media_harness(self):
        execution = self.run_source(
            "function run(input: json, client: ai.Client) -> json { "
            'baml.json.parse(`{"status":"complete","answer":42}`) }'
        )
        self.assertTrue(execution.complete, execution.errors)
        self.assertEqual(execution.submission["answer"], 42)
        self.assertTrue(execution.trace["root_span_id"])

    def test_full_episode_and_evaluator_query_native_traces(self):
        if self.object is None:
            self.skipTest("Set DO_MEDIA_OBJECT to run the media integration")
        case = self.object.cases("feedback")[0]
        original_memory = copy.deepcopy(case["input"]["memory"])
        execution = self.runner.execute(self.object.source(), case, "feedback")
        self.assertTrue(execution.complete, execution.errors)
        self.assertEqual(execution.submission["outcomes"][0]["status"], "pending")
        self.assertEqual(case["input"]["memory"], original_memory)
        evaluation = BamlEvaluator(self.object, self.runner)(execution, case, 1)
        self.assertTrue(evaluation.valid, evaluation.failures)
        self.assertTrue(evaluation.evidence)
        mismatched = copy.deepcopy(case)
        mismatched["input"]["case_id"] = "wrong"
        rejected = BamlEvaluator(self.object, self.runner)(execution, mismatched, 1)
        self.assertFalse(rejected.complete)

    def test_generated_revision_retained_only_after_two_panels(self):
        if self.object is None:
            self.skipTest("Set DO_MEDIA_OBJECT to run the media integration")
        store = Store(self.root / "state")
        report = Campaign(self.object, self.runner, store).evolve(1)
        result = report["results"][0]
        self.assertTrue(result["retained"], result)
        self.assertEqual(len(result["panels"]), 2)
        self.assertEqual(report["fresh_calls"], 0)
        self.assertNotEqual(report["retained"], self.object.source().hash)
        self.assertIn(
            "candidates.slice(0, 1)",
            self.object.source().files["baml_src/ns_harness/harness.baml"],
        )
        resumed = Campaign(self.object, self.runner, store).evolve(1, resume=True)
        self.assertEqual(resumed["results"], report["results"])
        audit = Campaign(self.object, self.runner, store).audit()
        self.assertTrue(
            all(e["complete"] and not e["failures"] for e in audit["evaluations"])
        )

    def test_sandbox_blocks_external_read_write_and_network(self):
        secret = self.root / "secret.txt"
        secret.write_text("test-only sentinel")
        outside = self.root / "outside.txt"
        actions = [
            f"baml.fs.read({json.dumps(str(secret))})",
            f'baml.fs.write({json.dumps(str(outside))}, "escape")',
            'baml.http.fetch("http://127.0.0.1:9").text()',
        ]
        for action in actions:
            execution = self.run_source(
                f"function run(input: json, client: ai.Client) -> json {{ "
                f"let result = {action}; baml.json.to_json(result) }}"
            )
            self.assertFalse(execution.complete)
            self.assertTrue(execution.errors)
        self.assertFalse(outside.exists())

    def test_compilation_initialization_is_also_confined(self):
        secret = self.root / "secret.txt"
        secret.write_text("test-only sentinel")
        source = (
            "function initialize() -> ai.Client { "
            f"let secret = baml.fs.read({json.dumps(str(secret))}); "
            "claude_code.ClaudeCodeClient.new(model = secret) }\n"
            "client Initialized = initialize();\n"
            "function run(input: json, client: ai.Client) -> json { baml.json.to_json(Initialized.id()) }"
        )
        execution = self.run_source(source)
        self.assertFalse(execution.complete)
        self.assertTrue(
            any(
                "Permission" in e or "denied" in e or "io is unavailable" in e
                for e in execution.errors
            ),
            execution.errors,
        )

    def test_worker_cannot_rewrite_its_trusted_input_or_source(self):
        for path in ["request.json", "baml_src/worker.baml", "worker.sb", "stdout.txt"]:
            execution = self.run_source(
                "function run(input: json, client: ai.Client) -> json { "
                f'baml.fs.write("{path}", "tampered"); input }}'
            )
            self.assertFalse(execution.complete, path)


if __name__ == "__main__":
    unittest.main()
