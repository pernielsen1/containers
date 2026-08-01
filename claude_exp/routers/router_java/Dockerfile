FROM mcr.microsoft.com/devcontainers/base:ubuntu

ENV DEBIAN_FRONTEND=noninteractive

# Optional sandboxed-session trust files: start.sh copies these in from /root/.ccr/ only when
# present, and this build stage is a no-op otherwise (start.sh's own comments explain why).
COPY .ccr-optional/ /tmp/ccr-optional/
RUN if [ -f /tmp/ccr-optional/ca-bundle.crt ]; then \
      cp /tmp/ccr-optional/ca-bundle.crt /usr/local/share/ca-certificates/build-proxy-ca.crt && \
      update-ca-certificates; \
    fi
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/build-proxy-ca.crt

RUN apt-get update && apt-get install -y openjdk-21-jdk maven nodejs npm curl python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Needed only so RouterFullStackTest.java (mvn test, run via `docker exec router_java mvn test`) can
# launch the shared routers/upstream_host Python component as a real subprocess for its full-stack
# test - upstream_host stopped having a Java reimplementation of its own once the three
# implementations' load generators were consolidated into one shared Python component (see
# ../divide_and_conquer.md and ../upstream_host/build_router.md).
RUN pip install --break-system-packages "pyiso8583>=4.0.0" "flask>=3.0.0" "requests>=2.31.0"

# JVM tools (Maven, and any Java code making HTTPS calls) use their own cacerts store, not the
# OS store update-ca-certificates just updated. If the sandbox's ready-made JVM truststore was
# copied in, use it; otherwise this points at a nonexistent file and the JDK's own default
# cacerts apply (harmless outside a sandboxed session).
ENV JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/ccr-optional/java-truststore.p12 -Djavax.net.ssl.trustStorePassword=changeit -Djavax.net.ssl.trustStoreType=PKCS12"

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
