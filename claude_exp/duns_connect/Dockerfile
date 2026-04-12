FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install MySQL, Python, Node.js (for Claude CLI), and tools
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*


# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Set up working directory
WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY requirements_manual.txt .
RUN pip install --break-system-packages -r requirements_manual.txt


ENTRYPOINT ["/entrypoint.sh"]

