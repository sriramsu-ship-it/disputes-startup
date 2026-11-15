# Stage notes: package module (R-20 response package, R-22 audit export, G5)

**Date:** 2026-11-15  **Branch:** `agent/package`  **Owner:** developer (package)  **Data:** synthetic only

## What changed and what it means
A prospect can now take two documents away from any completed case: a **response package** that reads like a dispute response (result, masked account, month-by-month reported vs corrected values, cited narrative, approvers with times, days before due, versions and a recomputed integrity check) and an **audit export** whose first page answers "what was disputed, what did we look at, what did we decide, why, who decided, when, can I trust this" before the detail. Both render as HTML, PDF (from the same HTML) and, for the export, a zip bundle. Every copy says on its face that it is a synthetic demonstration on a placeholder schema not validated against e-OSCAR or Metro 2.

## PRD v1.3 alignment (merged while I worked)
- **R-47** banner: every package and export rendering (HTML, PDF, zip copies) carries the exact line "DEMO · Synthetic data only · Not connected to e-OSCAR or any credit bureau · Never enter real personal information" (in `_package_macros.html`), above our placeholder-schema notes.
- **R-53**: package headed "Response package: NOT SENT. Synthetic demo."; rating values marked "placeholder codes" while `payment_rating_map.verified=false`; export opens with a **Case summary** page (renamed from "Examiner summary") with outcome, rule IDs with a plain-English detail line, each claim with its quote and finding, evidence with hashes, every human decision with reason code and text, the timeline against internal target and CRA due date, hash-chain status and **last anchor time** (`export.anchor_status`: latest anchor file, whether it covers the case's last event; reported, not re-verified). "examiner-ready" is not used.
- **R-51**: `test_package_and_export_templates_carry_the_banner_and_no_banned_claims` scans my templates and CSS for the §5.2 patterns (banner text exempt). The banner itself contains "connected to e-OSCAR" as part of "Not connected to e-OSCAR"; a repo-wide AC-22 scanner must exempt the exact banner string.

## What I built
| Item | Where | Notes |
|---|---|---|
| Package builder (R-20) | `src/disputes/package/build.py` | `build_package(b, w, approvals=, authorised_name=, versions=, now=)`, pure. `package_schema_version = "placeholder-response-package-2.0"` plus `schema_status` (placeholder, not validated against e-OSCAR ACDV response or Metro 2, no response code mapped). All v1 keys kept unchanged; v2 adds `account_last4`, `dispute`, `month_by_month`, `basis` (proposal, departs flag, rule firings, claim findings, evidence hashes), `timing` (calendar days before due), approval timestamps. v2-after-reopen unchanged in behaviour (supersedes hash + change reason). |
| Thin call site | `web/actions.py::_finalise` | Replaced the inline dict with one call to `build_package`; sink, artifact, `PACKAGE_WRITTEN` event and state change untouched. |
| View models, integrity | `src/disputes/package/model.py` | `package_integrity(row, events)` recomputes the stored hash, checks the `PACKAGE_WRITTEN` event's `package_sha256`, and checks content hash = event `content_sha256` = sink receipt. `export_summary(ex)` builds page 1 from the export dict only. |
| Export (R-22) | `web/export.py` (now package-owned), `templates/export.html`, `_package_macros.html`, `static/package.css` | `export_schema_version = "web-export-2"`. Adds `summary`, `package_integrity`, `limitations`, `audience`, `redactions`, per-attachment `extracted_text_sha256` and `original_stored: false`. All earlier keys kept. Hash-valued keys are never masked (the old `mask_deep` could corrupt hex hashes containing 8+ digit runs). |
| Client copy (R-39/R-41/R-27) | `export.build_export(masked=True)`, `package_routes.client_package_copy` | Account and SSN-shaped values to last 4, consumer name to initials, analysts as "staff <id> (<role>)" (Q16), `dfAuthorizedName` withheld, audit-event payloads omitted (IDs, types, actors, payload and chain hashes kept), suspicion reduced to level + count. Integrity is computed on the unmasked record before masking. |
| Rendering, PDF | `package/render.py`, `package/pdf.py` | Standalone HTML inlines the CSS and carries a `default-src 'none'` CSP meta tag. PDF via headless Chromium (`chrome-headless-shell` preferred; `$DISPUTES_PDF_BROWSER` overrides), black-hole proxy, throwaway profile, 25 s timeout. No new Python dependency. |
| Bundle (R-22 zip) | `package/bundle.py` | `MANIFEST.json` (every file with sha256 and size, `not_included`, `original_attachments[].original_included = false` with the intake hash), `README.txt`, `export.json/html/pdf`, `packages/package-vN.json/html`, `attachments/<id>__<safe name>.extracted.txt`. Untrusted file names reduced to `[A-Za-z0-9._-]`, 80 chars. |
| Routes | `web/package_routes.py`, one `include_router` line in `web/app.py` | Staff: `/ops/t/{t}/cases/{c}/packages/{v}.{html,json,pdf}`, `/ops/t/{t}/cases/{c}/audit-export.{pdf,zip}`. Client: `/client/cases/{c}/packages/{v}.{fmt}`, `/client/cases/{c}/audit-export.{pdf,zip}` (own tenant, completed cases only). Uses the app's own `handle` / role / tenant checks. AUDITOR/ADMIN reads -> `CASE_READ` (R-21); every client download -> `CASE_READ` with the CLIENT_VIEWER actor (R-39). No PDF renderer -> 503 with a "print from the browser" message; the zip lists `export.pdf` under `not_included`. |

## Tests (run 2026-11-15)
- `tests/test_package_build.py` (8, no DB), `tests/test_package_export.py` (8), `tests/test_package_http.py` (5): **21 passed**.
- **G5** (`test_g5_sampled_cases_are_reconstructable_from_the_rendered_export_alone`): 40 committed fixtures through the real pipeline (offline agents), 4 approved, plus 5 web scenarios (modify approved, out of scope, unaddressed claim, ID fraud, HIGH suspicion with second approval). 18 distinct cases sampled (seeded); for each, the test parses only the rendered export HTML and recovers final outcome, system proposal, rule IDs + versions, evidence IDs and each claim's finding; all 18 equal the stored values. Mix: VERIFIED_AS_REPORTED, MODIFY, OUT_OF_SCOPE (final and proposed), ESCALATED (several reasons). This is the automated stand-in for G5; Sriram's manual G5 on 10 cases is still required by the PRD.
- Full suite after rebase on main (incl. hardening #17): **725 passed**, EXIT=0 (2026-11-15).
- Rebase note: hardening changed the app hooks (`require_tenant(conn, ctx, request, t)`, `client_case_or_404`, `client_read`, ACCESS_DENIED); my router now uses those hooks, so client downloads and denied requests are audited by the app's own code. Hardening's template rules (no inline style, no `|safe`) hold: the inlined CSS is passed as `Markup` from `package/render.py`.

## Timing (R-22: <= 10 s per case with <= 10 attachments)
Measured locally (single case, headless shell 1243):
- 10-attachment case, export JSON + HTML + PDF + zip (zip includes a second PDF render): **1.07 s staff, 1.09 s client** (asserted <= 10 s in the test).
- Sample cases: export + HTML 0.01-0.17 s; PDF 0.5-1.0 s; zip 0.4-0.9 s; total 0.9-2.1 s per case.
- Note: `google-chrome` (full browser) hung for > 40 s in this sandbox (D-Bus / zygote); the headless shell renders in ~0.25 s. `find_browser` prefers the headless shell for that reason.

## Sourced facts used (all logged in the primer verification table, 2026-11-14)
| Fact | Grade | Used for |
|---|---|---|
| ACDV results in substance: "Verified as Reported", correction made on the ACDV and returned, modified / deleted per furnisher (FTC/FRB 2006 report) | A, but 2006 | Result labels "Verified as reported", "Modify (account information updated)", "Delete"; corrected values shown month by month |
| e-OSCAR response codes are RCnn values; RC03/RC07/RC13 are delete codes (release notes eo2026.02) | A, partial | Nothing: no partial code map. The package states "e-OSCAR response code: not mapped (U6)" |
| `dfAuthorizedName` required in ACDV responses (April 2026 release notes, PRD R-20) | A (existing) | The only real field name in the package |
| CFPB exam procedures (2012) sample dispute notices and test investigation, review of relevant info, results reported, modify/delete/block; direct disputes: results to consumer, corrected info to CRAs | A, 2012 | The page-1 questions of the export |
| Reg V 1022.43(e); Appendix E I.(b)(3), III.(c), III.(h) | A | Same; records substantiating accuracy |
| Supervisory Highlights Issue 20 (2019) and Issue 32 (2024) furnisher findings | A | Showing on the record's face: evidence reviewed, result recorded, correction made |
| Experian: payment history profile is a 24-byte, up-to-24-month field; built from monthly files; AUD for some changes | A for Experian practice | Context only; the package does not emit Metro 2 |

## Unverified (for the integrator to add to UNKNOWNS.md)
1. **ACDV response layout**: which fields carry corrected account data, how payment history is returned (per-month values vs a profile string), and required fields beyond `dfAuthorizedName` (extends U6).
2. **Full e-OSCAR response code list and meanings** (RC03/07/13 are named as delete codes; nothing else).
3. **Metro 2 payment-rating / payment-history code values** and how a historical correction is conveyed (Base Segment vs AUD vs next monthly file) for each bureau (extends U6).
4. **What examiners expect an investigation record to look like.** No public source prescribes a format; the 2012 exam procedures may have been revised (extends U10, U3).
5. Whether the business-day calendar applies to "days before due" (U21): the documents show calendar days and say so.
6. Whether client copies may show analyst names (Q16) and whether `dfAuthorizedName` should be the client's employee or ours (U42).

## Stubbed, faked or limited (plain statement)
- The package schema is our placeholder. It has not been validated against e-OSCAR or Metro 2, and nothing is sent anywhere (stub sink).
- Original attachment files are not stored; the bundle holds extracted text and the intake hash of each original, and says so.
- The Docker image (`Dockerfile`, deploy module) has **no browser**, so PDF routes answer 503 there until a headless Chromium is added (e.g. Playwright's `chromium-headless-shell` or Debian `chromium`) and `DISPUTES_PDF_BROWSER` is set. HTML print-to-PDF works from any browser.
- Chromium runs with `--no-sandbox` (root / containers without user namespaces). Mitigated by rendering only our own autoescaped HTML with a `default-src 'none'` CSP, no network (black-hole proxy) and a timeout. Revisit before hosting.
- Intake-stage escalations (e.g. INTAKE_INVALID, classification routes) record no `RuleFiring`, so the export can show the escalation reason but no rule ID/version for them. The export says so in "Why". This is an R-29 gap for intake/platform-core, not something the export can fix.
- The case view (`ops_case.html`) and client case page (`client_case.html`) still link only `export.html` / `export.json`; the new documents are reachable from the export's toolbar and package links. Request below.

## Requests for the integrator / other modules (not applied)
1. `templates/ops_case.html` packages list: link each version to `/ops/t/{t}/cases/{c}/packages/{v}.html`; `client_case.html`: add "Response package" and "Download bundle (zip)" links.
2. `Dockerfile`: install a headless Chromium and set `DISPUTES_PDF_BROWSER` (see above).
3. The existing `/client/cases/{c}/export.{json,html}` route in `app.py` does not write a download audit event; R-39 requires one (my new client routes do).
4. Add the six unknowns above to `UNKNOWNS.md`.

## Threat notes (this surface)
Assets: unmasked dispute data in staff documents; client copies leaving the platform. Trust boundaries: browser to app (app's session, CSRF and CSP unchanged), app to a local Chromium process, zip contents opened on the client's machine. Abuse cases handled: client fetching another tenant's or an incomplete case (404, nothing written to the other tenant; tested); staff without tenant access (404); malicious attachment file names in the zip (sanitised; tested with `../../`); HTML injection through letters (autoescape; standalone copies forbid scripts and fetches via CSP); a tampered package artifact (integrity check fails and the export says "DO NOT match"; tested). Open: `--no-sandbox` Chromium; PDF rendering is synchronous in the request thread (fine for a demo, a queue would be better under load).
