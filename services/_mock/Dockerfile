# Contract mock of one service: Stoplight Prism serving ../contracts/openapi/<SPEC>.yaml, plus the two health
# endpoints the gateway and compose poll. Build context: services/_mock, the contracts are mounted at /contracts.
FROM alpine:3.24.4
# nodejs/npm from Alpine; Prism is pure JavaScript. Pinned to the version the contracts were validated with.
RUN apk add --no-cache nodejs npm \
 && npm install -g --omit=dev @stoplight/prism-cli@5.16.0 \
 && npm cache clean --force
COPY mock.js /app/mock.js
USER nobody
EXPOSE 8080 8081
CMD ["node", "/app/mock.js"]
