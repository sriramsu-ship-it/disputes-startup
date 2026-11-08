-- Migration 0003 (platform-core): readable per-tenant case IDs and job-queue indexes.
-- Case ID format: <PREFIX>-<yyyymmdd>-<seq:05d>, e.g. ST0-20261107-00001.
-- PREFIX is allocated once per tenant and is UNIQUE across tenants (cases.case_id is a global key).
-- The sequence is per tenant per day, so case numbers never reveal another client's volume.

CREATE TABLE tenant_case_prefixes (
    tenant_id  text PRIMARY KEY REFERENCES tenants(tenant_id),
    prefix     text NOT NULL UNIQUE CHECK (prefix ~ '^[A-Z0-9]{2,12}$')
);

CREATE TABLE case_id_counters (
    tenant_id  text NOT NULL REFERENCES tenants(tenant_id),
    day        date NOT NULL,
    last_seq   integer NOT NULL,
    PRIMARY KEY (tenant_id, day)
);

-- Claim path: QUEUED jobs of a kind ready to run (tenant filter optional).
CREATE INDEX jobs_ready_idx ON jobs (kind, run_after, job_id) WHERE status = 'QUEUED';
-- Lease reaper path.
CREATE INDEX jobs_running_idx ON jobs (locked_until) WHERE status = 'RUNNING';
CREATE INDEX jobs_tenant_idx ON jobs (tenant_id, status);
