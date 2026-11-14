# Pinned contract tooling (Spectral, buf, openapi-typescript, tsc) so nobody installs Node for it.
# Built and run by scripts/ct.sh. Build context: tools/contract-tools (package.json + package-lock.json).
FROM alpine:3.24.4
RUN apk add --no-cache nodejs npm
WORKDIR /opt/contract-tools
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
ENV PATH=/opt/contract-tools/node_modules/.bin:$PATH
WORKDIR /repo
