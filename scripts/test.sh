#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export BAML_VERSION=0.20.2-nightly.20260929.a
export BOUNDARY_API_KEY=local
export DO_BAML_BINARY="${DO_BAML_BINARY:-$PWD/.tools/baml/bin/baml-cli}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
"$DO_BAML_BINARY" check --agent-skill-check off
"$DO_BAML_BINARY" test --agent-skill-check off --log off
python3 -m unittest discover -s tests -v
