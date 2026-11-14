# M1-M4 (docs/SERVICE-SPEC.md section 2). Variables: api_url, mgmt_url
GET {{mgmt_url}}/health/live
HTTP 200
[Asserts]
header "Content-Type" startsWith "application/json"
jsonpath "$.status" == "UP"

GET {{mgmt_url}}/health/ready
HTTP 200
[Asserts]
jsonpath "$.status" == "UP"

GET {{mgmt_url}}/health/startup
HTTP 200
[Asserts]
jsonpath "$.status" == "UP"

# M4: the management endpoints are not served on the API port
GET {{api_url}}/health/live
HTTP *
[Asserts]
status != 200
