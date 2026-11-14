#!/bin/sh
# Bootstraps buckets, anonymous read for the public bucket, and a service user for media-service.
# Runs inside the pgsty/silo image, which bundles the mcli client.
# If your image variant has no mcli (for example -distroless), use the pgsty/mc image instead.
set -eu

ALIAS=silo

echo "waiting for ${S3_ENDPOINT} ..."
until mcli alias set "$ALIAS" "$S3_ENDPOINT" "$S3_ROOT_USER" "$S3_ROOT_PASSWORD" > /dev/null 2>&1; do
  sleep 2
done

# originals stay private (README 10: "original kept private"); variants are served publicly
mcli mb --ignore-existing "$ALIAS/$S3_BUCKET_ORIGINALS"
mcli mb --ignore-existing "$ALIAS/$S3_BUCKET_PUBLIC"
mcli anonymous set download "$ALIAS/$S3_BUCKET_PUBLIC"

# Service user for media-service (the built-in readwrite policy). Re-running is safe.
mcli admin user add "$ALIAS" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"
if ! out="$(mcli admin policy attach "$ALIAS" readwrite --user "$S3_ACCESS_KEY" 2>&1)"; then
  case "$out" in
    *already*) ;;                       # policy was attached by a previous run
    *) echo "$out"; exit 1 ;;
  esac
fi

echo "s3 ready:"
mcli ls "$ALIAS"
