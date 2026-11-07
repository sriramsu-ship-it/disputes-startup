-- Disputes platform schema v1 (ADR-001, ADR-002, ADR-003, ADR-008 rev 2026-11-07).
-- Every table carries tenant_id (multi-tenant managed service; app-enforced scoping now,
-- Postgres RLS required before any real data — see ADR-008 revision).
-- Migrations are applied in order by disputes.db.core.migrate(); this file is migration 0001.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Furnisher clients we run disputes for. "ops" is our own operations org (analysts).
CREATE TABLE tenants (
    tenant_id     text PRIMARY KEY,
    display_name  text NOT NULL,
    synthetic     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    user_id        text PRIMARY KEY,
    email          text NOT NULL UNIQUE,
    display_name   text NOT NULL,
    role           text NOT NULL CHECK (role IN ('SPECIALIST','SUPERVISOR','ADMIN','AUDITOR','CLIENT_VIEWER')),
    -- NULL for our staff (they work across client tenants they are assigned to);
    -- set for CLIENT_VIEWER (exactly one tenant).
    tenant_id      text REFERENCES tenants(tenant_id),
    password_hash  text NOT NULL,
    totp_secret    text,
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (role <> 'CLIENT_VIEWER' OR tenant_id IS NOT NULL)
);

-- Staff assignment to client tenants (which clients an analyst may work).
CREATE TABLE staff_tenant_access (
    user_id    text NOT NULL REFERENCES users(user_id),
    tenant_id  text NOT NULL REFERENCES tenants(tenant_id),
    PRIMARY KEY (user_id, tenant_id)
);

CREATE TABLE cases (
    case_id              text PRIMARY KEY,
    tenant_id            text NOT NULL REFERENCES tenants(tenant_id),
    channel              text NOT NULL,                  -- ACDV | REG_V_DIRECT
    control_number       text,
    cra                  text,
    account_number       text,
    account_last4        text,
    date_received        date,
    response_due_date    date,
    internal_target_date date,
    clock_state          text,                           -- ON_TRACK | AT_RISK | BREACHED
    state                text NOT NULL,
    categories           text[] NOT NULL DEFAULT '{}',
    escalation_reasons   text[] NOT NULL DEFAULT '{}',
    proposed_outcome     text,
    final_outcome        text,
    suspicion_level      text NOT NULL DEFAULT 'NONE',
    priority             integer NOT NULL DEFAULT 0,     -- 100 = ID_FRAUD_SUSPECTED (R-07/R-16)
    repeat_of_case_id    text REFERENCES cases(case_id),
    assigned_to          text REFERENCES users(user_id),
    raw_payload_sha256   text NOT NULL,
    synthetic            boolean NOT NULL,
    version              integer NOT NULL DEFAULT 1,     -- optimistic concurrency
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
-- R-04: a control number is unique per tenant; duplicates create no case.
CREATE UNIQUE INDEX cases_tenant_control_uq ON cases (tenant_id, control_number) WHERE control_number IS NOT NULL;
CREATE INDEX cases_queue_idx ON cases (tenant_id, state, priority DESC, internal_target_date);
CREATE INDEX cases_repeat_idx ON cases (tenant_id, account_number, date_received);

-- R-04 duplicates are logged, not cased.
CREATE TABLE duplicate_intakes (
    id                  bigserial PRIMARY KEY,
    tenant_id           text NOT NULL REFERENCES tenants(tenant_id),
    control_number      text NOT NULL,
    original_case_id    text NOT NULL REFERENCES cases(case_id),
    raw_payload_sha256  text NOT NULL,
    received_at         timestamptz NOT NULL DEFAULT now()
);

-- Versioned, insert-only per-case artifacts (see domain.ArtifactKind).
CREATE TABLE case_artifacts (
    id           bigserial PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES tenants(tenant_id),
    case_id      text NOT NULL REFERENCES cases(case_id),
    kind         text NOT NULL,
    version      integer NOT NULL,
    data         jsonb NOT NULL,
    data_sha256  text NOT NULL,
    created_by   text NOT NULL,                          -- user_id, 'system' or 'model:<id>'
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, kind, version)
);

-- Original attachment bytes/text (R-22 bundle). Synthetic fixtures store extracted text only.
CREATE TABLE attachments (
    tenant_id       text NOT NULL REFERENCES tenants(tenant_id),
    case_id         text NOT NULL REFERENCES cases(case_id),
    attachment_id   text NOT NULL,
    file_name       text NOT NULL,
    media_type      text NOT NULL,
    page_count      integer NOT NULL,
    sha256          text NOT NULL,
    extracted_text  text NOT NULL,
    metadata        jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (case_id, attachment_id)
);

-- R-21 / ADR-003 audit log. Insert-only (trigger added in migration 0002 by the audit module).
CREATE TABLE audit_events (
    event_id          bigserial PRIMARY KEY,
    tenant_id         text NOT NULL,
    case_id           text,
    event_type        text NOT NULL,
    actor_type        text NOT NULL CHECK (actor_type IN ('SYSTEM','MODEL','HUMAN')),
    actor_id          text NOT NULL,
    actor_role        text,
    occurred_at       timestamptz NOT NULL,
    payload           jsonb NOT NULL,
    payload_sha256    text NOT NULL,
    case_prev_hash    text,
    case_hash         text,
    global_prev_hash  text NOT NULL,
    global_hash       text NOT NULL,
    schema_version    integer NOT NULL DEFAULT 1
);
CREATE INDEX audit_case_idx ON audit_events (case_id, event_id);
CREATE INDEX audit_tenant_idx ON audit_events (tenant_id, event_id);

-- ADR-002 job queue (claimed with FOR UPDATE SKIP LOCKED).
CREATE TABLE jobs (
    job_id        bigserial PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES tenants(tenant_id),
    case_id       text REFERENCES cases(case_id),
    kind          text NOT NULL,
    payload       jsonb NOT NULL DEFAULT '{}',
    status        text NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','RUNNING','DONE','DEAD')),
    attempts      integer NOT NULL DEFAULT 0,
    max_attempts  integer NOT NULL DEFAULT 3,
    run_after     timestamptz NOT NULL DEFAULT now(),
    locked_until  timestamptz,
    last_error    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claim_idx ON jobs (status, run_after);

-- Config versions (R-21 ADMIN events). tenant_id 'ops' = platform-wide.
CREATE TABLE config_versions (
    id          bigserial PRIMARY KEY,
    tenant_id   text NOT NULL REFERENCES tenants(tenant_id),
    key         text NOT NULL,
    value       jsonb NOT NULL,
    version     integer NOT NULL,
    changed_by  text NOT NULL,
    reason      text NOT NULL,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, key, version)
);

-- R-24 instrumentation (operational, not audit; 90-day retention R-31).
CREATE TABLE case_metrics (
    id          bigserial PRIMARY KEY,
    tenant_id   text NOT NULL REFERENCES tenants(tenant_id),
    case_id     text NOT NULL REFERENCES cases(case_id),
    user_id     text REFERENCES users(user_id),
    metric      text NOT NULL,          -- opened | first_viewed | active_seconds | decided
    value       double precision,
    detail      jsonb NOT NULL DEFAULT '{}',
    at          timestamptz NOT NULL DEFAULT now()
);

INSERT INTO tenants (tenant_id, display_name, synthetic) VALUES ('ops', 'Platform operations', true)
ON CONFLICT DO NOTHING;
