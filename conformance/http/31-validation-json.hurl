# E3 (docs/SERVICE-SPEC.md section 5) for services whose create operation takes JSON, and L3: the body carries a
# password and an e-mail address that must never reach the logs.
# Variables: api_url, validation_path, validation_token, de_validation_title
POST {{api_url}}{{validation_path}}
Authorization: Bearer {{validation_token}}
Accept-Language: de
Content-Type: application/json
{"password":"conformance-secret-pw","email":"leak-check@example.test"}
HTTP 400
[Asserts]
header "Content-Type" startsWith "application/problem+json"
header "Content-Language" == "de"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/validation-failed"
jsonpath "$.title" == "{{de_validation_title}}"
jsonpath "$.errors" count >= 1
jsonpath "$.errors[0].field" isString
jsonpath "$.errors[0].code" isString
jsonpath "$.errors[0].message" isString
