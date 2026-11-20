# 0019. PGSTY Silo as the local S3-compatible store

- Status: Accepted
- Date: 2026-11-20

## Context

media-service stores originals and variants in S3-compatible object storage. The README's architecture names "S3 / MinIO". The local stack needs a container that speaks the S3 API, with the buckets and a
service user with limited rights for media-service created at start. The image used was one that was already pulled on the first developer machine; the other options were not compared, and the choice was not certain to be a good one.

## Decision

The `infra` profile runs **PGSTY Silo**, a MinIO fork that keeps the `MINIO_*` variables and the S3 API, as the service `s3` ([`docker-compose.yml`](../../infra/docker-compose.yml)). `s3-init` creates the buckets, the anonymous-read policy of the public one
and a service user with the client that is bundled in the image. The compose file names three alternatives: Garage (`dxflrs/garage`), SeaweedFS (`chrislusf/seaweedfs`) and RustFS (`rustfs/rustfs`).

## Consequences

- media-service depends on the S3 API only, with endpoint, bucket and credentials taken from the environment, so the store can be replaced without a change to a service.
- What does not carry over is the bootstrap: `infra/minio-init/init.sh` uses the `mcli` client of the Silo image, so another store needs another init script, and the seed data job that loads images into S3 uses the same image.
- Silo's versions are dates (`RELEASE.2026-10-26T00-00-00Z`); the Renovate configuration reads year, month and day as major, minor and patch so that the next year is not treated as a breaking change ([0018](0018-pin-every-version-and-let-renovate-propose-updates.md)).
- This record is accepted because the stack runs on it, not because the alternatives were measured. Replace it with a record that says why when you compare them, or when the project behind the image changes.

## Alternatives considered

MinIO itself, which the README names, and the three images above were not evaluated for this record.
