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

# -j1 rather than -j$(nproc): crypto_host_main.cpp is a heavy translation unit (httplib in one
# file) and gets OOM-killed under parallelism on memory-constrained build hosts - same pitfall as
# router_cpp's router_main.cpp/crypto_host_main.cpp, see that Dockerfile's note.
RUN mkdir -p build && \
    cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release .. && \
    make -j1

RUN mkdir -p /config

ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib
ENV PATH=/src/build:$PATH

# Plugin-execution API + this actor's own CommandServer.
EXPOSE 5099 8099

CMD ["/bin/bash", "-c", "/src/build/crypto_host --config /src/config/crypto_host.json"]
