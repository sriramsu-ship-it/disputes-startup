# Stage notes: platform-core (audit, workflow, db extensions, CLI)

**Date:** 2026-11-07  **Branch:** `agent/platform-core`  **Author:** developer (platform-core)
All data synthetic. No network calls. Nothing under `src/disputes/` imports `synthgen`.

## What was built
| Path | What | Requirements |
|---|---|---|
| `src/disputes/db/migrations/0002_platform_core_insert_only.sql` | Row triggers reject UPDATE/DELETE and statement triggers reject TRUNCATE on `audit_events` and `case_artifacts`, for every role | ADR-003 §4, R-21, R-23, R-31 (no delete path) |
| `src/disputes/db/migrations/0003_platform_core_case_ids_jobs.sql` | `tenant_case_prefixes`, `case_id_counters`, job-queue partial indexes | ADR-002, case IDs |
| `src/disputes/db/repo.py` (added only) | `tenant_case_prefix`, `next_case_id`, `find_case_for_job` | |
| `src/disputes/audit/verify.py` | `verify_case`, `verify_all`, `triggers_present` (fixed names and return shapes for web) | R-21, ADR-003 §5 |
| `src/disputes/audit/anchor.py` | `write_anchor` (write-once, O_EXCL, chmod 0444), `latest_anchor`, `list_anchors` | R-21 anchor |
| `src/disputes/audit/reads.py` | `record_case_read(conn, *, tenant_id, case_id, user_id, role)`: CASE_READ for AUDITOR/ADMIN only | R-21 |
| `src/disputes/workflow/jobs.py` | enqueue, claim (`FOR UPDATE SKIP LOCKED` + lease), complete, fail with exponential backoff, dead-letter -> escalate case + `JOB_DEAD_LETTERED` audit event, lease reaper | ADR-002, fail safe |
| `src/disputes/workflow/pipeline.py` | `process_dispute`, `default_deps` per the docstring and PRD §6; `escalate_stuck_case` | §6 states, R-02..R-15 orchestration, R-21, R-29 |
| `src/disputes/workflow/worker.py` | `run_worker`, `process_one`, `default_deps_for` | ADR-002 |
| `src/disputes/cli.py` | `migrate`, `seed-demo`, `ingest`, `work`, `verify`, `anchor`, `backup`, `restore` | R-21 verify, R-32 |
| `scripts/backup_restore_drill.sh` | verify -> anchor -> pg_dump -> restore into a NEW db -> verify restored copy | R-32 |

### Case IDs
`<PREFIX>-<yyyymmdd>-<seq:05d>`, e.g. `ST0-20261107-00001`. PREFIX is derived from the tenant ID (initials of words, digit groups whole: `synthetic-tenant-0` -> `ST0`) and allocated once per tenant in `tenant_case_prefixes`, unique across tenants (a clash gets a numeric suffix: `ST12`). The sequence is per tenant per UTC day of the pipeline clock (`now`), incremented atomically (`INSERT ... ON CONFLICT DO UPDATE`). Per-tenant counters mean a client cannot infer another client's volume from case numbers.

### Pipeline behaviour (decisions taken where the docstring left room)
- Every DB step runs in its own `with conn.transaction()` with its audit event(s); a failed step rolls back.
- Duplicate control number (per tenant): no case, `repo.record_duplicate` + `DUPLICATE_IGNORED` (case_id NULL). A concurrent race that hits the unique index is also recorded as a duplicate (tested).
- INTAKE_INVALID stops at intake: no budget created, no LLM call (R-02). The pipeline also flags INTAKE_INVALID itself if either date is missing/not ISO even when the validator misses it (defence in depth).
- DOC_UNREADABLE and BREACHED are recorded and carried as upstream escalations; classification, investigation and draft still run for the reviewer; final state ESCALATED.
- Repeat link (R-04) runs right after classification because the repeat key is account + category. A repeat writes INTAKE artifact v2 with `repeat_of_case_id` and a `REPEAT_LINKED` event with the prior case's outcome; the case is still fully investigated.
- Routes: ESCALATE_FRAUD -> ESCALATED/ID_FRAUD_SUSPECTED, priority 100, no investigation, no draft. MULTI_ISSUE and CLASS_CONFLICT -> ESCALATED, no investigation. OUT_OF_SCOPE -> OUT_OF_SCOPE (ESCALATED instead if an upstream reason such as BREACHED exists).
- INVESTIGATE: claims (CLAIMS v1) -> months -> evidence -> comparison -> map claims (CLAIMS v2) -> decide (RULE_EVALUATED with firings, rules version, table versions) -> draft. Investigated cases are always drafted, including escalated ones (reviewer aid), unless the LLM is down.
- If drafting adds DRAFT_INVALID (or the LLM goes down at draft), `decide` is re-run with the new upstream reasons so the stored Decision (v2) matches the final escalation set.
- LlmUnavailable at any step: an `LLM_UNAVAILABLE` event, failed calls logged as MODEL_CALL, later LLM steps skipped, deterministic evidence + comparison (+ decision when classification exists) still stored, final ESCALATED/LLM_UNAVAILABLE (R-15).
- One `MODEL_CALL` event per `LlmCallRecord` in `budget.records` (actor MODEL, `model:<id>`), including failed attempts.
- Any other exception: `PIPELINE_ERROR` event (step, type, message, traceback hash), case -> ESCALATED with STATE_CHANGED reason `SYSTEM_ERROR`. Exceptions only escape if the DB fails while recording that; the worker then escalates the stuck case and retries/dead-letters the job.
- Refused before any write: tenant mismatch between the dispute and `tenant_id`; `synthetic != true` while `cfg.mode == "synthetic"` (ADR-009 §1).

## Tests (run)
Command: `cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q`
Result (full suite, this branch): **139 passed, 1 skipped** (76 pre-existing + 63 new platform-core tests + 1 skip), about 25 s wall clock on the shared 2-CPU box.
- `tests/test_platform_core_pipeline.py` (32 + 1 skip): happy VERIFY -> DRAFT_READY (all artifact kinds, 4 MODEL_CALL events, RULE_EVALUATED firings/table versions), MODIFY, intake invalid (no LLM), unparseable date, duplicate (+ per-tenant, + race), fraud (priority 100, no draft, queue order), out of scope (+ breached), multi-issue, class conflict, LLM unavailable at classify/claims/map/draft, draft invalid (decision v2), claim unresolved, months undetermined, unexpected exception in 6 different deps, repeat linking (inside and outside the 90-day window), breached + unreadable, HIGH suspicion recorded without changing outcome, non-synthetic/tenant refusal, case-ID format/uniqueness/prefix collision, repeated attachment IDs, a full run of every branch + anchor + `verify_all`, and `assert_audited` on every scenario (each STATE_CHANGED chains from RECEIVED to the final state, `verify_case` passes).
- `tests/test_platform_core_audit.py` (17): UPDATE/DELETE/TRUNCATE rejected on both tables; trigger disable detected; clean verify; tamper as superuser (disable trigger, edit payload, re-enable) -> exact first broken event_id from both `verify_case` and `verify_all`; payload+payload_sha256 forged -> case_hash break; deleted row -> break at the next event; **full consistent rewrite -> chains pass, anchor mismatch reported**; truncated tail -> anchor reports missing event; anchor write-once/0444/latest selection; empty log; CASE_READ for AUDITOR/ADMIN only and not across tenants.
- `tests/test_platform_core_jobs.py` (13): SKIP LOCKED with a second connection holding a row lock; lease; tenant-filtered claim; backoff then dead-letter -> case ESCALATED + JOB_DEAD_LETTERED; dead-letter with no case still audited; reaper requeue/dead + stale lease holder cannot complete; worker drains queue incl. a duplicate; unprocessable/non-synthetic payloads dead-lettered at once; DB failure escaping the pipeline -> stuck case escalated, retry, dead; CLI ingest of the 200-fixture set + 20 jobs worked; seed-demo with and without web auth; **backup -> restore into a new DB -> `verify_all` (chains, triggers, anchor) passes**; CLI `anchor`/`verify`/`migrate` as subprocesses, verify exits 1 after tampering.

Manual drill (run once, then cleaned up): migrate a scratch DB, seed-demo, ingest the 200 fixtures, worker with the **fake deps** (real modules are stubs), then `scripts/backup_restore_drill.sh`: 200 jobs done, 196 cases (4 duplicate control numbers in the fixture set), 3,301 events; the restored copy verified `ok` against the anchor at event 3301.

No agreement/eval numbers: platform-core has no model-driven step of its own. The pipeline has only been run end to end with fakes.

## Stubbed or faked
- Every intake/rules/agents function is still a stub on main; all pipeline tests use fake `Deps` (`Scenario` in `test_platform_core_pipeline.py`). `default_deps` imports the real modules lazily; its wiring test is **skipped** right now because `disputes/rules/evidence.py` imports `SystemOfRecord` from `disputes.contracts_bridge`, which does not export it (see contract request 2).
- The anchor store is a local directory (stand-in for an object-locked bucket); it gives no protection against someone with filesystem access. No scheduler: run `python -m disputes.cli anchor` every `anchor_interval_min` from cron/systemd.
- `seed-demo` creates tenants always; users and `staff_tenant_access` only when `disputes.web.auth.hash_password(password) -> str` and `new_totp_secret() -> str` exist (assumed signatures; tested with a monkeypatched stand-in). It prints the demo password and TOTP secrets (synthetic demo accounts, `@demo.invalid`).

## Known limits
- Insert-only triggers apply to every role, including the owner; a superuser can still disable them or drop the table. Row edits are caught by the chains; a full rewrite only by the anchor, and only for events at or before the latest anchor. There is no separate least-privilege app role yet (ADR-003 §4 "app role has INSERT and SELECT only" is not implemented; everything runs as `postgres`).
- `verify_all` reads the whole log into memory (fine at MVP volumes; stream with a server-side cursor before pilot volumes).
- ADR-002 says job completion, state change and audit event commit in one transaction. Here the pipeline commits step by step and `jobs.complete` commits afterwards; a crash between them re-runs the job, which records DUPLICATE_IGNORED against the finished case (harmless, visible).
- A dead-lettered job whose dispute never became a case (payload cannot be mapped) gets a `JOB_DEAD_LETTERED` audit event with case_id NULL but no case; ops must watch for that event type.
- The worker's `now` is real time unless the job payload carries `as_of` (`ingest --fixture-dates` uses each fixture's `ingest_date`, 15:00 UTC). Without it, the fixture due dates (early Nov 2026) are mostly BREACHED today.
- Default `DISPUTES_ANCHOR_DIR` is `/tmp/disputes-anchors`, shared by anyone on the host; set it per environment.

## Contract-change requests (for the integrator)
1. **`domain.EscalationReason`: add `SYSTEM_ERROR = "SYSTEM_ERROR"`.** Pipeline and dead-letter escalations currently have no value in the closed list, so `cases.escalation_reasons` keeps only the known reasons and the error is visible only in the `PIPELINE_ERROR` / `JOB_DEAD_LETTERED` events and the STATE_CHANGED reason. A supervisor queue filter for these cases needs the value. PRD §6 closed list would need the PM's sign-off. Proposed diff:
   ```diff
        LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
   +    SYSTEM_ERROR = "SYSTEM_ERROR"        # pipeline/job failure escalated fail-safe (ADR-002)
   ```
   After it lands, platform-core will add it to `run.reasons` in `_escalate_on_error` and `jobs._dead_letter`.
2. **`contracts_bridge.py`: re-export `SystemOfRecord`** (the rules stub imports it; currently an ImportError that breaks `default_deps` and `python -m disputes.cli work`):
   ```diff
   -    AcdvSource, Attachment, Dispute, FixtureAcdvSource, LlmClient, MockSystemOfRecord,
   +    AcdvSource, Attachment, Dispute, FixtureAcdvSource, LlmClient, MockSystemOfRecord, SystemOfRecord,
   ```
   (Or the rules agent imports it from `disputes_core.contracts`.)
3. Before any real data: a migration creating a `disputes_app` role with INSERT/SELECT only on `audit_events` and `case_artifacts` (ADR-003 §4), and running the app as that role.

## What the integrator needs to wire up
- After the agents/intake/rules PRs merge: un-skip check (`test_default_deps_wires_real_modules` should pass), then run `python -m disputes.cli migrate && seed-demo && ingest --tenant synthetic-tenant-0 --fixtures data/fixtures/seed20261019_n200 --fixture-dates && work && verify` against the real modules and check the fake-vs-real contract (especially `budget.records`, `inspect_attachments` returning `(findings, too_many)`, `find_repeat` returning the prior-case dict).
- Web: call `audit.verify.verify_case/verify_all`, `audit.reads.record_case_read`; human state changes still go through `workflow.state_machine.transition`.
- Ops: cron `disputes.cli anchor` every 15 min; daily `disputes.cli backup`; run `scripts/backup_restore_drill.sh` once before Phase 2 (R-32).
- `cases.priority = 100` marks ID fraud; `cases.repeat_of_case_id` the repeat link.
