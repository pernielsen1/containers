#!/usr/bin/env bash
# Convenience entrypoint: ensures the Docker daemon is running before working with any of the
# three router implementations (router_py, router_java, router_cpp) or running stress_test.sh. Delegates to
# router_java's dockerstart.sh, which already has the service/sudo/dockerd fallback logic - kept in
# one place rather than duplicated per implementation.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./router_java/dockerstart.sh
