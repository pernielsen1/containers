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

# -j2 rather than -j$(nproc): router_main.cpp is a heavy translation unit (httplib + the full
# router object graph in one file) and gets OOM-killed under high parallelism on memory-constrained
# build hosts. See build_router_target_cpp.md's "Container" pitfall note.
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

# Default to showing usage; actual startup is via docker-compose or manual exec
CMD ["/bin/bash"]
