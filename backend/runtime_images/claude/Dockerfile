FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.208

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-venv \
    && npm install --global "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

USER 65532:65532

CMD ["claude", "--version"]
