"""Fail closed when the scanner skips files, even if its exit status is zero."""

import json
from pathlib import Path
import subprocess

report = Path(".tools/bandit.json")
result = subprocess.run([
    ".tools/security-env/bin/bandit", "-r", "digital_objects", "runtime",
    "-f", "json", "-o", str(report),
], check=False)
if result.returncode not in (0, 1):
    raise SystemExit("Bandit failed to run")
scan = json.loads(report.read_text())
if scan["errors"] or scan["metrics"]["_totals"]["loc"] == 0:
    raise SystemExit("Incomplete security scan: skipped files or no code scanned")
blocking = [issue for issue in scan["results"] if issue["issue_severity"] in ("MEDIUM", "HIGH")]
for issue in scan["results"]:
    print(f'{issue["issue_severity"]} {issue["test_id"]} '
          f'{issue["filename"]}:{issue["line_number"]}: {issue["issue_text"]}')
if blocking:
    raise SystemExit("Security scan found medium/high severity issues")
print(f'Complete scan: {len(scan["results"])} low-severity findings; '
      '0 medium/high findings. See SECURITY.md for review.')
