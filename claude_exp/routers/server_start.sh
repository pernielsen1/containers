#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER_USER:?SERVER_USER env var must be set}@serverhp.home"
ALL=(py java cpp)

usage() {
    echo "Usage: SERVER_USER=<user> $0 [crypto|py|java|cpp ...]"
    echo "       Each router is paired with its own downstream_host config and stops any other"
    echo "       language's router first (only one can hold the shared ports at a time) -"
    echo "       crypto_host started separately. Listing several just leaves the last one running."
    exit 1
}

# downstream_host's PAN/key dataset differs per language (see downstream_host/build_router.md),
# and only one router can hold the shared ports (8080/8081/etc, --network host) at a time anyway -
# so downstream_host isn't an independent always-on service like crypto_host is. It's (re)started
# in lockstep with whichever router is requested, using that language's own perf config baked into
# the shared downstream_host image (see downstream_host/Dockerfile).
declare -A DOWNSTREAM_CONFIG_BY_LANG=(
    [py]="router_py/simulators/downstream_host/config_perf.json"
    [java]="router_java/config/downstream_host_perf.json"
    [cpp]="router_cpp/config/downstream_host_perf.json"
)

declare -A ROUTER_ENV_BY_LANG=(
    [py]="ROUTER_CONFIG=router_1/config_perf.json"
    [java]="ROUTER_CONFIG=router_1_perf.json"
    [cpp]="ROUTER_CONFIG=router_1_perf.json"
)

start_container() {
    local name="$1" image="$2" env_arg="${3:-}"
    echo "[start] $name on $SERVER"
    ssh "$SERVER" bash -s <<EOF
docker rm -f $name 2>/dev/null || true
docker run -d --name $name --network host --init ${env_arg:+-e $env_arg} $image
echo "$name started."
EOF
}

start_lang() {
    local lang="$1"
    # Only one router can hold the shared --network host ports (8080/5000/etc) at a time - stop
    # any other language's router container first so two don't end up bound to the same ports
    # simultaneously (confirmed live: both silently "start" per `docker ps`, but only the first to
    # bind actually works - the second logs no error, its threads just never truly come up).
    for other in "${ALL[@]}"; do
        if [ "$other" != "$lang" ]; then
            ssh "$SERVER" "docker rm -f router_$other 2>/dev/null" >/dev/null || true
        fi
    done
    start_container "downstream_host" "downstream_host" "DOWNSTREAM_CONFIG=${DOWNSTREAM_CONFIG_BY_LANG[$lang]}"
    start_container "router_$lang" "router_$lang" "${ROUTER_ENV_BY_LANG[$lang]}"
}

targets=("${@:-${ALL[@]}}")
for t in "${targets[@]}"; do
    case $t in
        crypto)      start_container crypto_host crypto_host ;;
        py|java|cpp) start_lang "$t" ;;
        *) usage ;;
    esac
done
