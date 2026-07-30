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

RUN apt-get update && apt-get install -y openjdk-21-jdk maven nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

# JVM tools (Maven, and any Java code making HTTPS calls) use their own cacerts store, not the
# OS store update-ca-certificates just updated. If the sandbox's ready-made JVM truststore was
# copied in, use it; otherwise this points at a nonexistent file and the JDK's own default
# cacerts apply (harmless outside a sandboxed session).
ENV JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/ccr-optional/java-truststore.p12 -Djavax.net.ssl.trustStorePassword=changeit -Djavax.net.ssl.trustStoreType=PKCS12"

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
