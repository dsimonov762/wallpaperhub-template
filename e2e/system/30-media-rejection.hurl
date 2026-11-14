# README 5.2 media rules: a valid PNG that is too small is accepted, then rejected by the worker with a reason code.
# SYSTEM TEST: needs the real media service and its worker.
POST {{base_url}}/api/v1/media
Authorization: Bearer {{alice_token}}
[MultipartFormData]
purpose: WALLPAPER
file: file,fixtures/tiny-100x100.png; image/png
HTTP 202
[Captures]
tiny_id: jsonpath "$.assetId"

GET {{base_url}}/api/v1/media/{{tiny_id}}
Authorization: Bearer {{alice_token}}
[Options]
retry: 30
retry-interval: 2s
HTTP 200
[Asserts]
jsonpath "$.status" == "REJECTED"
jsonpath "$.rejectReason" matches /^(TOO_SMALL|DUPLICATE)$/

# A rejected asset cannot back a wallpaper
POST {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
Content-Type: application/json
{ "assetId": "{{tiny_id}}", "title": "never", "tags": [], "category": "OTHER" }
HTTP 409
[Asserts]
jsonpath "$.code" == "media.asset-rejected"
