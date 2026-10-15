#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Scan tracked sources only; never upload runtime prompts, caches or credentials.
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
git archive HEAD | tar -xf - -C "$staging"
.tools/gitleaks/gitleaks dir "$staging" --redact --no-banner
python3 -m venv .tools/security-env
.tools/security-env/bin/pip --quiet install bandit==1.8.6
# Low-severity subprocess findings are reviewed in SECURITY.md, not suppressed.
.tools/security-env/bin/bandit -r digital_objects runtime -ll
