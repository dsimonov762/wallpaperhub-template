# A0-A4 (docs/SERVICE-SPEC.md section 4). Variables: api_url, protected_path, good_token, tampered_token, wrong_aud_token

# A0 control: a valid token is not refused (otherwise a service that rejects everything would pass A1-A4)
GET {{api_url}}{{protected_path}}
Authorization: Bearer {{good_token}}
HTTP *
[Asserts]
status != 401
status < 500

# A1 no token
GET {{api_url}}{{protected_path}}
HTTP 401
[Asserts]
header "Content-Type" startsWith "application/problem+json"
header "WWW-Authenticate" startsWith "Bearer"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/unauthorized"
jsonpath "$.status" == 401

# A2 not a JWT
GET {{api_url}}{{protected_path}}
Authorization: Bearer this.is.not-a-jwt
HTTP 401
[Asserts]
header "Content-Type" startsWith "application/problem+json"

# A3 a real token with a changed signature
GET {{api_url}}{{protected_path}}
Authorization: Bearer {{tampered_token}}
HTTP 401

# A4 a real token of another audience (client credentials of {{bad_aud_client}})
GET {{api_url}}{{protected_path}}
Authorization: Bearer {{wrong_aud_token}}
HTTP 401
