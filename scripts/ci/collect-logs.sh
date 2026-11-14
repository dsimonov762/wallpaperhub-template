#!/usr/bin/env bash
# Writes the docker state and the logs of every container of the wallpaperhub compose project to a folder (default ci-logs/),
# so a failed pipeline can upload them as an artifact.   scripts/ci/collect-logs.sh [DIR]
DIR="${1:-ci-logs}"; mkdir -p "$DIR"
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' > "$DIR/docker-ps.txt" 2>&1
docker stats --no-stream > "$DIR/docker-stats.txt" 2>&1
for c in $(docker ps -aq --filter label=com.docker.compose.project=wallpaperhub); do
  n="$(docker inspect -f '{{.Name}}' "$c" | tr -d /)"
  docker logs --tail 500 "$c" > "$DIR/$n.log" 2>&1
done
echo "logs of $(ls "$DIR" | wc -l) files in $DIR"
