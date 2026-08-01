FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.82.1

RUN mkdir -p /workspace /pi-state \
    && chown -R node:node /workspace /pi-state

USER node
WORKDIR /workspace

ENV PI_CODING_AGENT_DIR=/pi-state
ENV PI_SKIP_VERSION_CHECK=1
ENV PI_TELEMETRY=0

ENTRYPOINT ["pi"]
