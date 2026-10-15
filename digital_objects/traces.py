"""Read native BAML evidence; never maintain a second event database."""

import json
import subprocess
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = "0.20.2-nightly.20260929.a"


class TraceUnavailable(RuntimeError):
    pass


def decode(lines: str) -> tuple[list[dict], dict]:
    rows, columns, outcome = [], None, None
    for line in lines.splitlines():
        if not line.strip():
            continue
        frame = json.loads(line)
        if outcome is not None:
            raise TraceUnavailable("Data after query outcome")
        if "outcome" in frame or "queryOutcome" in frame:
            outcome = frame.get("outcome", frame.get("queryOutcome"))
        elif "columns" in frame:
            if columns is not None:
                raise TraceUnavailable("Duplicate column frame")
            columns = [
                c["name"] if isinstance(c, dict) else c for c in frame["columns"]
            ]
        elif "row" in frame:
            if columns is None or len(columns) != len(frame["row"]):
                raise TraceUnavailable("Invalid row shape")
            rows.append(dict(zip(columns, frame["row"])))
        else:
            rows.append(frame)
    if outcome is None or outcome.get("status") != "complete":
        raise TraceUnavailable("Missing or incomplete query outcome")
    if outcome.get("source_missing") or outcome.get("unsealed"):
        raise TraceUnavailable("Trace source missing or unsealed")
    if any(outcome.get("query", {}).get("unavailable", {}).values()):
        raise TraceUnavailable("Required captured values unavailable")
    return rows, outcome


class LocalTraces:
    def __init__(self, binary: str, environment: dict):
        self.binary, self.environment = binary, environment

    def query(self, project: Path, sql: str) -> list[dict]:
        result = subprocess.run(
            [
                self.binary,
                "query",
                "--from",
                str(project),
                "--format",
                "jsonl",
                "--max-rows",
                "10000",
                "--max-wall",
                "10s",
                "-",
            ],
            input=sql,
            text=True,
            capture_output=True,
            timeout=20,
            env=self.environment,
        )
        if result.returncode:
            raise TraceUnavailable(result.stderr[-1500:] or "Trace query failed")
        return decode(result.stdout)[0]

    def read_run(self, project: Path, run_id: str, entrypoint: str = "execute") -> dict:
        rows = self.query(
            project,
            "SELECT span_id, process_id, span_name, parent_span_id, status, "
            "start_time, end_time, duration, input_args, output_value, error_value, "
            "temporary_projections FROM spans",
        )
        roots = [
            row
            for row in rows
            if row["span_name"].endswith("." + entrypoint)
            and isinstance(row.get("input_args"), dict)
            and row["input_args"].get("run_id") == run_id
        ]
        if len(roots) != 1:
            raise TraceUnavailable("Expected exactly one trusted run span")
        root = roots[0]
        process_id = root["process_id"]
        processes = self.query(project, "SELECT process_id, status FROM processes")
        if not any(
            p["process_id"] == process_id and p["status"] == "success"
            for p in processes
        ):
            raise TraceUnavailable("Process did not complete successfully")
        announcements = self.query(
            project, "SELECT process_id, is_complete FROM span_announcements"
        )
        if any(
            a["process_id"] == process_id and not a["is_complete"]
            for a in announcements
        ):
            raise TraceUnavailable("Unfinished native spans")
        descendants = {root["span_id"]}
        while True:
            expanded = descendants | {
                r["span_id"] for r in rows if r["parent_span_id"] in descendants
            }
            if expanded == descendants:
                break
            descendants = expanded
        scoped = [r for r in rows if r["span_id"] in descendants]
        if root["status"] != "return" or root.get("output_value") is None:
            raise TraceUnavailable("Run failed or output was not captured")
        return {
            "complete": True,
            "root_span_id": root["span_id"],
            "process_id": process_id,
            "submission": root["output_value"],
            "spans": scoped,
            "backend": "local",
        }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TraceUnavailable("BCS redirects are not allowed")


class CloudTraces:
    """BCS wire adapter; deployment capabilities must be verified explicitly."""

    def __init__(self, endpoint: str, token: str, target: dict):
        if not endpoint.startswith("https://"):
            raise ValueError("BCS requires HTTPS")
        self.endpoint, self.token, self.target = endpoint.rstrip("/"), token, target

    def query(self, sql: str, query_id: str) -> list[dict]:
        request = Request(
            self.endpoint + "/v1/query",
            method="POST",
            data=json.dumps(
                {
                    "queryId": query_id,
                    "sql": sql,
                    "target": self.target,
                    "budgets": {"maxRows": 10000, "maxWallMs": 10000},
                }
            ).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.headers.get_content_type() != "application/x-ndjson":
                raise TraceUnavailable("Unexpected BCS response format")
            body = response.read(8_000_001)
        if len(body) > 8_000_000:
            raise TraceUnavailable("BCS response exceeds limit")
        rows, outcome = decode(body.decode())
        if outcome.get("queryId") != query_id:
            raise TraceUnavailable("BCS query ID mismatch")
        return rows
