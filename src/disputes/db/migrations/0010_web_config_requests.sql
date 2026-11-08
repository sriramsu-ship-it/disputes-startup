-- Web module (range 0010-0019). R-18 / R-21: a config change is proposed by one ADMIN and takes
-- effect only when a DIFFERENT ADMIN approves it ("no user can approve their own config change").
-- On approval the web service inserts the new row into config_versions (0001) and writes the
-- CONFIG_CHANGED audit event (old value, new value, proposer, approver, reason) in one transaction.
CREATE TABLE IF NOT EXISTS config_change_requests (
    request_id    bigserial PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES tenants(tenant_id),     -- 'ops' = platform-wide
    key           text NOT NULL,
    old_value     jsonb,
    new_value     jsonb NOT NULL,
    reason        text NOT NULL CHECK (length(btrim(reason)) >= 10),
    proposed_by   text NOT NULL REFERENCES users(user_id),
    proposed_at   timestamptz NOT NULL DEFAULT now(),
    status        text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by    text REFERENCES users(user_id),
    decided_at    timestamptz,
    decision_note text,
    CHECK (decided_by IS NULL OR decided_by <> proposed_by)
);
CREATE INDEX IF NOT EXISTS config_change_requests_status_idx ON config_change_requests (tenant_id, status);
