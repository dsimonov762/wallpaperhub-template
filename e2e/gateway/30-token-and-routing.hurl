# Keycloak issues a token the gateway accepts (password grant is enabled for client e2e-tests only, local realm)
POST {{keycloak_url}}/realms/{{realm}}/protocol/openid-connect/token
[FormParams]
grant_type: password
client_id: {{client_id}}
username: alice
password: password
HTTP 200
[Captures]
alice_token: jsonpath "$.access_token"
[Asserts]
jsonpath "$.token_type" == "Bearer"

# Valid token -> the request reaches the account service (or its mock): not a gateway 401/403/404/5xx
GET {{base_url}}/api/v1/users/me
Authorization: Bearer {{alice_token}}
HTTP 200
[Asserts]
header "X-Request-Id" exists
header "X-RateLimit-Limit" exists

# Each route family reaches its own upstream
GET {{base_url}}/api/v1/wallpapers
Authorization: Bearer {{alice_token}}
HTTP 200

GET {{base_url}}/api/v1/media
Authorization: Bearer {{alice_token}}
HTTP 200

GET {{base_url}}/api/v1/notifications
Authorization: Bearer {{alice_token}}
HTTP 200

# With a valid token an unknown path is a 404 problem+json from the gateway
GET {{base_url}}/api/v1/does-not-exist
Authorization: Bearer {{alice_token}}
HTTP 404
[Asserts]
header "Content-Type" startsWith "application/problem+json"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/not-found"
# security headers are also on responses the gateway generates itself, not only on routed ones
header "X-Content-Type-Options" == "nosniff"
header "X-Frame-Options" == "DENY"
header "Strict-Transport-Security" exists
