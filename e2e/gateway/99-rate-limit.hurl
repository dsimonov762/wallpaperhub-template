# POST /api/v1/registrations allows 10 requests per minute per client IP and gateway instance (envoy.yaml).
# Run this file LAST and alone: it empties the bucket of your IP, so a registration right after it is answered 429 for up to a minute.
# The body is invalid on purpose: it only has to get past the gateway, whatever the service answers is irrelevant.
POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP *

POST {{base_url}}/api/v1/registrations
Content-Type: application/json
{"username":"x"}
HTTP 429
[Asserts]
header "Retry-After" exists
header "Content-Type" startsWith "application/problem+json"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/rate-limited"
jsonpath "$.status" == 429
