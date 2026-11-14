-- account-service schema (README 6.1). PostgreSQL 14+ (the compose stack runs 18).
-- Plain SQL: Flyway, Liquibase (sql format), golang-migrate, Alembic (op.execute), Atlas, dbmate or psql all accept it.
-- Conventions: snake_case, timestamptz in UTC, text instead of varchar(n) with CHECK constraints for limits.
-- `version` and `updated_at` are maintained by the application (optimistic locking, ETag = "<version>"), never by triggers.

CREATE TABLE users (
    id               uuid        PRIMARY KEY,                       -- equal to the Keycloak `sub`; never generated here
    username         text        NOT NULL,
    email            text        NOT NULL,
    display_name     text        NOT NULL,
    bio              text,
    locale           text        NOT NULL DEFAULT 'en',
    avatar_asset_id  text,                                          -- media-service asset id; no FK across services
    banner_asset_id  text,
    status           text        NOT NULL DEFAULT 'ACTIVE',
    deleted_at       timestamptz,                                   -- soft delete; purged after 30 days (README 9)
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    version          bigint      NOT NULL DEFAULT 0,

    CONSTRAINT users_username_format  CHECK (username ~ '^[a-z0-9_]{3,30}$'),
    CONSTRAINT users_email_format     CHECK (email = lower(email) AND char_length(email) BETWEEN 3 AND 254 AND email LIKE '%_@_%'),
    CONSTRAINT users_display_name_len CHECK (char_length(display_name) BETWEEN 1 AND 60),
    CONSTRAINT users_bio_len          CHECK (bio IS NULL OR char_length(bio) <= 500),
    CONSTRAINT users_locale_values    CHECK (locale IN ('en', 'de', 'es')),
    CONSTRAINT users_status_values    CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    CONSTRAINT users_avatar_asset_fmt CHECK (avatar_asset_id IS NULL OR avatar_asset_id ~ '^ast_[0-9A-HJKMNP-TV-Z]{26}$'),
    CONSTRAINT users_banner_asset_fmt CHECK (banner_asset_id IS NULL OR banner_asset_id ~ '^ast_[0-9A-HJKMNP-TV-Z]{26}$'),
    CONSTRAINT users_version_nonneg   CHECK (version >= 0)
);

-- Soft-deleted rows keep their username and email until the purge job removes them, so a name cannot be taken over
-- while Keycloak or other services may still reference it.
CREATE UNIQUE INDEX users_username_uq ON users (username);
CREATE UNIQUE INDEX users_email_uq    ON users (email);
-- GET /users (admin): newest first, optional status filter and `q` prefix search on username/display name.
CREATE INDEX users_created_idx        ON users (created_at DESC, id) WHERE deleted_at IS NULL;
CREATE INDEX users_username_prefix_idx ON users (username text_pattern_ops) WHERE deleted_at IS NULL;
-- gRPC ListUsersUpdatedSince.
CREATE INDEX users_updated_idx        ON users (updated_at, id) WHERE deleted_at IS NULL;
-- Daily purge of users soft-deleted more than 30 days ago.
CREATE INDEX users_deleted_idx        ON users (deleted_at) WHERE deleted_at IS NOT NULL;

COMMENT ON TABLE  users IS 'Profile of a registered user. Credentials live in Keycloak only.';
COMMENT ON COLUMN users.id IS 'UUID, equal to the Keycloak sub claim.';
COMMENT ON COLUMN users.email IS 'Stored lower-case. PII: only the owner, admins and the internal gRPC API see it.';
COMMENT ON COLUMN users.deleted_at IS 'Soft delete marker. Every read path treats such a user as not existing.';
COMMENT ON COLUMN users.version IS 'Optimistic lock counter, exposed as the ETag "<version>" and checked via If-Match.';

-- ---------------------------------------------------------------------------------------------------------------------
-- Transactional outbox (README 4.3). Rows are inserted in the same transaction as the domain change.
CREATE TABLE outbox_event (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- relay order; the README's "bigserial"
    event_id        uuid        NOT NULL,                                   -- becomes the `event-id` header and Avro eventId
    aggregate_type  text        NOT NULL,                                   -- 'user'
    aggregate_id    text        NOT NULL,                                   -- Kafka message key
    event_type      text        NOT NULL,                                   -- 'UserRegistered', 'UserProfileUpdated', 'UserDeleted'
    topic           text        NOT NULL,                                   -- e.g. 'account.user.registered.v1'
    payload         jsonb       NOT NULL,                                   -- JSON form of the Avro record; Avro-encoded when published
    headers         jsonb       NOT NULL DEFAULT '{}'::jsonb,               -- traceparent, correlation-id
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz,
    attempts        integer     NOT NULL DEFAULT 0,
    last_error      text,

    CONSTRAINT outbox_event_id_uq        UNIQUE (event_id),
    CONSTRAINT outbox_topic_format       CHECK (topic ~ '^account\.[a-z]+\.[a-z-]+\.v[0-9]+$'),
    CONSTRAINT outbox_payload_is_object  CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT outbox_headers_is_object  CHECK (jsonb_typeof(headers) = 'object'),
    CONSTRAINT outbox_attempts_nonneg    CHECK (attempts >= 0)
);

-- The relay query: WHERE published_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED.
CREATE INDEX outbox_unpublished_idx ON outbox_event (id) WHERE published_at IS NULL;
-- Cleanup of rows published more than 7 days ago.
CREATE INDEX outbox_published_idx   ON outbox_event (published_at) WHERE published_at IS NOT NULL;

COMMENT ON TABLE outbox_event IS 'Events waiting for, or already given to, Kafka. At-least-once: consumers dedupe on event_id.';

-- Optional wake-up for the relay: LISTEN outbox_event. NOTIFY is delivered on commit, so it never announces rows that
-- are not visible yet. Polling every 500 ms stays as the safety net, because notifications are not durable.
CREATE FUNCTION outbox_notify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('outbox_event', NEW.id::text);
    RETURN NULL;
END;
$$;

CREATE TRIGGER outbox_event_notify
    AFTER INSERT ON outbox_event
    FOR EACH ROW EXECUTE FUNCTION outbox_notify();

-- ---------------------------------------------------------------------------------------------------------------------
-- Audit trail of administrative and profile changes. Append only.
CREATE TABLE audit_log (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id     uuid,                                                      -- NULL for system actions (purge job, relay)
    action       text        NOT NULL,                                      -- 'USER_REGISTERED', 'PROFILE_UPDATED', 'USER_DELETED', ...
    entity_type  text        NOT NULL,                                      -- 'user'
    entity_id    text        NOT NULL,
    before       jsonb,
    after        jsonb,
    trace_id     text,                                                      -- W3C trace id, to jump to Tempo
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT audit_action_format   CHECK (action ~ '^[A-Z][A-Z0-9_]*$'),
    CONSTRAINT audit_trace_id_format CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$')
);

CREATE INDEX audit_entity_idx ON audit_log (entity_type, entity_id, created_at DESC);
CREATE INDEX audit_actor_idx  ON audit_log (actor_id, created_at DESC) WHERE actor_id IS NOT NULL;

COMMENT ON TABLE audit_log IS 'Who changed what and when. before/after hold the changed profile fields, never credentials.';
