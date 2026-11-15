#!/usr/bin/env bash
# make seed-build | make seed-check : regenerates (or verifies) seed/out and the seed images from seed/dataset.yaml.
# Uses the local python3 when it has PyYAML, Pillow and numpy, otherwise a python container.
set -eu
cd "$(dirname "$0")/.."
ARGS=("$@")
if python3 -c 'import yaml' 2>/dev/null && { [ "${1:-}" = --check ] || python3 -c 'import PIL, numpy' 2>/dev/null; }; then
  exec python3 seed/build.py "${ARGS[@]}"
fi
command -v docker >/dev/null || { echo "need python3 with: pip install -r seed/requirements.txt  (or Docker)" >&2; exit 1; }
exec docker run --rm -v "$PWD:/w" -w /w -e PIP_ROOT_USER_ACTION=ignore python:3.13-slim \
  sh -c 'pip install -q --disable-pip-version-check -r seed/requirements.txt && python seed/build.py "$@"' sh "${ARGS[@]}"
