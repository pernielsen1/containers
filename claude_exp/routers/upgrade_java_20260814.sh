#!/bin/bash
# One-off: upgrade the host JDK from 21 to 25 (current LTS) and switch it on as the default
# `java`/`javac`. Run manually on each laptop - not invoked by any other script in this repo.
#
# router_java's Docker image already points at openjdk-25-jdk (see router_java/Dockerfile) and
# gets picked up on the next `docker build` (router_java/start.sh does this automatically whenever
# the Dockerfile changed since the last build - no separate step needed there).
#
# maven.compiler.release was initially left at 21 in router_java/pom.xml on the theory that running
# the build on a newer JDK doesn't require bumping the bytecode target - but a JDK-only upgrade with
# the language level left behind reads as more "mixed state to reason about" than it's worth for a
# single-module repo experiment, so it was bumped to 25 as well (see router_java/pom.xml /
# router_java/build_router.md) rather than staying split.
#
# GOTCHA (found 2026-08-15, annoying but by design): this script switches `java`/`javac` via
# `update-alternatives`, which only changes what plain `java`/`javac` on PATH resolve to. Maven
# does NOT go through PATH for this - its launcher script explicitly prefers $JAVA_HOME when set,
# so if JAVA_HOME is exported anywhere in your shell/profile (`echo $JAVA_HOME` to check), `mvn`
# keeps silently building with whatever JDK JAVA_HOME still points at even after this script runs
# and `java -version` correctly reports the new one - confirmed on this host: `java -version` said
# 25, `mvn -version`'s "Java version:" line still said 21, both at once. Symptom if release is ever
# bumped past what JAVA_HOME's JDK supports: "release version NN not supported". Fix is to also
# update (or unset) JAVA_HOME, which this script does not do - it's normally set once in a shell
# profile / `.bashrc`, not something safe to overwrite unattended.
#
# Usage: ./upgrade_java_20260814.sh
set -euo pipefail

NEW_VERSION=25

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This script only handles apt-based hosts (Debian/Ubuntu) - install OpenJDK ${NEW_VERSION} manually." >&2
  exit 1
fi

echo "== Current java =="
java -version 2>&1 || echo "(no java on PATH)"

echo
echo "== Installing openjdk-${NEW_VERSION}-jdk =="
sudo apt-get update
sudo apt-get install -y "openjdk-${NEW_VERSION}-jdk"

NEW_JAVA="/usr/lib/jvm/java-${NEW_VERSION}-openjdk-amd64/bin/java"
NEW_JAVAC="/usr/lib/jvm/java-${NEW_VERSION}-openjdk-amd64/bin/javac"

if [ ! -x "$NEW_JAVA" ]; then
  echo "ERROR: expected $NEW_JAVA after install - package layout may differ, check manually." >&2
  exit 1
fi

echo
echo "== Registering as an alternative and switching default =="
sudo update-alternatives --install /usr/bin/java java "$NEW_JAVA" 2511
sudo update-alternatives --install /usr/bin/javac javac "$NEW_JAVAC" 2511
sudo update-alternatives --set java "$NEW_JAVA"
sudo update-alternatives --set javac "$NEW_JAVAC"

echo
echo "== New default java =="
java -version
mvn -version 2>/dev/null || true

echo
echo "Done. router_java's Docker image switches to Java ${NEW_VERSION} on its next build -"
echo "run ./router_java/start.sh (or ./router_java/dockerstart.sh, if that's what you use) to rebuild."
