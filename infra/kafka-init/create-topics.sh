#!/bin/sh
# Creates every topic from README section 5.6, plus retry topics and a DLQ per topic.
set -eu

BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:29092}"
PARTITIONS="${PARTITIONS:-3}"

TOPICS="
account.user.registered.v1
account.user.profile-updated.v1
account.user.deleted.v1
media.asset.processed.v1
media.asset.rejected.v1
catalog.wallpaper.published.v1
catalog.wallpaper.moderated.v1
"

for topic in $TOPICS; do
  for suffix in "" ".retry.1" ".retry.2" ".dlq"; do
    name="${topic}${suffix}"
    echo "creating topic ${name}"
    kafka-topics --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
      --topic "$name" --partitions "$PARTITIONS" --replication-factor 1
  done
done

echo "topics:"
kafka-topics --bootstrap-server "$BOOTSTRAP" --list
