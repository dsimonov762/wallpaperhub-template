# E1, E2, E4, E5, E6 (docs/SERVICE-SPEC.md section 5).
# Variables: api_url, good_token, list_path, list_token, trace_id, span_id, and the bundle texts
# en/de/es_not_found_title / _detail

# E1 unknown path: 404 not-found problem
GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
HTTP 404
[Asserts]
header "Content-Type" startsWith "application/problem+json"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/not-found"
jsonpath "$.status" == 404
jsonpath "$.instance" == "/api/v1/__conformance_not_found__"
jsonpath "$.traceId" matches /^[0-9a-f]{32}$/
# English by default
header "Content-Language" == "en"
jsonpath "$.title" == "{{en_not_found_title}}"
jsonpath "$.detail" == "{{en_not_found_detail}}"

# E2 traceId is the trace id of the incoming traceparent
GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
traceparent: 00-{{trace_id}}-{{span_id}}-01
X-Request-Id: conformance-{{trace_id}}
HTTP 404
[Asserts]
jsonpath "$.traceId" == "{{trace_id}}"
# E6 the request id comes back unchanged
header "X-Request-Id" == "conformance-{{trace_id}}"

# E6 and one is made up when the caller sends none
GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
HTTP 404
[Asserts]
header "X-Request-Id" exists

# E4 localization: first tag of Accept-Language, texts from contracts/i18n
GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
Accept-Language: de-DE,de;q=0.9,en;q=0.8
HTTP 404
[Asserts]
header "Content-Language" == "de"
jsonpath "$.title" == "{{de_not_found_title}}"
jsonpath "$.detail" == "{{de_not_found_detail}}"

GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
Accept-Language: es
HTTP 404
[Asserts]
header "Content-Language" == "es"
jsonpath "$.title" == "{{es_not_found_title}}"

# a language we do not have falls back to English
GET {{api_url}}/api/v1/__conformance_not_found__
Authorization: Bearer {{good_token}}
Accept-Language: fr
HTTP 404
[Asserts]
header "Content-Language" == "en"

# E5 a page size above 100 is refused, not clamped
GET {{api_url}}{{list_path}}
Authorization: Bearer {{list_token}}
[QueryStringParams]
size: 101
HTTP 400
[Asserts]
header "Content-Type" startsWith "application/problem+json"
jsonpath "$.code" == "pagination.size-too-large"
jsonpath "$.status" == 400
