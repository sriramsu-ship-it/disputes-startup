# Stage notes: hardening (Level 1 hosted demo, synthetic data only)

**Date:** 2026-11-15  **Branch:** `agent/hardening`  **Owner:** developer (hardening)  **Data:** synthetic only

Goal: make the web app and worker safe and correct enough to put on the internet for prospects
(DECISIONS 2026-11-14). This is **not** a pilot-readiness claim: RLS, per-tenant keys, an app DB
role without UPDATE/DELETE on audit tables, and an independent isolation test are still required
before any real data (ADR-008 revision, R-37).

## What I built
| # | Item | Where | Notes |
|---|---|---|---|
| 1 | Login rate limiting and lockout (R-18) | `web/auth.py`, migration `0011_hardening_auth.sql` (`auth_attempts`) | Per account: 5 password-or-TOTP failures in 15 min lock the account (even the right password then gets 429). Keyed by sha256(lower(email)) whether or not the account exists, so lockout does not reveal which emails exist; no raw email stored. The moment an existing account becomes locked writes one ACCOUNT_LOCKED audit event (R-18 v1.3: lockouts audited; unknown emails never write audit events). Only a full sign-in (TOTP success) or an admin unlock resets the count, so knowing the password does not allow unlimited TOTP guesses. Per source address: 30 failures in 15 min -> 429 for every account. Check + verify + record run under `pg_advisory_xact_lock(account)`, so limits hold across several web tasks. A pending (password-ok) session dies after 5 bad codes. Same message for unknown email, wrong password and inactive user; dummy scrypt for unknown emails (timing). Constant-time compares for passwords, TOTP (all three window steps are compared), CSRF. |
| 1 | Client address behind a load balancer | `auth.client_ip` | Socket peer by default. `DISPUTES_TRUSTED_PROXY_HOPS=N` takes the address N entries from the right of X-Forwarded-For (left entries are client-controlled). With `cli serve` (deploy) uvicorn already rewrites the peer from X-Forwarded-For when the connection comes from `DISPUTES_FORWARDED_ALLOW_IPS`; **use one of the two, not both** (recommend: uvicorn's, scoped to the VPC CIDR; leave HOPS=0). |
| 1 | TOTP replay protection | `auth.consume_totp`, `users.totp_last_step` | A code (30 s step) is accepted once per user. |
| 2 | Server-side sessions | `auth.SessionStore`, `web_sessions` | Cookie = 256-bit random token; DB stores only its SHA-256. Stages MFA_PENDING (5 min, cookie path `/login`) and ACTIVE. New token at the password step and again after MFA; any session the browser presented is revoked at login (no fixation). Idle timeout = `Config.session_idle_timeout_min` (30), absolute lifetime 12 h. Logout, admin "End sessions", deactivation and sign-in reset revoke rows; every request re-reads the row and the user. HttpOnly, SameSite=Lax; with `Settings.cookie_secure` also Secure and the `__Host-` cookie prefix. `Settings.session_secret` is no longer used to sign anything (deploy's hosting check still requires a strong one; harmless). |
| 3 | User administration + first login (R-18, R-21, R-38, R-39) | `web/admin_users.py`, routes `/ops/admin/users*`, `/invite/{token}`, templates `ops_users.html`, `invite.html`, `cli invite-admin` | ADMIN creates staff (with client-tenant assignments) or CLIENT_VIEWER (exactly one client tenant, never `ops`); deactivate; reset sign-in (clears password + TOTP, revokes sessions, new link); end sessions; unlock; change staff tenant access (old/new audited). New users have no usable password; the ADMIN gets a one-time link (72 h, only its hash stored, shown once; we never email). The link page shows the TOTP key and the `otpauth://` URI as text (no QR: no new dependency, no third-party QR service). Setting the password + confirming a code happens in one step. Every action writes an audit event (USER_CREATED, USER_DEACTIVATED, USER_SIGNIN_RESET, USER_SESSIONS_REVOKED, USER_UNLOCKED, STAFF_ACCESS_CHANGED, USER_ENROLLED, SIGNED_IN, SIGNED_OUT). An ADMIN cannot deactivate or reset themselves. `cli invite-admin --email --name` bootstraps the first ADMIN. |
| 3 | Password policy | `auth.password_policy_errors` | >= 12 and <= 256 chars, not the email, not a short common list, >= 4 distinct characters. In `DISPUTES_ENV=demo` the published seeded password (`synthetic-demo-pass`, and `DISPUTES_DEMO_PASSWORD` if set) is refused when setting a password, **and an account still on `synthetic-demo-pass` cannot sign in in demo** (it gets "ask an admin for a reset link"). In `dev` the seeded password keeps working (local demo, `seed-demo`, tests). |
| 4 | Clock refresh (R-05, STATUS known issue 2) | `workflow/clock_refresh.py`; `worker.clock_pass`; `cli work --loop` runs it every `--clock-refresh-s` (default 300); `cli refresh-clocks [--as-of]` one pass | Re-evaluates open cases with `intake.clock.compute_clock`. Writes only on change (clock state or internal target): updates the case and appends CLOCK_STATE_CHANGED with from/to, due date, target, evaluated_at, business days to target, holiday/time-zone table versions, rule id/version and the config offsets used. No `cases.version` bump (a clock flip must not 409 a reviewer's form). Multi-worker safe: per-case `FOR UPDATE SKIP LOCKED` + compare in the same transaction; a session advisory lock lets one worker run a pass at a time. One failing case is logged and skipped. Closed cases (SUBMITTED_STUB, OUT_OF_SCOPE) are not re-evaluated. **Newly BREACHED (PRD v1.3 §6.1 Q13):** BREACHED added to `escalation_reasons`, priority raised to 50 (after ID fraud at 100, before the rest), and the case moved to ESCALATED by the state machine (actor `system:clock-refresh`, reason BREACHED) unless already ESCALATED. The reviewer's working decision is kept; their stale form gets 409. AT_RISK never changes state or version. Interval: 300 s default, inside Q13's 15-min ceiling. |
| 5 | Client portal "completed" (STATUS known issue 1) | `web/portal.py`, `client_dashboard.html`, `client_case.html` | Definition, stated in the UI: **completed = closed: responded (SUBMITTED_STUB) or closed out of scope (OUT_OF_SCOPE)** (R-40 categories; exactly the cases R-41 lets the client download). The outcomes panel counts each completed case once under its final outcome, or "Out of scope" for pipeline OUT_OF_SCOPE cases (which have no `final_outcome`), so it always sums to the tile. |
| 5 | Client-facing statuses (PRD v1.3 §6.1 Q11) | `portal.client_status`, `client_timeline`, client templates | Received / In review / Response ready (not sent) / Out of scope: returned to you, with one plain-English line under "In review" (e.g. "Escalated to a supervisor: evidence conflict"). The client timeline shows headline changes only. The audit export keeps internal states. "Needs your action" (R-42 handoff) is not built. |
| 5 | R-39 / R-37 | `app.py` | Every client case view and export download writes CASE_READ (role CLIENT_VIEWER, surface). Any unsafe request (POST/PUT/PATCH/DELETE, any path, including paths that do not exist) carrying a CLIENT_VIEWER session gets 403 and a CLIENT_WRITE_DENIED event, except `/logout`. A request for another tenant's (or a non-existent) case answers 404 and writes ACCESS_DENIED in the requester's own scope (client tenant, or `ops` for staff), never into the other tenant's case chain. |
| 5 | Client export content check | `test_hardening_portal.py` | On a pipeline-run, approved fixture case: the client export contains model IDs and prompt **hashes** (R-22 allows), no prompt text, no other tenant, no config, no R-24/R-45 metrics, no credentials; account numbers masked. Analyst names still appear in `reviews` (Q16 is an open contract decision, not an R-39 violation). |
| 6 | Shared effective config | `workflow/effective_config.py`; `configsvc.effective_config` delegates to it | Web, worker (`run_worker(cfg_loader=...)` re-reads before each job; `work --loop` uses it) and the clock refresh read the same `config_versions` values. A stored value of the wrong type is ignored (default kept, warning logged) instead of crashing the worker. Two-admin approval unchanged. |
| 7 | Domain types | `actions.py`, `casedata.review_to_json / review_from_json`, `pipeline.py` | Review artifacts are built as `domain.ReviewRecord` and stored in the **same flat JSON shape** as before (`extra` keys at top level), so existing exports and hashes are unchanged; `review_from_json` reads flat and nested forms. `REOPEN = ReviewAction.REOPEN_AFTER_SUBMISSION`. Reviewer narratives are `Draft(human_authored=True)`. `Classification.llm_suspicious` is set in the pipeline right after classify from `budget.suspicious_flag` (a one-line `replace`, guarded for non-dataclass fakes). |
| 8 | Headers, limits, errors, logs | `app.py` | CSP verified and tightened (`base-uri 'none'`, `object-src 'none'`; no inline script/style anywhere, test-enforced on all templates); X-Frame-Options DENY, nosniff, Referrer-Policy same-origin, COOP/CORP same-origin, Permissions-Policy; HSTS (1 year, includeSubDomains) when `cookie_secure`. Body limit 1 MiB (`DISPUTES_MAX_BODY_BYTES`), enforced on Content-Length and on streamed bodies (413). Unhandled errors: generic 500 page with a request ID, never a stack trace; the log line has the error type, masked message and file:line frames only. Structured JSON request log (`disputes.web.request`: request ID, method, path with invite tokens redacted, status, duration, client address, user ID) through the R-27 masking filter. uvicorn's raw access log is off (`access_log=False` in `cli serve` and `python -m disputes.web`) because it would record invite tokens. `/docs`, `/redoc`, `/openapi.json` stay 404. |
| 8 | CSRF defence in depth | `app.py` | Besides the per-session token: any unsafe request whose `Sec-Fetch-Site` is `cross-site` or whose `Origin` is not this host (or `DISPUTES_ALLOWED_ORIGINS`) gets 403. This also covers the pre-session forms (login, MFA, invite), which have no session token. |

## Tests (what I ran)
Command: `cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q -p no:cacheprovider; echo EXIT=$?`

New files: `tests/test_hardening_auth.py` (20), `test_hardening_admin.py` (9), `test_hardening_clock_config.py` (11),
`test_hardening_portal.py` (9), `test_hardening_attacker.py` (16). Changed to fit server-side sessions:
`tests/test_web_support.py` (`csrf_of` reads the session row; `login` clears the last TOTP step so a
test can sign the same user in twice), `tests/test_web_auth.py` (codec tests replaced by session-store tests).

Results: see the PR description for the final full-suite run and the `scripts/demo_native.sh` end-to-end run.

## Attacker self-review (each has a test in `test_hardening_attacker.py` / `test_hardening_auth.py`)
| Attempt | Result |
|---|---|
| CSRF: missing / forged / another user's token | 403, case unchanged |
| CSRF: valid token but cross-site Origin, `Origin: null`, `Sec-Fetch-Site: cross-site` | 403 |
| Login CSRF (cross-site POST to /login and /login/mfa) | 403 (was possible before: login had no token) |
| Session fixation (planted cookie) | planted ID never stored; new IDs at password step and after MFA; pending token is not a session |
| Stolen cookie after logout | dead (server-side revoke). Before: valid until idle timeout |
| TOTP replay (observer reuses a code) | refused |
| Brute force / password spray | account lockout (5/15 min), per-address throttle (30/15 min); spoofed X-Forwarded-For ignored unless proxies are trusted |
| Account enumeration | same message and status for unknown / wrong / inactive; lockout identical for non-existent emails |
| IDOR staff (other tenant via own-tenant URL, export, actions, metrics beacon) | 404 + ACCESS_DENIED, nothing written |
| IDOR client (guessed case IDs, /ops URLs) | 404 / 403, nothing of tenant B shown |
| Forced browsing, every role x admin / users / metrics / queue / client / docs | matrix test, all as expected |
| Read-only roles acting (AUDITOR, CLIENT_VIEWER) | 403 (client also audited) |
| Stored XSS via letter text, reviewer narrative, reason text, user display name | escaped in case view, staff export HTML and users page; no inline script/style/handlers in any template |
| Oversized / streamed bodies | 413 |
| Error leakage | generic 500 with request ID; log masked |

**Found and fixed while doing this:** (1) login CSRF; (2) cookie theft window (no revocation);
(3) no brute-force limit; (4) TOTP codes were replayable within their 90 s window; (5) the R-27
masking filter corrupted JSON log lines that contained `•` escapes (the digit-run rule ate
`•3213`), fixed by logging with `ensure_ascii=False`; (6) uvicorn's access log would have
written invite tokens; (7) client reads/downloads and client write attempts were not audited (R-39);
cross-tenant requests were not audited (R-37).

**Could not fix / not in scope:** see "Open risks".

## Decisions I made (PM / Sriram to confirm)
1. Newly BREACHED cases: implemented as ruled in PRD v1.3 §6.1 Q13 (merged in #16 while I was
   building; my first cut only recorded the state). Not built from Q12: period selection and
   counting by completion time, "revised after response" marking, SLA attainment (R-40 work).
2. "Completed" = SUBMITTED_STUB or OUT_OF_SCOPE, which matches PRD v1.3 §6.1 Q12.
3. Reset sign-in resets **both** password and TOTP (one flow; admin verifies the person out of band).
4. Successful logins/logouts, lockout onset and admin user actions go to the audit chain; individual
   **failed** attempts go to `auth_attempts` only (an attacker must not be able to flood the hash-chained audit log). A
   flood of ACCESS_DENIED / CLIENT_WRITE_DENIED by a signed-in client can still grow the audit log;
   it is not rate-limited.
5. An ADMIN can create another ADMIN without a second approval (unlike config changes). PM/Sriram:
   should admin creation need two admins too?
6. Dev TOTP display (`DISPUTES_DEV_SHOW_TOTP=1`) works in `dev` only; never in `demo` (deploy's
   hosting check also refuses it).

## Contract requests (not applied; integrator)
1. `config.Config`: add `session_absolute_hours` (12), `login_max_account_failures` (5),
   `login_max_ip_failures` (30), `login_failure_window_min` (15), `invite_ttl_hours` (72),
   `password_min_length` (12) so ADMIN can change them through the two-admin flow. Today they are
   constants in `web/auth.py`.
2. `config.Settings`: add `trusted_proxy_hops` (`DISPUTES_TRUSTED_PROXY_HOPS`), `max_body_bytes`
   (`DISPUTES_MAX_BODY_BYTES`) and `allowed_origins` (`DISPUTES_ALLOWED_ORIGINS`); read from the
   environment directly today.

## For other agents
- **demo:** any POST/PUT/PATCH/DELETE from a CLIENT_VIEWER session is refused (R-39). A prospect
  "try your own letter" flow must run under a staff role in a sandbox tenant, or the route must be
  an explicit, reviewed exception. In `DISPUTES_ENV=demo` accounts on `synthetic-demo-pass` cannot
  sign in; create prospect accounts with `/ops/admin/users` links or a non-published password.
  New templates must keep to the CSP (no inline script/style; a test scans every template under
  `web/templates/`, including `templates/demo/`).
- **deploy:** `work --loop` now refreshes clocks every 300 s (`--clock-refresh-s`). Use
  `cli invite-admin` to create the first real admin. Leave `DISPUTES_TRUSTED_PROXY_HOPS` unset when
  `serve` trusts `DISPUTES_FORWARDED_ALLOW_IPS`.
- **package:** client exports go through `/client/cases/{id}/export.{json,html}`; the route audits
  the download before building. Please keep prompt text, config and per-analyst metrics out of
  the export (test: `test_client_export_has_no_prompts_config_metrics_or_other_tenants`).

## Open risks
- **No RLS / app DB role separation yet**: isolation is application-level (ADR-008). Pilot gate.
- `web_sessions` and `auth_attempts` grow without a purge job (R-31 retention: 90 days proposed).
- Lockout is a denial-of-service lever: anyone can lock a known email for 15 minutes. Accepted for a
  demo; admin unlock exists.
- TOTP secrets are stored in clear in `users.totp_secret` (as before). Pilot: encrypt with a KMS key.
- Invite links are bearer secrets until used (72 h); anyone holding one can set up the account.
- Analyst display names appear in the client export (Q16 open).
- No QR code for enrolment (text key and URI only).
- **Demo data will mostly escalate.** Measured on the local demo (`demo_native.sh`, fixtures ingested
  with fixture dates): the first refresh pass at real time (2026-11-15) changed 138 of 203 open
  cases and found 107 newly BREACHED; with Q13 these now move to ESCALATED within one worker
  interval (300 s). The demo/deploy agents should ingest with due dates relative to "now", or the
  queue a prospect sees will be mostly "Escalated: past the bureau due date".
