# Seed data

A small, realistic dataset for local development: **12 users, 30 wallpapers, 41 media assets, 48 favorites, 5 collections, 43 notifications**,
loaded consistently into Keycloak, Postgres (account, media), MongoDB, Elasticsearch, Redis (both instances) and S3.
The ids you need (users, wallpapers, assets) are in [CATALOG.md](CATALOG.md).

```bash
make up            # infrastructure + schemas (once)
make seed          # fill every store; safe to repeat
make reset         # DELETE all data in every store (asks first; YES=1 skips the question)
make reseed        # reset, then seed: the same known state every time
```

All seeded users log in with the password `password`:

| user | role | what it is good for |
|---|---|---|
| `alice` | USER | the main author: 9 wallpapers (one of them REMOVED by moderation), banner and avatar, two unread notifications (published, moderated) |
| `mod` | MODERATOR | moderation endpoints, one wallpaper of its own (`de`) |
| `admin` | ADMIN | admin endpoints (`es`) |
| `bob`, `carol`, `grace`, `heidi`, `erin` | USER | authors in `en`, `de` and `es`; bob has e-mail notifications off, carol has the digest off |
| `dave` | USER | wallpapers in every failure state: rejected by moderation (`w13`) and rejected by the media pipeline as too small (`w24`) |
| `frank` | USER, SUSPENDED | disabled in Keycloak; his published wallpaper stays visible |
| `ivan` | USER | soft-deleted 20 days ago (a row in account, not in Keycloak): the purge job's work item |
| `judy` | USER | brand new: no wallpaper, one unread welcome notification (empty states) |

States covered: wallpapers `PUBLISHED` (25), `PENDING_MEDIA` (2, asset still `PROCESSING`), `REJECTED` (2), `REMOVED` (1); an asset stuck in `PROCESSING` for
3 hours (orphan cleanup); titles and descriptions in three languages with accents (to exercise the folding analyzer of the Elasticsearch mapping); read and unread inbox entries with titles
and bodies rendered from `contracts/i18n` in the recipient's language; moderation entries in the catalog audit; `zset:trending` filled.

## What "seed", "reset" and "reseed" do

* **seed** inserts what is missing and never overwrites: Postgres `ON CONFLICT DO NOTHING` in one transaction, Mongo `$setOnInsert` upserts (the `$jsonSchema` validators
  stay active, so a document the schema rejects fails the job), Elasticsearch bulk `create` (409 = already there), Redis `HSET`/`ZADD` with the same values, S3 mirror,
  Keycloak partial import with `ifResourceExists: SKIP`. Run it twice and nothing changes. Rows you edited stay as you left them.
* **reset** empties: every Postgres table of the `public` schema except the bookkeeping tables of migration tools (Flyway, Liquibase, Alembic, goose, ...), every Mongo
  collection, the Elasticsearch index, both Redis instances (`FLUSHALL`: caches and rate limits too), both buckets, and every Keycloak user except `alice`, `mod` and
  `admin`. Schemas, indexes, validators, the realm and its clients, Kafka topics and Schema Registry subjects stay.
* **reseed** = reset + seed.

The jobs only reach the compose network (`infra/data/*.sh`, compose profile `data`), they cannot touch anything else. Seeding writes the stores directly and publishes
no Kafka events: consumers do not see "new" users or wallpapers, they only see the data. Services holding cached data from before (Redis caches survive a `seed`)
should be restarted; `make reset` flushes Redis.

Your own service must accept this data: the seed is written against `contracts/db-schema`, not against any implementation. If your service uses other table names
than the canonical schema, either keep the canonical schema (`make schemas`, drop your own V1) or adapt `seed/out/*.sql`.

## How it is built

`dataset.yaml` is the only file you edit. `python seed/build.py` (`make seed-build`; needs `seed/requirements.txt` or Docker) turns it into:

```
seed/out/        account.sql media.sql catalog.js catalog.es.ndjson notification.redis shared.redis keycloak-users.json manifest.json
seed/s3/         originals/** and public/** with the object keys of the buckets (variants: FULL, PREVIEW 1280w, THUMBNAIL 320w, WebP q80;
                 avatars 512/128/48; banners 1500x500 and 750x250)
seed/images.lock.json   what is derived from the pixels (perceptual hash, blurhash, palette) and the parameters each picture was made from
seed/CATALOG.md  the readable id table
```

Everything is committed, so `make seed` needs nothing beyond the images the stack already pulled. The pictures are generated procedurally (hills, waves, blurs, star
fields, skylines, circuit traces, minimal shapes, geometric animals), so there is no licensing question and no binary you cannot reproduce.

* Ids are deterministic: users have the fixed UUIDs `00000000-0000-4000-8000-0000000000NN` (the first three are the realm export's), the others are ULIDs derived from
  the keys of the dataset and the (fixed) dates. The same token `sub` equals `users.id` equals `wallpapers.author.id`.
* Dates are fixed relative to `anchor` in `dataset.yaml`, not to "now", so the output is stable and reviewable. Move the anchor to move everything.
* A picture is only rendered when it is missing or its parameters changed (`images.lock.json`); `python seed/build.py --regen` renders all again.
* `make seed-check` (also in CI) fails when `seed/out` or an image is out of date and validates the data without any database: the `$jsonSchema` validators and `$expr`
  rule of `contracts/db-schema/mongo/catalog.json`, the strict Elasticsearch mapping, the Redis key catalogue, and cross-store consistency (favoriteCount equals the number
  of favorites, Elasticsearch holds exactly the PUBLISHED wallpapers, every asset exists with the right status, every image file exists with the right sha256).
  `make seed-test-sql` (and the CI job `seed`) loads the SQL twice into a real Postgres on top of the canonical schema.

## Changing the dataset

Add a wallpaper: one line under `wallpapers:` (`a` author, `t` title, `c` category, `m` motif, `p` three colours, `size`, `ago`, `pop`, `tags`, `d`; optional `status`, `mod`,
`asset_reject`), then `make seed-build seed-check` and commit `seed/`. If you change a Postgres, Mongo, Elasticsearch or Redis contract, `make seed-check` tells you which part of
the seed no longer fits.
