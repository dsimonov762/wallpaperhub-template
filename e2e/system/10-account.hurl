# README 4.1 steps 1-3: register -> sign in -> read and edit the own profile.
# SYSTEM TEST: needs the real account service (and Keycloak, Postgres). The Prism mocks cannot pass it.
# Variables: base_url, keycloak_url, realm, client_id, run_id (run.sh generates it), alice_token

# Register. The password policy of the realm is length(8) and notUsername.
POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{
  "username": "e2e_{{run_id}}",
  "email": "e2e_{{run_id}}@example.test",
  "password": "Correct-horse-1",
  "displayName": "E2E {{run_id}}"
}
HTTP 201
[Captures]
new_user_id: jsonpath "$.id"
[Asserts]
jsonpath "$.username" == "e2e_{{run_id}}"
jsonpath "$.status" == "ACTIVE"
jsonpath "$.password" not exists

# Same username again -> 409 with the domain error code
POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{
  "username": "e2e_{{run_id}}",
  "email": "other_{{run_id}}@example.test",
  "password": "Correct-horse-1",
  "displayName": "E2E again"
}
HTTP 409
[Asserts]
header "Content-Type" startsWith "application/problem+json"
jsonpath "$.code" == "user.username-taken"
jsonpath "$.traceId" isString

# Sign in with the new account
POST {{keycloak_url}}/realms/{{realm}}/protocol/openid-connect/token
[FormParams]
grant_type: password
client_id: {{client_id}}
username: e2e_{{run_id}}
password: Correct-horse-1
HTTP 200
[Captures]
new_token: jsonpath "$.access_token"

# Own profile, with an ETag for optimistic locking
GET {{base_url}}/api/v1/users/me
Authorization: Bearer {{new_token}}
HTTP 200
[Captures]
etag1: header "ETag"
[Asserts]
jsonpath "$.id" == {{new_user_id}}
jsonpath "$.email" == "e2e_{{run_id}}@example.test"
header "ETag" exists

PATCH {{base_url}}/api/v1/users/me
Authorization: Bearer {{new_token}}
If-Match: {{etag1}}
Content-Type: application/json
{ "bio": "written by the e2e suite" }
HTTP 200
[Captures]
etag2: header "ETag"
[Asserts]
jsonpath "$.bio" == "written by the e2e suite"
header "ETag" != {{etag1}}

# The first ETag is stale now -> 409 request.version-conflict
PATCH {{base_url}}/api/v1/users/me
Authorization: Bearer {{new_token}}
If-Match: {{etag1}}
Content-Type: application/json
{ "bio": "second writer" }
HTTP 409
[Asserts]
jsonpath "$.code" == "request.version-conflict"

# Validation errors list the fields (RFC 9457 with errors[])
PATCH {{base_url}}/api/v1/users/me
Authorization: Bearer {{new_token}}
If-Match: {{etag2}}
Content-Type: application/json
{ "displayName": "" }
HTTP 400
[Asserts]
jsonpath "$.errors" isCollection
jsonpath "$.errors" count >= 1

# The gateway strips identity headers from the client: a spoofed X-User-Id must not change who the caller is
GET {{base_url}}/api/v1/users/me
Authorization: Bearer {{alice_token}}
X-User-Id: {{new_user_id}}
X-User-Roles: ADMIN
HTTP 200
[Asserts]
jsonpath "$.id" == "00000000-0000-4000-8000-000000000001"
jsonpath "$.username" == "alice"
