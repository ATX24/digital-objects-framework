"""Bound process lifetime and output without buffering untrusted output forever."""

import os
import selectors
import signal
import subprocess
import time


def bounded(command: list[str], *, cwd, env, timeout: int, limit: int = 4_000_000):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    streams = [bytearray(), bytearray()]
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate([process.stdout, process.stderr]):
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Process timed out")
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    streams[key.data].extend(chunk)
                    if sum(map(len, streams)) > limit:
                        raise RuntimeError("Process output exceeds limit")
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            *(s.decode("utf-8", errors="replace") for s in streams),
        )
    finally:
        # Also reap children after a successful parent exit.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
        process.stderr.close()
