# README 4.1 steps 4-9: upload -> processing -> create wallpaper -> idempotent retry -> search -> favorite.
# SYSTEM TEST: needs media + catalog + Kafka + Elasticsearch + S3 running for real (profiles infra + apps).
# Variables: base_url, run_id, alice_token, upload_png (path of the unique picture run.sh generated, relative to the file root)

# Not an image behind a .png name: refused from the content, not the name (magic bytes)
POST {{base_url}}/api/v1/media
Authorization: Bearer {{alice_token}}
[MultipartFormData]
purpose: WALLPAPER
file: file,fixtures/not-an-image.png; image/png
HTTP 415
[Asserts]
jsonpath "$.code" == "media.unsupported-type"

# A valid picture is accepted for processing
POST {{base_url}}/api/v1/media
Authorization: Bearer {{alice_token}}
[MultipartFormData]
purpose: WALLPAPER
file: file,{{upload_png}}; image/png
HTTP 202
[Captures]
asset_id: jsonpath "$.assetId"
[Asserts]
jsonpath "$.status" == "PROCESSING"

# The media worker finishes asynchronously (validation, variants, blurhash)
GET {{base_url}}/api/v1/media/{{asset_id}}
Authorization: Bearer {{alice_token}}
[Options]
retry: 30
retry-interval: 2s
HTTP 200
[Asserts]
jsonpath "$.status" == "READY"
jsonpath "$.width" >= 1920
jsonpath "$.height" >= 1080
jsonpath "$.variants" count >= 1
jsonpath "$.blurhash" isString

# Create the wallpaper with an Idempotency-Key
POST {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
Idempotency-Key: e2e-{{run_id}}-create
Content-Type: application/json
{
  "assetId": "{{asset_id}}",
  "title": "E2E Sunrise {{run_id}}",
  "description": "created by the e2e suite",
  "tags": ["e2e", "sunrise"],
  "category": "NATURE"
}
HTTP 201
[Captures]
wallpaper_id: jsonpath "$.id"
[Asserts]
header "Location" contains "/wallpapers/"
jsonpath "$.status" matches /^(PENDING_MEDIA|PUBLISHED)$/
jsonpath "$.author.username" == "alice"

# Retry with the same key and body: the first response is replayed, no second wallpaper
POST {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
Idempotency-Key: e2e-{{run_id}}-create
Content-Type: application/json
{
  "assetId": "{{asset_id}}",
  "title": "E2E Sunrise {{run_id}}",
  "description": "created by the e2e suite",
  "tags": ["e2e", "sunrise"],
  "category": "NATURE"
}
HTTP 201
[Asserts]
jsonpath "$.id" == {{wallpaper_id}}

# Same key, different body -> 409
POST {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
Idempotency-Key: e2e-{{run_id}}-create
Content-Type: application/json
{
  "assetId": "{{asset_id}}",
  "title": "A different title",
  "tags": [],
  "category": "SPACE"
}
HTTP 409
[Asserts]
jsonpath "$.code" == "idempotency.key-reused"

# One asset, one wallpaper: a second wallpaper for the same asset is refused, even with a fresh Idempotency-Key
POST {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
Idempotency-Key: e2e-{{run_id}}-create-second
Content-Type: application/json
{
  "assetId": "{{asset_id}}",
  "title": "Second try {{run_id}}",
  "tags": [],
  "category": "NATURE"
}
HTTP 409
[Asserts]
jsonpath "$.code" == "wallpaper.asset-already-used"

# A wallpaper asset cannot be linked as an avatar: purpose mismatch, nothing changes
PUT {{base_url}}/api/v1/users/me/avatar
Authorization: Bearer {{alice_token}}
Content-Type: application/json
{ "assetId": "{{asset_id}}" }
HTTP 409
[Asserts]
jsonpath "$.code" == "media.asset-purpose-mismatch"

# Catalog consumes the media.ready event and publishes
GET {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}
Authorization: Bearer {{alice_token}}
[Options]
retry: 30
retry-interval: 2s
HTTP 200
[Asserts]
jsonpath "$.status" == "PUBLISHED"
jsonpath "$.variants" count >= 1
jsonpath "$.dimensions.width" >= 1920

# Search is eventually consistent (catalog -> Kafka -> Elasticsearch indexer)
GET {{base_url}}/api/v1/wallpapers/search
Authorization: Bearer {{alice_token}}
[Options]
retry: 30
retry-interval: 2s
[QueryStringParams]
q: {{run_id}}
facets: CATEGORY,TAG
HTTP 200
[Asserts]
jsonpath "$.items[0].id" == {{wallpaper_id}}
jsonpath "$.facets" count == 2

# Favorite, twice (naturally idempotent), then remove
POST {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}/favorite
Authorization: Bearer {{alice_token}}
HTTP 200
[Asserts]
jsonpath "$.favorited" == true
jsonpath "$.favoriteCount" == 1

POST {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}/favorite
Authorization: Bearer {{alice_token}}
HTTP 200
[Asserts]
jsonpath "$.favoriteCount" == 1

GET {{base_url}}/api/v1/users/me/favorites
Authorization: Bearer {{alice_token}}
HTTP 200
[Asserts]
jsonpath "$.items[0].id" == {{wallpaper_id}}

DELETE {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}/favorite
Authorization: Bearer {{alice_token}}
HTTP 200
[Asserts]
jsonpath "$.favorited" == false
jsonpath "$.favoriteCount" == 0

# Moderation is for MODERATOR and ADMIN only: alice is a plain USER
POST {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}/moderation
Authorization: Bearer {{alice_token}}
Content-Type: application/json
{ "decision": "REMOVED" }
HTTP 403
[Asserts]
jsonpath "$.type" == "https://wallpaperhub.dev/problems/forbidden"

# Moderator removes it; the author is notified and the wallpaper disappears for others
POST {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}/moderation
Authorization: Bearer {{mod_token}}
Content-Type: application/json
{ "decision": "REMOVED", "reason": "e2e cleanup" }
HTTP 200
[Asserts]
jsonpath "$.status" == "REMOVED"

# The author cannot delete a removed wallpaper (it would free the asset for a repost) ...
DELETE {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}
Authorization: Bearer {{alice_token}}
HTTP 409
[Asserts]
jsonpath "$.code" == "wallpaper.removed-by-moderation"

# ... a moderator can, which also cleans up after this test
DELETE {{base_url}}/api/v1/wallpapers/{{wallpaper_id}}
Authorization: Bearer {{mod_token}}
HTTP 204

GET {{base_url}}/api/v1/notifications
Authorization: Bearer {{alice_token}}
[Options]
retry: 20
retry-interval: 2s
[QueryStringParams]
unread: true
HTTP 200
[Asserts]
jsonpath "$.items[?(@.type=='WALLPAPER_MODERATED')]" count >= 1
