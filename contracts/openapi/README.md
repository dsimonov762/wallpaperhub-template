# OpenAPI contracts

One OpenAPI document per service, plus a shared one. They describe the REST API of README section 5.1 and
are the source of truth for it; the implementations (in any language) must match them.

| File | Service | Operations |
|---|---|---|
| `account.yaml` | account-service | registration, profile, avatar/banner, user admin, token refresh/logout |
| `media.yaml` | media-service | upload, list, get, presigned URL, delete |
| `catalog.yaml` | catalog-service | wallpapers, search, favorites, moderation, collections (optional) |
| `notification.yaml` | notification-service | inbox, preferences, stream tickets, SSE, WebSocket, admin test |
| `common.yaml` | none | shared parameters, headers, ids, `Problem`, error responses (no paths) |

Everything is language-agnostic. Use the specs to generate server stubs or clients, or only as a reference.

## Conventions

- **OpenAPI 3.0.3**, not 3.1: the widest tool support (code generators, Spectral, mock servers). Nullable fields
  use `nullable: true`.
- **Shared parts** are referenced as `$ref: 'common.yaml#/components/...'`. Most tools resolve that directly. If
  one does not, bundle first, for example `npx @redocly/cli bundle account.yaml -o dist/account.yaml`.
- **Server URL** is `/api/v1` (relative to the gateway); paths in the files have no prefix.
- **Errors** are always `application/problem+json` with the `Problem` schema. Every operation lists the
  statuses it can produce; 401 is listed everywhere except the public operations.
- **Versioning**: `If-Match`/`ETag` on every PUT and PATCH (a quoted integer version), `Idempotency-Key` on POSTs
  that create something.
- **Pagination**: offset (`page`, `size`, `sort=<field>,<asc|desc>`) with a whitelist of sort values per endpoint,
  except `GET /users/me/favorites`, which uses a cursor.
- **Language**: every operation accepts `Accept-Language` (`en`, `de`, `es`).

## Vendor extensions

| Extension | On | Meaning |
|---|---|---|
| `x-access` | operation | Who may call it: `public`, `authenticated`, `owner`, `owner-or-moderator`, `owner-or-admin`, `owner-or-internal`, `moderator`, `admin`. The gateway only checks the token; the service enforces this. |
| `x-error-codes` | operation | Domain error codes the operation can return in `Problem.code`. Each has a localized `error.<code>` text in `contracts/i18n`. |
| `x-optional` | operation, tag | Part of the optional second entity (collections). May be left out. |

`x-access` is also what the gateway config follows: `public` operations have JWT validation disabled in Envoy.

## Validation constraints and error codes

Schema constraints double as the validation rules, and a failed constraint is reported as a field error
(`Problem.errors[].code`) with the same text in every service:

| Schema keyword | Field error code |
|---|---|
| required / `nullable: false` | `NotNull` (`NotBlank` for strings) |
| `minLength` (with `minLength: 1`) | `NotBlank` |
| `minLength` / `maxLength` | `Size` / `MaxLength` |
| `minimum` / `maximum` | `Min` / `Max` |
| `pattern` | `Pattern` |
| `format: email` | `Email` |
| `maxItems` | `MaxItems` |
| `enum` | `OneOf` |
| password rules | `PasswordPolicy` |

## Out of scope

- The gRPC API of account-service (`contracts/proto`) and the Kafka events (`contracts/avro`).
- GraphQL (`contracts/graphql`), which exposes the catalog data a second way.
- Management endpoints (`/actuator/*`, `/health`, `/metrics`) and the Keycloak endpoints; the
  `/auth/refresh` and `/auth/logout` operations of account-service are thin wrappers for teaching purposes.
