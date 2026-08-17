FROM python:3.12-slim

# docker-cli only (no daemon) -- backends/router_cpp.py and backends/router_java.py shell out to
# `docker exec`/`docker ps` against the host's docker.sock, which start.sh bind-mounts in.
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The routers/ tree (this file's repo) is bind-mounted at runtime by start.sh, not baked in here
# -- every backends/<target>.py resolves ROUTERS_ROOT from its own __file__ at import time, so it
# just needs the same relative layout under the mount point, and router source edits don't
# require an image rebuild.
WORKDIR /src/monitor_host

ENTRYPOINT ["python3", "main.py"]
