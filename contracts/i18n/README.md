# i18n contract

Every service localizes error text and emails from these three bundles, so the same request gets the same
words whichever language the service is written in.

| File | Content |
|---|---|
| `messages.en.json`, `messages.de.json`, `messages.es.json` | Flat `key -> text`. Same keys, same order, same placeholders in all three. |
| `format-tests.json` | Test vectors for the placeholder syntax: `{template, args, expected}`. Run them against your formatter. |

English is the fallback: use it when `Accept-Language` names no supported language or a key is missing
(a missing key is a bug, the repository checks keep the three files in sync).

## Placeholder syntax

Deliberately tiny so it takes ten lines in any language:

- `{name}` is replaced by the argument `name` (letters and digits, starting with a letter, case sensitive).
- `{{` and `}}` produce a literal `{` and `}`.
- Everything is one left-to-right pass: replaced values are not scanned again, there is no nesting, no plural
  rules and no number or date formatting. A missing argument leaves `{name}` in the text (and should be logged).
- Arguments are strings. Pass numbers as plain decimals without grouping (`1000000`), and pass anything that
  needs localizing (a reason, a field label) already resolved from another key.

Reference implementation:

```python
import re
_TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z][A-Za-z0-9]*)\}")

def fmt(template: str, args: dict) -> str:
    def sub(m):
        if m.group(0) == "{{": return "{"
        if m.group(0) == "}}": return "}"
        return str(args[m.group(1)]) if m.group(1) in args else m.group(0)
    return _TOKEN.sub(sub, template)
```

## Which key goes where

| Where | Key |
|---|---|
| Problem `title` (RFC 9457) | `problem.<slug>.title` |
| Problem `detail` | `error.<code>` when the exception carries a domain code, else `problem.<slug>.detail` |
| `errors[].message` of a field error | `validation.<code>` with `field` set to the label `field.<name>` (the raw name if there is no label) plus the rule's arguments (`min`, `max`, ...) |
| Email | `email.greeting` + the event's `email-body` (+ `notification.wallpaper-moderated.reason-line` when there is a reason) + `email.signature` + `email.footer`, separated by blank lines; subject from `email-subject` |
| In-app inbox | `inbox-title` and `inbox-body` of the same event |

`<slug>` is the exception name from README 5.3 in kebab-case without `Exception`, except that
`ValidationException` is `validation-failed` (README 5.2): `unauthorized`, `forbidden`, `not-found`, `conflict`,
`payload-too-large`, `unsupported-media`, `rate-limited`, `upstream-unavailable`, plus `internal-error` for 500.
`<code>` is `AppException.code`, for example `media.asset-not-owned`. The gateway uses the same problem slugs and
English titles for the errors it generates itself.

Notification events and their keys (`notification.<event>.*`):

| Event | Kafka topic | Arguments |
|---|---|---|
| `welcome` | `account.user.registered.v1` | `name` |
| `wallpaper-published` | `catalog.wallpaper.published.v1` | `title` |
| `wallpaper-moderated.<DECISION>` | `catalog.wallpaper.moderated.v1` | `title`, `reason` (line only) |
| `asset-rejected` | `media.asset.rejected.v1` | `reason` = the text of `media.reject-reason.<reasonCode>`, falling back to `OTHER` |
| `digest` | weekly job, no topic | `items` = `item` lines joined with `\n`; `item` takes `title`, `author` |

Every event except `digest` has an inbox pair. Emails for `welcome` and `digest` use `{name}`; the service fills
it with the display name, or the username when there is none.

## Style

German and Spanish address the reader informally (du, tú) and avoid gendered placeholders: Spanish messages
say "El campo {field} ..." and the Spanish field labels are lower case because they sit mid-sentence. The
translations were written by Claude, not by a professional translator: have a native speaker review them
before anything real depends on them.

## Adding a language

Copy `messages.en.json`, translate every value (keep the placeholders), add the locale to `supportedLocales` in
the Keycloak realm, and extend the checks.
