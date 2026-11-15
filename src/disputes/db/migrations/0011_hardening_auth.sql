-- Migration 0011 (hardening, web range 0010-0019). R-18 login hardening, server-side sessions,
-- invites/TOTP enrolment. These are platform tables (users are global, not tenant-owned).
-- Secrets are never stored in clear: session and invite tokens are stored as SHA-256 hashes;
-- login attempts are keyed by a SHA-256 of the normalised email (R-27: no raw emails in these rows).

-- Server-side sessions. The cookie holds a random token; the row is keyed by sha256(token).
-- stage MFA_PENDING = password accepted, waiting for TOTP (5 min); ACTIVE = signed in.
CREATE TABLE web_sessions (
    session_hash    text PRIMARY KEY,
    user_id         text NOT NULL REFERENCES users(user_id),
    stage           text NOT NULL CHECK (stage IN ('MFA_PENDING', 'ACTIVE')),
    csrf            text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,                 -- absolute lifetime
    revoked_at      timestamptz,
    revoked_reason  text,
    source_ip       text,
    mfa_failures    integer NOT NULL DEFAULT 0
);
CREATE INDEX web_sessions_user_live_idx ON web_sessions (user_id) WHERE revoked_at IS NULL;

-- Login attempts (operational, not audit): rate limiting and lockout across web tasks.
CREATE TABLE auth_attempts (
    id           bigserial PRIMARY KEY,
    at           timestamptz NOT NULL DEFAULT now(),
    kind         text NOT NULL CHECK (kind IN ('PASSWORD', 'TOTP', 'INVITE', 'UNLOCK')),
    account_key  text NOT NULL,          -- sha256(lower(email)), or 'invite' for invite attempts
    source_ip    text NOT NULL,
    success      boolean NOT NULL
);
CREATE INDEX auth_attempts_account_idx ON auth_attempts (account_key, at);
CREATE INDEX auth_attempts_ip_idx ON auth_attempts (source_ip, at);

-- One-time invite / sign-in reset links. The user sets a password and enrols TOTP.
CREATE TABLE user_invites (
    token_hash           text PRIMARY KEY,
    user_id              text NOT NULL REFERENCES users(user_id),
    purpose              text NOT NULL CHECK (purpose IN ('INVITE', 'RESET')),
    created_by           text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    expires_at           timestamptz NOT NULL,
    used_at              timestamptz,
    revoked_at           timestamptz,
    pending_totp_secret  text
);
CREATE INDEX user_invites_user_idx ON user_invites (user_id);

-- TOTP replay protection: the last accepted 30-second step per user.
ALTER TABLE users ADD COLUMN totp_last_step bigint;
