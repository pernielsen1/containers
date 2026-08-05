FROM python:3.12-slim

WORKDIR /src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# docker-compose overrides this for local dev (bind-mounts src); on remote the image runs as-is.
CMD ["/bin/bash", "-c", "\
  python3 simulators/crypto_host/main.py & \
  python3 simulators/downstream_host/main.py & \
  python3 router/main.py --config router/router_1/config.json & \
  sleep infinity"]
