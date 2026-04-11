FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install MySQL, Python, Node.js (for Claude CLI), and tools
RUN apt-get update && apt-get install -y \
    mysql-server \
    python3 \
    python3-pip \
    python3-venv \
    python3-pymysql \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Set up working directory
WORKDIR /app

# Copy project files
# PY company_ids.csv .
# PY test_company_id.py .

# Configure MySQL to allow root login and external connections
RUN mkdir -p /var/run/mysqld && chown mysql:mysql /var/run/mysqld

# Entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PN_MYSQL_USER="pn_user"
ENV PN_MYSQL_PASSWORD="pn_password"

ENTRYPOINT ["/entrypoint.sh"]
