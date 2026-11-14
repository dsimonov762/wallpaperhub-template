#!/bin/sh
# PORTS="8080=8101 8081=8191 9090=9101": listen on the first port of each pair, forward to $TARGET_HOST:<second>.
# Exits when one of the forwarders dies, so the restart policy (and docker ps) show the problem.
TARGET_HOST="${TARGET_HOST:-host.docker.internal}"
pids=""
for pair in $PORTS; do
  socat "TCP-LISTEN:${pair%%=*},fork,reuseaddr" "TCP:${TARGET_HOST}:${pair##*=}" &
  pids="$pids $!"
  echo "forwarding :${pair%%=*} -> ${TARGET_HOST}:${pair##*=}"
done
trap 'kill $pids 2>/dev/null; exit 0' TERM INT
while :; do
  for p in $pids; do kill -0 "$p" 2>/dev/null || { echo "forwarder $p died" >&2; kill $pids 2>/dev/null; exit 1; }; done
  sleep 2
done
