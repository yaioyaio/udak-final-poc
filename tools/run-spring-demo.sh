#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v gradle >/dev/null 2>&1; then
  gradle :spring-boot-demo:test :spring-boot-demo:bootRun
elif [ -f ./gradlew ]; then
  ./gradlew :spring-boot-demo:test :spring-boot-demo:bootRun
else
  echo "Gradle is required. Install Gradle 8.14+ or generate a Gradle Wrapper first." >&2
  exit 2
fi
