#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD_DIR="${TMPDIR:-/tmp}/udak-core-smoke-$$"
trap 'rm -rf "$BUILD_DIR"' EXIT
mkdir -p "$BUILD_DIR"
find core/src/main/java core/src/test/java -name '*.java' -print0 | xargs -0 javac --release 17 -d "$BUILD_DIR"
java -cp "$BUILD_DIR" dev.udak.core.CoreSmokeTest
