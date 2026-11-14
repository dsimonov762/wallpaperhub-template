# Preflight from an allowed origin is answered by the gateway without a token
OPTIONS {{base_url}}/api/v1/wallpapers
Origin: http://localhost:5173
Access-Control-Request-Method: POST
Access-Control-Request-Headers: authorization,content-type,idempotency-key
HTTP *
[Asserts]
status < 300
header "Access-Control-Allow-Origin" == "http://localhost:5173"
header "Access-Control-Allow-Methods" contains "POST"
header "Access-Control-Allow-Headers" contains "idempotency-key"
header "Access-Control-Max-Age" == "600"

# Gateway-generated errors still carry the CORS headers, so the browser can read the 401 and start a token refresh
GET {{base_url}}/api/v1/users/me
Origin: http://localhost:5173
HTTP 401
[Asserts]
header "Access-Control-Allow-Origin" == "http://localhost:5173"
header "Access-Control-Expose-Headers" contains "retry-after"
