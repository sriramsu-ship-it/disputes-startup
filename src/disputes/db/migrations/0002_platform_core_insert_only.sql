-- Migration 0002 (platform-core): audit_events and case_artifacts are insert-only (ADR-003 §4, R-21, R-23).
-- UPDATE and DELETE are rejected row by row; TRUNCATE is rejected by a statement trigger.
-- Applies to EVERY role, including the owner: there is no delete path (R-23).
-- Limit (stated): a superuser can still ALTER TABLE ... DISABLE TRIGGER or rewrite rows; the
-- hash chains detect row edits and the external anchor detects a full rewrite (audit/verify.py).
-- `audit/verify.py` reports whether these triggers exist and are enabled.

CREATE OR REPLACE FUNCTION platform_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is insert-only (ADR-003, R-21, R-23): % rejected', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER audit_events_insert_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION platform_reject_mutation();
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION platform_reject_mutation();

CREATE TRIGGER case_artifacts_insert_only
    BEFORE UPDATE OR DELETE ON case_artifacts
    FOR EACH ROW EXECUTE FUNCTION platform_reject_mutation();
CREATE TRIGGER case_artifacts_no_truncate
    BEFORE TRUNCATE ON case_artifacts
    FOR EACH STATEMENT EXECUTE FUNCTION platform_reject_mutation();
