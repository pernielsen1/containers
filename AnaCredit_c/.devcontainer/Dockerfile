FROM mcr.microsoft.com/devcontainers/python:3.12

# Install Node.js (required for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install common Python tooling
RUN pip install --upgrade pip \
    && pip install ipython requests pandas openpyxl jsonschema

# Create host_commands mount point
RUN mkdir -p /host_commands

WORKDIR /workspaces/AnaCredit_c
