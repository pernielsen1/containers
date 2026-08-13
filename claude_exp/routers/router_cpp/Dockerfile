FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    cmake \
    g++ \
    git \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

COPY . .

# EXPERIMENTAL: was -j1 (see build_router.md's OOM pitfall notes - on this project's ~2.8GB dev
# host, -j2 previously OOM-killed 4 of 5 times). Testing -j2 now that more host memory is free.
RUN mkdir -p build && \
    cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release .. && \
    make -j2

# Create directories for config
RUN mkdir -p /config

# Set up environment
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib
ENV PATH=/src/build:$PATH

# Expose all required ports
EXPOSE 5000 5001 5002 8080 8081 8082 8083

# docker-compose overrides this for local dev (bind-mounts config to /config); on remote uses /src/config.
ENV ROUTER_CONFIG=router_1.json
CMD ["/bin/bash", "-c", "\
  /src/build/crypto_host     --config /src/config/router_1.json & \
  /src/build/downstream_host --config /src/config/${ROUTER_CONFIG} & \
  /src/build/router_main     --config /src/config/${ROUTER_CONFIG} & \
  sleep infinity"]
