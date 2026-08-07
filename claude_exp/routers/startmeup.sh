#!/usr/bin/env bash
# One-button "kick the rebuilds off and go make coffee" entrypoint: makes sure the Docker daemon
# is up, then runs a short (10s/impl, single tps) stress_test.sh sweep across all three router
# implementations. The point isn't the performance numbers - it's that each impl's stress_run.sh
# does a `docker compose up --build` (or equivalent) on its way up, so this is the cheapest way to
# force a rebuild/recompile of all three images without hand-typing stress_test.sh flags every time.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

cat <<'MOUTH'

           .-"""""""""""""-.
        .-"                 "-.
      .'    .---------------.  '.
     /     /                 \   \
    |     | .---.     .---.   |   |
    |     | '---'     '---'   |   |
     \     \                 /   /
      '.    '---------------'  .'
        '-.._____________..-'
              |||||||||
              |||||||||
               \\\\\\\
                \\\\\
                 \\\
                  |

        ...Start Me Up...

MOUTH

echo "[startmeup] checking Docker daemon..."
./start_docker.sh

echo "[startmeup] kicking off a quick 10s/impl sweep to force rebuilds..."
./stress_test.sh --tps 50 --duration 10

echo "[startmeup] done - you never let me stop."
