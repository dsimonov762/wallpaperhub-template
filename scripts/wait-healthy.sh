#!/usr/bin/env bash
# Waits until every container of the wallpaperhub compose project that has a healthcheck is healthy.
# Fails early when a one-shot job (kafka-init, ...) exited with an error.   scripts/wait-healthy.sh [timeout-seconds]
timeout="${1:-600}"; end=$(( $(date +%s) + timeout )); last=""
while :; do
  rows="$(docker ps -a --filter label=com.docker.compose.project=wallpaperhub --format '{{.Names}}|{{.Status}}')"
  failed="$(printf '%s\n' "$rows" | grep -E '\|Exited \([1-9]' || true)"
  unhealthy="$(printf '%s\n' "$rows" | grep -E '\(unhealthy\)' || true)"
  starting="$(printf '%s\n' "$rows" | grep -E 'health: starting' | cut -d'|' -f1 | tr '\n' ' ')"
  if [ -n "$failed" ]; then echo "a job failed:"; printf '%s\n' "$failed"; echo "see: make logs S=<name>"; exit 1; fi
  if [ -z "$starting" ] && [ -z "$unhealthy" ]; then echo "all containers healthy"; exit 0; fi
  if [ "$(date +%s)" -ge "$end" ]; then echo "timeout; still waiting for: $starting $unhealthy"; exit 1; fi
  [ "$starting" != "$last" ] && { echo "waiting for: ${starting:-unhealthy containers to recover}"; last="$starting"; }
  sleep 3
done
