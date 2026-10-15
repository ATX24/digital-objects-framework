#!/usr/bin/env python3
"""Forward one native ClaudeCodeClient invocation through a bounded mailbox."""

import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid

directory = Path(__file__).parent / "ipc"
with (directory / "lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    identifier = uuid.uuid4().hex
    request = directory / f"{identifier}.request"
    pending = directory / f"{identifier}.pending"
    pending.write_text(json.dumps({"args": sys.argv[1:]}))
    os.replace(pending, request)
    response = directory / f"{identifier}.response"
    deadline = time.monotonic() + 125
    while not response.exists():
        if time.monotonic() >= deadline:
            sys.exit("Model broker timed out")
        time.sleep(0.025)
    result = json.loads(response.read_text())
    response.unlink()
    sys.stdout.write(result["stdout"])
    sys.stderr.write(result["stderr"])
    sys.exit(result["returncode"])
