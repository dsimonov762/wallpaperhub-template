#!/usr/bin/env node
// Mock of one Wallpaper Hub service, generated from its OpenAPI contract with Stoplight Prism.
// Lets the gateway, Keycloak and the e2e suite run before a real implementation exists.
//
//   :8080  the API, answered by Prism with the examples of the spec (Prefer: code=NNN picks another response)
//   :8081  management: /health/live and /health/ready (what the Envoy upstream health checks and compose probe)
//
// Environment:
//   SPEC_FILE    path of the OpenAPI file (default /contracts/openapi/${SPEC}.yaml)
//   SPEC         account | media | catalog | notification
//   BIND_HOST    address to listen on (default 0.0.0.0)
//   PORT         API port (default 8080)
//   MGMT_PORT    management port (default 8081)
//   PRISM_PORT   internal Prism port on 127.0.0.1 (default 4010)
//   PRISM_BIN    prism executable (default "prism")
'use strict';
const http = require('http');
const { spawn } = require('child_process');

const spec = process.env.SPEC_FILE || `/contracts/openapi/${process.env.SPEC}.yaml`;
const host = process.env.BIND_HOST || '0.0.0.0';
const port = Number(process.env.PORT || 8080);
const mgmtPort = Number(process.env.MGMT_PORT || 8081);
const prismPort = Number(process.env.PRISM_PORT || 4010);
const prismBin = process.env.PRISM_BIN || 'prism';
const service = process.env.SPEC || spec.split('/').pop().replace(/\.ya?ml$/, '');

let prismReady = false;
const prism = spawn(prismBin, ['mock', '--host', '127.0.0.1', '--port', String(prismPort), '--errors', spec], {
  stdio: ['ignore', 'pipe', 'pipe'],
});
const log = (m) => process.stdout.write(`[mock:${service}] ${m}\n`);
prism.stdout.on('data', (d) => {
  const s = d.toString();
  if (/Prism is listening/.test(s)) prismReady = true;
});
prism.stderr.on('data', (d) => process.stderr.write(d));
prism.on('exit', (code) => {
  log(`prism exited with ${code}`);
  process.exit(code || 1);
});
['SIGINT', 'SIGTERM'].forEach((s) => process.on(s, () => { prism.kill(); process.exit(0); }));

// Management: ready once Prism has loaded the spec.
http.createServer((req, res) => {
  const ok = req.url.startsWith('/health/live') || (req.url.startsWith('/health/ready') && prismReady);
  res.writeHead(ok ? 200 : 503, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ status: ok ? 'UP' : 'DOWN', mock: service }));
}).listen(mgmtPort, host, () => log(`management on ${host}:${mgmtPort}`));

// API: reverse proxy to Prism. The specs declare `servers: /api/v1`, which Prism treats as a base path it never
// matches, so the prefix is removed here (the gateway forwards the full /api/v1/... path, like a real service sees).
// Prism answers 404 problem documents for unknown routes.
http.createServer((req, res) => {
  const path = req.url.replace(/^\/api\/v1(?=\/|\?|$)/, '') || '/';
  const upstream = http.request(
    { host: '127.0.0.1', port: prismPort, method: req.method, path, headers: req.headers },
    (up) => { res.writeHead(up.statusCode, up.headers); up.pipe(res); }
  );
  upstream.on('error', () => {
    res.writeHead(503, { 'Content-Type': 'application/problem+json' });
    res.end(JSON.stringify({ type: 'https://wallpaperhub.dev/problems/upstream-unavailable', title: 'Mock not ready', status: 503 }));
  });
  req.pipe(upstream);
}).listen(port, host, () => log(`api on ${host}:${port} (spec ${spec})`));
