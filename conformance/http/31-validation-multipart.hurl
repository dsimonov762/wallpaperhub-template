# E3 for services whose create operation is a multipart upload (media): the file part is missing.
# Variables: api_url, validation_path, validation_token, de_validation_title
POST {{api_url}}{{validation_path}}
Authorization: Bearer {{validation_token}}
Accept-Language: de
[MultipartFormData]
purpose: BOGUS
HTTP 400
[Asserts]
header "Content-Type" startsWith "application/problem+json"
header "Content-Language" == "de"
jsonpath "$.type" == "https://wallpaperhub.dev/problems/validation-failed"
jsonpath "$.title" == "{{de_validation_title}}"
jsonpath "$.errors" count >= 1
