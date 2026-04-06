FROM python:3.11-slim

# System dependencies + Node.js (required for Claude Code CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        git \
        curl \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Ensure validate.sh is executable
RUN chmod +x /workspace/validate.sh

# Add src to PYTHONPATH so validators can import each other without path hacks
ENV PYTHONPATH="/workspace/src:${PYTHONPATH}"

CMD ["bash"]
