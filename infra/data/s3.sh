#!/bin/sh
# Seeds or resets the two buckets. Runs inside the pgsty/silo image, which bundles the mcli client (MinIO mc compatible).
#   MODE        seed (default) | reset
#   S3_ENDPOINT S3_ROOT_USER S3_ROOT_PASSWORD S3_BUCKET_ORIGINALS S3_BUCKET_PUBLIC
# seed  mirrors seed/s3/originals and seed/s3/public into the buckets (public ones with the immutable Cache-Control of
#       README 10); objects that are already there are overwritten with identical bytes.
# reset removes every object; buckets, the anonymous-read policy and the service user stay.
set -eu
MODE="${MODE:-seed}"
A=silo
count() { n=0; while IFS= read -r _; do n=$((n + 1)); done; echo "$n"; }   # the image is not assumed to have grep or wc
mcli alias set "$A" "$S3_ENDPOINT" "$S3_ROOT_USER" "$S3_ROOT_PASSWORD" >/dev/null
for b in "$S3_BUCKET_ORIGINALS" "$S3_BUCKET_PUBLIC"; do
  mcli ls "$A/$b" >/dev/null 2>&1 || mcli stat "$A/$b" >/dev/null 2>&1 || {
    echo "ERROR: bucket $b does not exist. Run: make up (the s3-init job creates it)" >&2; exit 1; }
done
case "$MODE" in
  seed)
    mcli mirror --overwrite "${SEED_ORIGINALS:-/seed/s3/originals}" "$A/$S3_BUCKET_ORIGINALS" >/dev/null
    mcli mirror --overwrite --attr "Cache-Control=public, max-age=31536000, immutable" "${SEED_PUBLIC:-/seed/s3/public}" "$A/$S3_BUCKET_PUBLIC" >/dev/null
    echo "s3: $(mcli ls --recursive "$A/$S3_BUCKET_ORIGINALS" | count) originals, $(mcli ls --recursive "$A/$S3_BUCKET_PUBLIC" | count) public objects" ;;
  reset)
    for b in "$S3_BUCKET_ORIGINALS" "$S3_BUCKET_PUBLIC"; do
      # rm on an empty bucket may complain, so only remove when there is something to remove
      if [ -n "$(mcli ls "$A/$b" 2>/dev/null)" ]; then mcli rm --recursive --force "$A/$b" >/dev/null; fi
      echo "s3: $b emptied"
    done ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
