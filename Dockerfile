FROM python:3.12-slim

WORKDIR /app

# System dependencies for Claude CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI (install script requires bash, not sh)
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.claude/local/bin/claude /usr/local/bin/claude

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sidechannel/ sidechannel/
COPY plugins/ plugins/

VOLUME ["/app/config", "/app/data", "/projects"]

CMD ["python", "-m", "sidechannel"]
