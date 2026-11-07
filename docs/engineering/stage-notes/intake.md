# Stage notes: intake module

**Date:** 2026-11-07  **Author:** developer (intake agent)  **Branch:** `agent/intake`
All data synthetic. No network, no LLM calls, no `synthgen` import in `src/disputes/`.

## What was built
| Req | Path | Notes |
|---|---|---|
| R-02, R-05 (missing due date) | `src/disputes/intake/validate.py` | `validate_dispute` checks control number, CRA, date received, due date, account number, consumer name, dispute codes. Strict `YYYY-MM-DD` (ASCII digits, no time/offset/padding). Free text and attachments may be empty (per stub; see ambiguity A1). Never raises; error messages name the field, never the value (R-27). Also `parse_iso_date`. |
| R-05 | `src/disputes/intake/clock.py` | `is_business_day`, `add_business_days`, `subtract_business_days`, `business_days_between` (signed, (start, end]), `compute_clock`. Holidays = `observed_date` of `holiday_calendar`; zone = `time_zone.due_date_end_of_day_zone`. `now` must be tz-aware (ValueError otherwise). |
| R-03, R-33 | `src/disputes/intake/attachments.py` | `inspect_attachment(s)`. Unreadable: archive by media type or extension (never opened), `metadata.image_only` or `image/*`, media type other than text/plain or application/pdf, < `min_chars_per_page` visible chars/page, > `max_pages_per_file`, > `max_file_mb` (only if a size is in metadata; absent = within limit), invalid page count or size. Zero-width chars and hidden spans are not counted as readable chars (so they cannot pad a short document). Hidden text from `metadata.render_hints.hidden_spans`, `metadata.hidden_spans` or `metadata.hidden_text`; zero-width in text, file name or metadata. |
| R-04 (repeats) | `src/disputes/intake/dedup.py` | `find_repeat`: most recent prior case with intersecting categories, `0 <= age_days <= window` (inclusive; same-day prior counts). Tolerates string dates and PG array literals. |
| R-14 | `src/disputes/intake/suspicious.py`, `src/disputes/reference_tables/injection_patterns.json` | `detect`: scans ACDV free text, attachment text, file names (with `_ - .` turned into spaces) and metadata values, after NFKC and zero-width removal. HIGH: `ROLE_MARKER`, `CHAT_TEMPLATE_TOKEN`, `OVERRIDE_IGNORE`, `OVERRIDE_NEW_INSTRUCTIONS`, plus `INVISIBLE_TEXT` (hidden spans) and `ZERO_WIDTH_CHARS`. LOW: `TOOL_JSON_CALL`, `TOOL_CALL_TAG`, `LLM_FLAG`. Level = max. Table is R-35 format, `verified=false`, `synthetic_placeholder=true`, source stated (ADR-007). |
| Combined | `src/disputes/intake/service.py` | `run_intake(dispute, now, cfg, prior_cases=None, *, llm_flag=False) -> (IntakeResult, SuspicionResult)`. Escalations in order INTAKE_INVALID, BREACHED, DOC_UNREADABLE (all recorded). Clock computed whenever the due date parses (even if another field is invalid). DOC_UNREADABLE also when attachments > `max_attachments_per_case`. Repeat key at intake = account + **code-table** categories (`code_categories`). `duplicate_of_case_id` always None (DB lookup, workflow). |

Stub signatures are unchanged. Additions: `add_business_days`, `end_of_day`, `holidays`, `zone`, `calendar_covers`, `parse_iso_date`, `scan_text`, `code_categories`, `run_intake`.

## Tests
Command: `cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q`
Result (2026-11-07, this branch): **`223 passed in 7.55s`** (76 existing + 147 intake). Intake only: `147 passed in 1.88s`.

| File | Covers |
|---|---|
| `src/tests/test_intake_validate.py` | R-02 every required field × missing/empty/whitespace; bad dates (US format, 13th month, Feb 30, timestamps, full-width/Arabic-Indic digits); codes; non-string and non-Dispute input; no value echo |
| `src/tests/test_intake_clock.py` | Holidays/weekends, target, AT_RISK window incl. past-target, last microsecond of due date vs breach, zone (UTC/LA vs New York), due on a holiday, config offsets, naive `now`, table versions. **Hypothesis (400 examples each, deadline=None):** never lands on weekend/holiday; round-trips (`add(sub(d,n),n)==d`, counts == n); `business_days_between` equals a naive loop, antisymmetric and additive; clock state equals its definition for random due/now/offsets; states monotonic over time |
| `src/tests/test_intake_attachments.py` | Threshold per page and config, image-only, archives (5 forms), unsupported type, page/size limits, invalid page count, zero-width (5 code points) incl. padding attack, hidden spans incl. padding attack, too many attachments |
| `src/tests/test_intake_dedup.py` | 30-day repeat (S1), inclusive 90-day boundary, category intersection, most-recent wins, malformed priors, config window |
| `src/tests/test_intake_suspicious.py` | Table schema + verified=false; 11 plain consumer sentences → NONE (incl. "Please delete this late payment…", "disregard my previous letter", "your system shows…"); 12 HIGH variants (incl. full-width `ＳＹＳＴＥＭ:`); zero-width-split override; tool syntax → LOW; LLM flag; each surface |
| `src/tests/test_intake_service.py` | Combined behaviour, reason order, repeat linking, flag never changes escalations, garbage input escalates without raising |
| `src/tests/test_intake_fixture_agreement.py` | Agreement with `labels.jsonl` (below) |
| `src/tests/test_intake_helpers.py` | Builders (no tests). Includes `dispute_from_envelope(..., proposed_contract=True)` that applies contract requests C1/C2 for measurement only |

## Agreement with generator-intent labels (seed20261019_n200)
`now` = `fixture_meta.ingest_date` 17:00 America/New_York. 4 DUPLICATE_IGNORED cases excluded (workflow decides duplicates), leaving 196. Labels are generator intent and circular with the PRD (U20/U31); production code never reads them.

| Measure | Current `acdv_to_dispute` | With contract changes C1+C2 |
|---|---|---|
| Intake escalations (INTAKE_INVALID / DOC_UNREADABLE / BREACHED) exact set match | **192/196** | **196/196** |
| `clock_state_at_intake` (188 cases with a gold state: 180 ON_TRACK, 4 AT_RISK, 4 BREACHED; null for the 8 INTAKE_INVALID) | 188/188 | 188/188 |
| `suspicious_expected` level (7 HIGH, 1 LOW, 188 NONE) | 196/196 | 196/196 |
| Hidden-text finding == `injection_hidden_text` tag | 0/2 detected (render hints dropped by mapper; both still HIGH via zero-width + visible override phrase) | 196/196 |
| Repeat link (replay in ingest order, key = account + code category, 90 days) | 196/196 (4 repeats) | same |
| **HIGH false-positive rate on clean cases (B14/U23)** | **0/188 = 0.0%** (any flag: 0/188); 95% one-sided upper bound ≈1.6% (Clopper-Pearson, 0/188). 4/4 imperative negative controls NONE | same |

**The 4 disagreements** (C00021, C00035, C00128, C00139, all `malformed:blank_last_name`): generator labels INTAKE_INVALID; we pass them. Cause: **contract/mapper issue, not an intake bug and not a label bug.** `acdv_to_dispute` builds `consumer_name = f"{first} {last}".strip()`, so a blank last name becomes a one-word name and the defect is invisible to intake. Fix = C1 below. There is also a PRD ambiguity (A2): whether a one-part name is invalid.

The FP number is weak evidence: clean fixture letters are templated, so 0% says little about real letters (U23 stays open). Known FP risk: a lower-case role word followed by a colon (e.g. "the customer service assistant: Jane said…") matches `ROLE_MARKER` and would be HIGH. Kept because R-14 names "assistant:" explicitly; worth measuring on the T1 clean stratum and the generator v1 letter variety.

## Stubbed, faked or not done
- No text extraction: intake trusts `extracted_text`/`page_count` from the adapter (no PDF parsing, no OCR, by ADR-007). Font-size/colour/off-page detection is only as good as the `render_hints` the extractor provides.
- File size is read from metadata keys `size_bytes` / `file_size_bytes` / `byte_size` / `size_mb`; fixtures carry none, so R-33's 10 MB limit is untested on fixtures (unit-tested only).
- Duplicates (R-04 DUPLICATE_IGNORED) are not decided here; the workflow must check the control number in the DB before calling `run_intake`.
- Holiday table covers 2026-01-01..2027-12-31 only. Outside it, only weekends are excluded; `ClockInfo.table_versions["holiday_calendar"]["covers_dates"]` is False so the reviewer/audit sees it. Not escalated (no rule for it; flag to PM).

## Contract-change requests (integrator / foundation)
**C1 (`src/disputes_core/contracts.py`, `acdv_to_dispute`): a blank first or last name must give `consumer_name=None`.**
```diff
-    name = f"{first} {last}".strip() or None
+    name = f"{first} {last}" if first and last else None   # R-02: blank part = missing required field
```
Affects: platform-core (stores consumer_name), web (display). Fixes the 4 disagreements. Needs A2 answered if mononyms must be accepted.

**C2 (same function): carry attachment render hints so R-03 hidden-text detection works on fixtures.**
```diff
-        attachments=tuple(Attachment(x["attachment_id"], x["file_name"], x["media_type"], x["page_count"],
-                                     x["extracted_text"], x["sha256"], dict(x.get("metadata") or {}))
+        attachments=tuple(Attachment(x["attachment_id"], x["file_name"], x["media_type"], x["page_count"],
+                                     x["extracted_text"], x["sha256"],
+                                     {**dict(x.get("metadata") or {}),
+                                      **({"render_hints": x["render_hints"]} if x.get("render_hints") else {})})
                           for x in a.get("attachments") or ()),
```
(Alternative: a `render_hints: dict` field on `Attachment`; intake already reads `metadata["render_hints"]`, so C2 needs no intake change.) Note this changes nothing in the raw payload hash.

**C3 (informational, no diff):** `tests/test_platform_foundation.py` bans the upper-case substring `HIDDEN` in all platform code, so the reason / pattern code is `INVISIBLE_TEXT` rather than `HIDDEN_TEXT`. Web should label it "hidden text".

## PRD ambiguities (to PM)
- **A1** R-01 lists free text as a required field and R-02 invalidates empty required fields, but the intake stub (and S1) say free text may be empty. The generator oracle treats empty/missing free text as INTAKE_INVALID. I followed the stub. No fixture has empty free text, so agreement is unaffected.
- **A2** Is a consumer name with only one part (blank first or last) INTAKE_INVALID? The generator says yes; real mononyms exist.
- **A3** R-33 says archives → DOC_UNREADABLE but does not say what > 10 attachments does. I escalate DOC_UNREADABLE and still inspect all of them.
- **A4** R-05 does not say whether a due date on a weekend/holiday shifts (U36). Not shifted; target counted back from the CRA date as given.
- **A5** What a due date outside the holiday table's range should do (currently: weekends only + `covers_dates=False`).

## What the integrator needs to wire up
1. `default_deps`: `validate_dispute=intake.validate.validate_dispute`, `inspect_attachments=intake.attachments.inspect_attachments`, `compute_clock=intake.clock.compute_clock`, `detect_suspicious=intake.suspicious.detect`, `find_repeat=intake.dedup.find_repeat` — or call `intake.service.run_intake` once and store `IntakeResult` / `SuspicionResult` as the `intake` / `suspicion` artifacts.
2. Order: duplicate check by control number (DB) → `run_intake(dispute, now, cfg, repo.prior_cases_for_account(...))`. `now` must be tz-aware.
3. Repeat at intake uses **code** categories. After classification (R-06), call `find_repeat` again with the final category set if it differs, to catch a repeat that only the LLM category reveals.
4. Copy `clock.state`, `clock.due_date`, `clock.internal_target` into the `cases` columns used by the R-16 queue. The clock must be **re-evaluated** periodically (worker) for AT_RISK/BREACHED transitions; intake only evaluates at ingest.
5. Re-run `detect(..., llm_flag=True)` (or append the LOW match) when the classifier/claims step reports an LLM flag. HIGH → R-19 second approval.
6. Apply C1 and C2; then drop `proposed_contract` in `test_intake_fixture_agreement.py` and tighten the "current mapping" test to 196/196.

## Self-review
- Every intake acceptance criterion in S1/S5/S8 has a passing test I ran (above).
- Deterministic: deadlines are table-driven code with property tests; no model on the path.
- Malformed input never raises (validate, attachments, dedup, detect, run_intake); only a naive `now` raises (caller bug).
- Manipulation via uploads: zero-width/hidden text cannot pad readability; zero-width cannot split an override phrase; full-width homoglyphs folded by NFKC. Not covered: other homoglyphs (Cyrillic "ЅYSTEM"), paraphrased injections (residual risk per ADR-007, LLM flag is LOW only).
- PII: error messages carry no values. `SuspicionMatch.excerpt` (≤80 chars) contains consumer text and goes into the case artifact (audit store, not masked by design, R-27); it must not be written to operational logs.
- Placeholders: holiday calendar, time zone and injection patterns are all `verified=false` (U21, U36, U23).
