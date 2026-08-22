FROM maven:3.9-eclipse-temurin-25 AS build

# Optional sandboxed-session trust files: start.sh copies these in from /root/.ccr/ only when
# present, and this stage is a no-op otherwise - needed so `mvn dependency:resolve` below can
# reach Maven Central through this sandbox's loopback build proxy. Has nothing to do with the
# router's own runtime TLS (it builds its own explicit SSLContext from config/certs/, resolved
# relative to whichever --config file is passed - see RouterConfig.java/CryptoHostMain.java), so
# this shim stays confined to this build stage only.
COPY .ccr-optional/ /tmp/ccr-optional/
RUN if [ -f /tmp/ccr-optional/ca-bundle.crt ]; then \
      cp /tmp/ccr-optional/ca-bundle.crt /usr/local/share/ca-certificates/build-proxy-ca.crt && \
      update-ca-certificates; \
    fi
ENV JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/ccr-optional/java-truststore.p12 -Djavax.net.ssl.trustStorePassword=changeit -Djavax.net.ssl.trustStoreType=PKCS12"

# RouterFullStackTest (mvn test) spawns the shared routers/upstream_host and
# routers/downstream_host Python components as real subprocesses - see run_tests.sh, which bind-
# mounts them into this stage at /upstream_host, /downstream_host.
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/* \
    && pip install --break-system-packages "pyiso8583>=4.0.0" "flask>=3.0.0" "requests>=2.31.0"

WORKDIR /build
COPY pom.xml .
RUN mvn dependency:resolve -q
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:25-jre-jammy
# procps: monitor_host's docker-exec-based actor kill matches processes via `ps -eo pid,args` (see
# ../monitor_host/backends/router_java.py) - this runtime image ships no JDK, so `jps` isn't an
# option the way it was in the old persistent devcontainer image.
RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/target/router_java.jar .
