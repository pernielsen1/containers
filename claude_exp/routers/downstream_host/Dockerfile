# Build context is the repo root (routers/), not this directory - see deploy.sh's
# deploy_downstream(): downstream_host/main.py's load_config() resolves iso_spec/pans_defined/
# certfile/keyfile/cafile relative to the config file's own path (see load_config() in main.py),
# so each language's config keeps working unchanged only if its sibling directories are copied in
# at the same relative offsets they have in the real repo layout.
FROM python:3.12-slim
WORKDIR /app

COPY downstream_host/requirements.txt downstream_host/requirements.txt
RUN pip install --no-cache-dir -r downstream_host/requirements.txt

COPY downstream_host/ downstream_host/
COPY upstream_host/test_spec.json upstream_host/test_spec.json

# router_py's config ("../../certs/...", "../../test_spec.json", "../../pans_defined.json" relative
# to router_py/simulators/downstream_host/) needs these three siblings of router_py/.
COPY router_py/certs/ router_py/certs/
COPY router_py/test_spec.json router_py/test_spec.json
COPY router_py/pans_defined.json router_py/pans_defined.json
COPY router_py/simulators/downstream_host/ router_py/simulators/downstream_host/

# router_java/router_cpp keep certs+pans_defined inside their own config/ dir - copying the whole
# dir is simplest and small (~100K each, includes files downstream_host doesn't need too).
COPY router_java/config/ router_java/config/
COPY router_cpp/config/ router_cpp/config/

EXPOSE 5001 8081

# Which language's config to launch with - set via `docker run -e DOWNSTREAM_CONFIG=...`
# (server_start.sh sets this per-language). Defaults to router_py's so a bare `docker run` still
# comes up with something runnable for a manual smoke test.
ENV DOWNSTREAM_CONFIG=router_py/simulators/downstream_host/config_perf.json
CMD ["/bin/bash", "-c", "python3 downstream_host/main.py --config ${DOWNSTREAM_CONFIG}"]
