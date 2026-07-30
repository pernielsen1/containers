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

# -j1 rather than -j$(nproc): router_main.cpp/crypto_host_main.cpp are heavy translation units
# (httplib + the full router object graph in one file) and get OOM-killed under parallelism on
# memory-constrained build hosts - on this project's actual ~2.8GB dev host, even -j2 failed 4 of
# 5 times. See build_router.md's "Stress testing"/OOM pitfall notes before raising this.
RUN mkdir -p build && \
    cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release .. && \
    make -j1

# Create directories for config
RUN mkdir -p /config

# Set up environment
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib
ENV PATH=/src/build:$PATH

# Expose all required ports
EXPOSE 5000 5001 5002 8080 8081 8082 8083

# Default to showing usage; actual startup is via docker-compose or manual exec
CMD ["/bin/bash"]
