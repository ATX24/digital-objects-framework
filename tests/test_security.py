"""Regression checks for the boundary between generated code and its host."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

from digital_objects.clients import Broker, Budget, BudgetExceeded
from digital_objects.process import bounded
from digital_objects.traces import NoRedirect, TraceUnavailable


class SecurityTest(unittest.TestCase):
    def test_mailbox_rejects_symlinks_and_retains_directory_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            secret = outside / "secret"
            secret.write_text('{"args":[]}')
            broker = Broker(root / "ipc", root / "cache", "fixture", "haiku", Budget(0))
            try:
                (root / "ipc" / "bad.request").symlink_to(secret)
                with self.assertRaises(OSError):
                    broker.read_request("bad.request")
                (root / "ipc").rename(root / "original")
                (root / "ipc").symlink_to(outside, target_is_directory=True)
                broker.respond("reply.response", {"ok": True})
                self.assertFalse((outside / "reply.response").exists())
                self.assertTrue((root / "original" / "reply.response").exists())
            finally:
                os.close(broker.fd)

    def test_fixture_cannot_make_fresh_model_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broker = Broker(root / "ipc", root / "cache", "fixture", "haiku", Budget(1))
            try:
                with self.assertRaises(BudgetExceeded):
                    broker.invoke(
                        [
                            "-p",
                            "--output-format",
                            "stream-json",
                            "--verbose",
                            "--model",
                            "haiku",
                            "--permission-mode",
                            "default",
                            "--no-session-persistence",
                            "--tools",
                            "",
                            "--json-schema",
                            "{}",
                            "hello",
                        ]
                    )
                self.assertEqual(broker.budget.used, 0)
            finally:
                os.close(broker.fd)

    def test_output_and_wall_time_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            for source, timeout, limit in [
                ("print('x'*10000)", 5, 100),
                ("import time; time.sleep(10)", 1, 10000),
            ]:
                with self.assertRaises(RuntimeError):
                    bounded(
                        [sys.executable, "-c", source],
                        cwd=temporary,
                        env=dict(os.environ),
                        timeout=timeout,
                        limit=limit,
                    )

    def test_cloud_redirects_cannot_forward_credentials(self):
        with self.assertRaises(TraceUnavailable):
            NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "https://example.com"
            )
