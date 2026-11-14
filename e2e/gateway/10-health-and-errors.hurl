# Gateway-level facts. They hold with real services AND with the Prism mocks, because the gateway itself answers.

# Gateway health (answered by Envoy, aggregates the upstream health checks)
GET {{base_url}}/health
HTTP 200
[Asserts]
header "X-Request-Id" exists
jsonpath "$.status" == "UP"

# No token on a protected route -> 401 problem+json produced by the gateway (README 3.1, 8.1)
GET {{base_url}}/api/v1/users/me
HTTP 401
[Asserts]
header "Content-Type" startsWith "application/problem+json"
header "WWW-Authenticate" startsWith "Bearer"
header "X-Request-Id" exists
header "X-Content-Type-Options" == "nosniff"
header "X-Frame-Options" == "DENY"
header "Strict-Transport-Security" exists
jsonpath "$.type" == "https://wallpaperhub.dev/problems/unauthorized"
jsonpath "$.status" == 401
# gateway errors carry requestId, not traceId (contract: common.yaml Problem)
jsonpath "$.requestId" isString
jsonpath "$.traceId" not exists

# Garbage bearer token -> 401, never forwarded
GET {{base_url}}/api/v1/wallpapers
Authorization: Bearer not.a.jwt
HTTP 401
[Asserts]
header "Content-Type" startsWith "application/problem+json"

# A client-supplied X-Request-Id is replaced by the gateway (no log forging)
GET {{base_url}}/health
X-Request-Id: attacker-chosen-id
HTTP 200
[Asserts]
header "X-Request-Id" != "attacker-chosen-id"

# Anything outside the public routes needs a token first: an unknown path is a 401, so the gateway does not reveal
# which routes exist. (404 for unknown paths is checked with a token in 30-token-and-routing.hurl)
GET {{base_url}}/does-not-exist
HTTP 401
[Asserts]
header "Content-Type" startsWith "application/problem+json"
