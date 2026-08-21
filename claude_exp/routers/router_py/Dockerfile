FROM python:3.12-slim

WORKDIR /src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# docker-compose overrides this for local dev (bind-mounts src); on remote the image runs as-is.
# downstream_host is the shared routers/downstream_host Python component, deployed and started
# separately (see ../downstream_host/Dockerfile, ../server_start.sh) - not bundled here.
ENV ROUTER_CONFIG=router_1/config_perf.json
CMD ["/bin/bash", "-c", "\
  python3 simulators/crypto_host/main.py & \
  python3 router/main.py --config router/${ROUTER_CONFIG} & \
  sleep infinity"]
