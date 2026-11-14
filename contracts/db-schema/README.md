# Canonical data-store schemas

The persistent shape of every service (README section 6), as files any language can use. Services own their stores:
no service reads or writes another service's database, and nothing here has a foreign key across services.

| Store | Service | Files |
|---|---|---|
| PostgreSQL | account | `postgres/account/V1__init.sql` |
| PostgreSQL | media | `postgres/media/V1__init.sql` |
| MongoDB | catalog | `mongo/catalog.json` (source of truth), `mongo/init.js` (generated), `mongo/build-init.mjs` |
| Elasticsearch | catalog | `elasticsearch/wallpapers-v1.json`, `elasticsearch/queries/*.json`, `elasticsearch/create-index.sh` |
| Redis | gateway, account, media, catalog, notification | `redis/keys.yaml` |

notification-service has no relational or document database: Redis with AOF persistence is its primary store
(README 3), so its schema is the key catalogue.

## Applying them

**PostgreSQL.** The files are plain SQL named like Flyway migrations, so they work as they are with Flyway and
with Liquibase (`sql` format), Atlas, dbmate and `psql -f`. For golang-migrate rename `V1__init.sql` to
`000001_init.up.sql`; for Alembic or other ORMs' tools run it with `op.execute`. Next changes become `V2__...sql`;
never edit an applied file. In the compose stack the databases are `postgres-account` and `postgres-media`:

```
psql "postgresql://account:<password>@localhost:5432/account" -f postgres/account/V1__init.sql
```

**MongoDB.** `mongosh "mongodb://localhost:27017" --file mongo/init.js` creates the collections with their validators
and indexes. It is idempotent: existing collections get their validator updated, indexes are only created when
missing. Change `catalog.json`, then `node mongo/build-init.mjs` to regenerate `init.js`.

**Elasticsearch.** `ES_URL=http://localhost:9200 sh elasticsearch/create-index.sh` creates `wallpapers-v1` behind the
alias `wallpapers`.

**Redis.** Nothing to create; `redis/keys.yaml` is the contract for key names, types, fields and TTLs.

## Rules that apply to every store

- **Ids** are the public ids of the API (`ast_`, `wp_`, `col_`, `ntf_` + ULID) and Keycloak UUIDs, stored as text (as
  uuid in Postgres where the column holds a user id). The database never generates them, except for internal
  sequence ids (`outbox_event.id`, `audit_log.id`, `media_variant.id`).
- **Time** is UTC: `timestamptz` in Postgres, BSON `date` in Mongo, epoch milliseconds in Redis, `date` in Elasticsearch.
  The JSON examples in the README show the API form (ISO-8601 strings).
- **Optimistic locking** uses an integer `version` that the application increments on every write. It is the ETag
  (`"<version>"`) and the `If-Match` check; there are no triggers for it. Writers use
  `UPDATE ... WHERE id = ? AND version = ?` (Postgres) or `{_id, version}` as the filter (Mongo).
- **Validation limits** repeat the OpenAPI ones (username 3-30, display name 1-60, bio 500, title 100, 20 tags of at
  most 30 characters, and so on) so that no code path can store what the API would have refused. When you change a
  limit, change it in the OpenAPI spec and here.
- **Soft delete** exists only for users (`users.deleted_at`, purged after 30 days). Other services react to
  `account.user.deleted.v1` by removing their own data.

## PostgreSQL notes

- **account**: `users.id` equals the Keycloak `sub`. Soft-deleted users keep their username and email until purged, so
  nobody can take over a name while other services may still reference it. `outbox_event` has a partial index for the
  relay query of README 4.3 and an optional `LISTEN/NOTIFY` trigger; polling stays the safety net.
  `audit_log` is append-only.
- **media**: the state machine is enforced by constraints: `READY` needs width, height and sha256, and `reject_reason`
  is set exactly when the status is `REJECTED`. `phash` is a `bit(64)`, so near-duplicates are found without extensions:
  `WHERE bit_count(phash # $1::bit(64)) <= 6`. That is a scan; fine for a reference project, replace it with a BK-tree
  or vector index if it ever matters.
- `media_asset.created_by` from README 6.2's "every table carries ... created_by" is left out on purpose: `owner_id`
  is the creator of every row.

## MongoDB notes

- `$jsonSchema` validators use `additionalProperties: false`, so a misspelled field fails instead of silently
  being stored. Validation level is `strict` and the action is `error`.
- A `PUBLISHED` wallpaper must have at least one variant and object `dimensions` (README 4.1 step 7); this is an extra
  `$expr` check next to the `$jsonSchema`.
- Besides the README fields, `wallpapers` has `moderation` (the last decision), `viewCount` and `downloadCount` (flushed
  from the Redis counters every minute), and `version`. `GET` responses leave `moderation`, the counters and `version`
  out (`version` becomes the ETag).
- Search fallback: the `text_fallback` text index backs the degraded Mongo query used when Elasticsearch is down
  (README 8). It has `default_language: none` so German and Spanish text is not stemmed as English.
- Favorites: the unique `(userId, wallpaperId)` index makes `POST /wallpapers/{id}/favorite` idempotent. The keyset cursor
  of `GET /users/me/favorites` encodes `(createdAt, _id)` of the last item and walks the `user_created` index.
  Update `favoriteCount` in the same transaction as the favorite document when your deployment has a replica set;
  without one (the single-node compose setup) use the upsert result to decide whether to `$inc`, and accept that the
  counter can drift until the next reconciliation.
- `assetId` has the unique index `asset_uq`: one wallpaper per media asset, for every status, until the wallpaper is
  deleted. The service checks first and maps a duplicate-key error (E11000) from a concurrent create to the same
  `409 wallpaper.asset-already-used`. If you started the stack from an earlier version of this repo, drop the old
  non-unique index once (`db.wallpapers.dropIndex("asset")` in mongosh) or `make nuke`; `createIndexes` cannot change
  the options of an existing index key.

## Elasticsearch notes

- `dynamic: strict`; only `PUBLISHED` wallpapers are indexed, and a wallpaper that leaves that status is deleted from
  the index. The document id is the wallpaper id. `status` stays in the document as a safety filter.
- Index with `version` set to the Mongo `version` and `version_type=external_gte`: a late, out-of-order write can
  never overwrite newer data, and retries are harmless.
- Documents have `authorId` (a keyword) but not the whole author snapshot: the service loads wallpapers from Mongo by id
  after the search (`_source: false`), which is also where `favoritedByMe` comes from.
- `title.autocomplete` indexes edge n-grams of 1 to 20 characters and is searched with the plain folded analyzer.
- Paging uses `from`/`size`, so `page * size + size` must stay within `index.max_result_window` (10,000); deeper pages
  fail in Elasticsearch. Reject such pages with a 400 (there is no dedicated error code yet) or switch to `search_after`.
- Facets are terms aggregations named after the API's `FacetKey` values (`CATEGORY`, `TAG`).

## Redis notes

Four additions to README 6.5, each with a reason in `keys.yaml`:

1. `idem:{service}:{principal}:{key}` instead of `idem:{key}`: client-chosen keys are not unique across users, and one
   user must never be able to replay another user's stored response.
2. `dedup:{service}:{eventId}` for all consumers: catalog and media both consume `account.user.deleted.v1` from the
   shared Redis, so one shared `dedup:{eventId}` would make the second consumer skip the event.
3. `inbox:unread:{userId}`: unread filter and count in O(log n).
4. `conn:{userId}`: the limit of three connections per user has to hold across notification-service instances.

Retention of the inbox (newest 500 per user, 90 days) is a default I chose; README does not specify one.
