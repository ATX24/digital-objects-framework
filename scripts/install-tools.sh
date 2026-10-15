#!/bin/sh
# Pinned downloads; no authentication or mutable installer script.
set -eu
cd "$(dirname "$0")/.."
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)
    target=aarch64-apple-darwin
    baml_sha=d5f505c851a5920d5609e2c8364a531bbac992fc87a3f606fb1cf32fbba97c74
    leaks_target=darwin_arm64
    leaks_sha=b90f13bb8c90ab72083d9b0c842e39dafb82c0e5c3f872f407366b7a58909013 ;;
  Darwin-x86_64)
    target=x86_64-apple-darwin
    baml_sha=203e3f2b041aaf9505df6dcba9982a342a9113a2bb2626acbe9c9c3c101ceb46
    leaks_target=darwin_x64
    leaks_sha=41c44ae8ad1d6eef57d4526ad0fd67d8129eee9a856f55c2b3b9395fd3d9ec0f ;;
  *) echo 'This release requires macOS for execution confinement.' >&2; exit 1 ;;
esac
version=0.20.2-nightly.20260929.a
mkdir -p .tools/baml .tools/gitleaks
curl --fail --location --retry 3 --output .tools/baml.tar.gz \
  "https://github.com/BoundaryML/baml/releases/download/baml-language-$version/baml-language-$version-$target.tar.gz"
printf '%s  %s\n' "$baml_sha" .tools/baml.tar.gz | shasum -a 256 -c -
tar -xzf .tools/baml.tar.gz -C .tools/baml
curl --fail --location --retry 3 --output .tools/gitleaks.tar.gz \
  "https://github.com/gitleaks/gitleaks/releases/download/v8.24.3/gitleaks_8.24.3_$leaks_target.tar.gz"
printf '%s  %s\n' "$leaks_sha" .tools/gitleaks.tar.gz | shasum -a 256 -c -
tar -xzf .tools/gitleaks.tar.gz -C .tools/gitleaks
test -x .tools/baml/bin/baml-cli
test -x .tools/gitleaks/gitleaks
