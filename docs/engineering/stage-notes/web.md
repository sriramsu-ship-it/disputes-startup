# Stage notes: web module (analyst workbench `/ops` + client portal `/client`)

**Date:** 2026-11-07  **Branch:** `agent/web`  **Owner:** developer (web)  **Data:** synthetic only

## What I built
| Requirement | Where | Notes |
|---|---|---|
| R-18 auth | `src/disputes/web/auth.py` | `hash_password(pw) -> str` (stdlib scrypt n=2^14,r=8,p=1, salted, params stored), `verify_password` (constant-time), `new_totp_secret() -> str`, `verify_totp` (pyotp, ±1 step), signed session cookie (itsdangerous, `Settings.session_secret`) with idle timeout from config `session_idle_timeout_min` (30), user re-read each request. Login = password, then TOTP (no TOTP secret = no login). Roles checked on the server. Staff see only `staff_tenant_access` tenants (ADMIN all client tenants, never `ops`); CLIENT_VIEWER only its tenant and only `/client`. `DISPUTES_DEV_SHOW_TOTP=1` shows the current code on the MFA page **only** in synthetic mode. CSRF token on every POST; HttpOnly + SameSite=Lax cookies (+Secure with `DISPUTES_COOKIE_SECURE=1` or mode=live); CSP `default-src 'self'` (no inline script/style), X-Frame-Options DENY. |
| R-16 queue + case view | `app.py`, `views.py`, `templates/ops_queue.html`, `ops_case.html` | Tenant switcher; queue via `db.repo.list_cases` (ID fraud first, then AT_RISK/BREACHED, then internal target), filters by state (open/all/each) and flag. Case view: ACDV as received, consumer text with claim-quote highlights (segments, never HTML), evidence side by side, month-by-month comparison, claim-to-evidence map (system vs reviewer findings), narrative sentences with source / template ID / evidence IDs / quote spans, validator errors, flags (suspicion level + matches, escalation reasons with R-29 rule ID, version and evidence IDs), deadline ruler (received, internal target, today, due) and clock state, prior linked case, reviewer record, packages, audit timeline. |
| R-17 actions | `actions.py` (service layer), routes `POST /ops/t/{t}/cases/{c}/actions/{action}` | APPROVE, EDIT (outcome, corrected fields, narrative, claim findings), ESCALATE, MARK_OUT_OF_SCOPE, plus take-for-review (ESCALATED to IN_REVIEW, supervisor) and reopen-after-submission. Opening a DRAFT_READY case moves it to IN_REVIEW and assigns it. Every EDIT / OUT_OF_SCOPE / reopen needs an Appendix C reason code + ≥10 chars; ESCALATE and REJECT_SECOND_APPROVAL need ≥10 chars. Approval blocked until: an approvable outcome is chosen, MODIFY has corrections, every claim lacking a valid finding has a human finding (SUPPORTED/CONTRADICTED need known evidence IDs, NOT_ADDRESSABLE needs a ≥10-char reason), and a human narrative exists when the validator failed / no draft / outcome or corrections differ from the proposal. Narrative ≤ `narrative_max_words`. State changes only via `workflow.state_machine.transition`; each action writes a `review` artifact + `REVIEW_ACTION` audit event in the same transaction; optimistic concurrency via the form's case version (409 on stale). |
| R-19 second approval | `actions.second_approve`, `reject_second_approval` | DELETE or HIGH suspicion -> AWAITING_SECOND_APPROVAL. Only a SUPERVISOR who has not APPROVED or EDITED the case (any time in its history) may second-approve or send back. |
| R-20 package | `actions._finalise` | Immutable package (outcome, corrections, narrative + sentences, `dfAuthorizedName`, approvals, versions, supersedes hash, change reason, synthetic) -> `StubResponseSink` + `package` artifact + `PACKAGE_WRITTEN` event; APPROVED -> SUBMITTED_STUB. Sink failure rolls back the whole approval (tested). Reopen (SUPERVISOR/ADMIN, reason required) -> next approval writes package v(n+1) with the reason and the previous package's hash; v1 untouched. |
| R-22 export | `export.py`, `templates/export.html` | JSON + print-friendly HTML from the same dict: case, dispute as received, deadline, timeline (events with hashes), intake/suspicion/classification, evidence with hashes + content, attachments with hashes + extracted text, comparison, claims (system + human findings), decision, every draft version with sentence sources, reviews, packages, versions (rules, templates, patterns, model IDs and prompt hashes found in audit payloads, artifact versions), reference-table versions + `verified`, hash-chain status from `audit.verify.verify_case`, content hash, generation time. |
| R-21 reads | `metrics.record_case_read` -> `disputes.audit.reads.record_case_read` | AUDITOR/ADMIN case view and export write CASE_READ. |
| R-21 admin | `configsvc.py`, `templates/ops_admin.html`, migration `0010_web_config_requests.sql` | Effective config = defaults overlaid by newest `config_versions` per key (tenant `ops`). One ADMIN proposes (reason ≥10), a **different** ADMIN approves/rejects (DB CHECK + code); approval inserts `config_versions` and writes `CONFIG_CHANGED` (old, new, proposer, approver, reason). `mode` and `llm_model_id` are locked (R-35 / R-30). |
| R-24 instrumentation | `metrics.py`, `static/review.js` | `opened`, `first_viewed`, `active_seconds` (Page Visibility + focus/blur + idle cutoff from config, beacon every 30 s and on hide; server caps 300 s per beacon, CSRF-checked), `decided` (seconds since first view, action, override flag, reason code, escalation reasons). CSV at `/ops/t/{t}/metrics.csv` for SUPERVISOR/ADMIN. |
| Client portal | `portal.py`, `templates/client_*.html` | Own tenant only (tenant from the user row, never the URL): SLA strip (open on-track / at-risk / breached, completed), counts by state and by outcome, case list with last-4 account, internal target vs bureau due date, status timeline (state changes only, actors shown as "Our analyst team"/"Platform"), audit export for completed cases (SUBMITTED_STUB, OUT_OF_SCOPE) with PII masked. |
| R-27 masking | `pii.py`, `__main__.py` | `mask_account`, `mask_text` (SSN-shaped, SYNACCT…, 8-19 digit runs, given names), `PiiMaskingFilter` installed on root/uvicorn loggers by `python -m disputes.web`. Staff views and staff exports are unmasked; the client export is masked. |
| Run | `src/disputes/web/__main__.py` | `python -m disputes.web` -> uvicorn on 127.0.0.1:8000. |
| Demo data | `src/disputes/web/demo.py` | Synthetic tenants/users/cases in 10 scenarios built with the domain dataclasses; refuses non-synthetic mode. Used by the tests; `python -m disputes.web.demo <db_url>` for local UI work. |

Design: a cool ink-on-paper case-file look (Charter/Georgia serif headings, system sans body, tabular figures), a ledger-teal primary, colour reserved for meaning (clock state, fraud, reviewer-entered). The one bold element is the deadline ruler on the case header plus a clock-state edge on each queue row. A hatched "Synthetic data" banner is on every page, including exports. Checked at 1280 px with headless Chrome (queue, case view, client portal); no console errors.

## Tests
Command: `cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q`
- Web tests: `tests/test_web_actions.py` (24), `tests/test_web_auth.py` (14), `tests/test_web_http.py` (17), fixtures in `tests/test_web_support.py`. Result of the web files alone: 55 passed.
- Full suite after rebase on origin/main (incl. platform-core #5, intake #2, rules #4, contract fixes #6, generator #8, agents #9): `599 passed in 120.54s`, EXIT=0; web files alone `55 passed in 12.62s`. Case view < 2 s and export < 10 s are asserted in tests (local, single-case).

## Stubbed, faked or limited
- **Sessions are stateless signed cookies**: logout clears the cookie, but a stolen cookie stays valid until its idle timeout (30 min). Server-side revocation needs a sessions table (could use 0011). Deactivating a user does take effect at once (user re-read per request).
- No login rate limiting / lockout yet (needed before any real user).
- Login form has no CSRF token (SameSite=Lax pending cookie only).
- No TOTP enrolment flow; secrets come from `cli seed-demo` / `demo.py`.
- Original attachment bytes are not stored by fixtures, so R-22's "zip bundle" is the attachment list with hashes and extracted text in the export.
- PDF rendering of the export: not built (print the HTML; print CSS provided).
- Names in free text are masked only when passed explicitly (pattern masking cannot find names).
- Client export masking: account numbers and the consumer's name masked; hashes refer to the unmasked originals.
- Clock state shown is `cases.clock_state` as stored by the pipeline; the web does not recompute it on read.
- Test data is inserted directly with `db.repo` (not through the pipeline).

## Decisions I made that the PM or integrator should confirm
1. **EDIT and APPROVE are separate actions.** Edits change the case's "working decision" (stored in the review artifact); APPROVE finalises it. A supervisor who EDITED or APPROVED a case can never give its second approval (whole case history, including earlier package versions).
2. **Every EDIT needs a reason code**, including narrative-only edits (NARRATIVE_EDIT_ONLY) and claim findings (CLAIM_FINDING_ENTERED). MARK_OUT_OF_SCOPE always needs one. ESCALATE needs text, code optional.
3. **Human narrative is required** when the outcome or corrections differ from the proposal (the template sentences would state the wrong outcome), not only when the validator failed.
4. **`dfAuthorizedName` = the final approver** (the second approver for two-approval cases); both approvers are listed in `approvals`.
5. **Second approval is SUPERVISOR-only** (ADMIN cannot second-approve), per R-19 wording.
6. **Config changes need two admins** (R-18 "nobody approves their own config change").
7. **Client sees internal states** (Escalated, In review…) in the portal and the masked export. PM: is that the right level of transparency for a managed-service client?

## Contract-change requests (for the integrator; not applied)
1. `domain.py`: define the `review` artifact's dataclass, which `ArtifactKind.REVIEW` references but does not define:
   ```python
   @dataclass(frozen=True)
   class ReviewRecord:
       action: str                      # ReviewAction value or "REOPEN_AFTER_SUBMISSION"
       actor_id: str
       actor_role: Role
       actor_name: str
       from_state: CaseState
       to_state: CaseState
       reason_code: str | None = None   # PRD Appendix C
       reason_text: str | None = None
       working: dict | None = None      # {outcome, corrections, claim_findings, narrative}
       extra: dict = field(default_factory=dict)  # stage, first_approver, changed, ...
   ```
   (The web currently writes the same keys flat, with `extra` keys at the top level.)
2. `domain.ReviewAction`: add `REOPEN_AFTER_SUBMISSION = "REOPEN_AFTER_SUBMISSION"` (used now as a string in `actions.REOPEN`).
3. `domain.Draft`: add `human_authored: bool = False`. Reviewer-written narratives are stored as new `draft` versions with `human_authored: true` and all sentences `source=HUMAN`.
4. `config.Settings`: add `cookie_secure: bool` from `DISPUTES_COOKIE_SECURE` (the web reads the env var directly for now).
5. Optional: move `configsvc.effective_config(conn)` into `disputes/config.py` (or `db`) so the pipeline and worker read the same effective values. Today only the web reads `config_versions`.

## What the integrator needs to wire up
- Run migrations (adds `0010_web_config_requests.sql`).
- `python -m disputes.web` (set `DISPUTES_SESSION_SECRET`; `DISPUTES_DEV_SHOW_TOTP=1` for demos). Create users with `cli seed-demo` (it uses `disputes.web.auth.hash_password` / `new_totp_secret`) or `python -m disputes.web.demo <db_url>`.
- The pipeline must write the artifacts the case view reads (`dispute` as `to_jsonable(Dispute)` with `consumer_name`, `intake`, `suspicion`, `classification`, `evidence`, `comparison`, `claims`, `decision`, `draft`) and set `cases.proposed_outcome`, `escalation_reasons`, `suspicion_level`, `priority`, `clock_state`, `internal_target_date`. Missing artifacts render as "none" rather than failing.
- Model IDs / prompt hashes in the versions block are collected from audit payload keys `model_id`, `prompt_template_id`, `prompt_sha256` (top level or under `llm_call`). If the agents module logs them under other keys, tell me or update `casedata.versions_for_case`.
- Clock refresh: if no job re-evaluates `cases.clock_state` daily, the queue's AT_RISK ordering goes stale.

## Threat notes (this surface)
Assets: unmasked dispute PII in staff views and exports, the approval authority, config. Trust boundaries: browser to app (session cookie, CSRF, CSP), staff vs client tenant scoping (server-side, per request), uploaded text rendered in the view (autoescape only, tested with `<script>` / `<img onerror>` payloads; quote highlights are segment lists, not HTML). Abuse cases covered by tests: client reading another tenant's case or export (404), staff without tenant access (404), auditor/client acting (403), self second approval (403), self config approval (403), forged or missing CSRF (403), stale form (409), injected text in letters (escaped; HIGH flag forces second approval, outcome unchanged). Open: login brute force (no rate limit), cookie theft window (no server revocation), RLS not yet enabled (ADR-008 pilot gate).
