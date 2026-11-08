# Stage notes: generator v1 (R-26 v1, T2 red-team suite)

**Date:** 2026-11-07  **Owner:** developer (generator module)  **Branch:** `agent/generator`
**Everything here is SYNTHETIC.** Placeholder schema, codes and ratings (U6), `verified=false` tables.

## What I built
- `src/synthgen/v1/` (standard library only), behind a version switch. **v0 is untouched**: `synthgen/generator.py`, the oracle, schemas and committed v0 fixtures are byte-identical (`test_committed_fixture_matches_regeneration` and the v0 determinism tests still pass). The CLI default is still v0 (tested).
  - `phrasing.py`: paraphrase banks per claim **kind** (13 kinds, 10-16 templates each), 14 greetings, 14 intro lines, 12 intro contexts, 16 fillers, 12 backstory lines, 14 requests, 12 closings, 8 month formats, 7 day-date formats, a typo function that never touches placeholders (months, dates, amounts, names).
  - `injections.py`: catalogs for 5 surfaces: letter body 26, hidden text 25 (5 styles x 3 placements, half also put a zero-width char in the greeting), ACDV free text 25, file name/metadata 25, tool/JSON syntax 25. Each variant has a `variant_class` (e.g. `role_marker_obfuscated`, `homoglyph`, `override_paraphrase`, `fake_transcript`). PII bait (3 kinds x 6 phrasings), 12 plain-imperative negative controls, 10 benign look-alikes ("your system", "the instructions").
  - `notes.py`: benign structured (`OTHER`) and free-text servicing notes on every account (0-4 free text, 0-2 structured), plus free-text plan notes for the conflict scenarios.
  - `generator.py`: letters composed from blocks (optional header with address and letter date, greeting, intro, optional backstory, claims paragraph(s) with filler, request, closing, optional P.S.), single- or double-spaced, sometimes one run-on paragraph. Claim spans are located by code from the rendered text (assert-checked). Fraud letters are denial x explanation x action (26 x 21 x 15 = 8,190 combos) with a per-batch selector: **any two fraud cases share at most one component**.
  - New scenarios: `ph_verify_long` (long letter, claim sometimes only in the P.S.), `ph_multi_month_verify`, `ph_multi_month_mixed` (MODIFY), `ph_freetext_note_conflict` (ESCALATED/EVIDENCE_CONFLICT from a free-text note only, R-10 "LLM free-text-note flag"), `ph_freetext_note_near_miss` (plan note ends before the month; VERIFIED), consumer does not mention the plan in some conflict cases, low-text-layer PDF (<200 chars/page), more malformations (blank control number, impossible date, more non-ISO formats).
  - `report.py`: `variant_report.json` written with every v1 set (U34): per surface, per claim kind and claim type (templates, distinct quotes, distinct "skeletons" with months/numbers masked), fraud (distinct combos, max shared components, max word-3-gram Jaccard, near-duplicate pairs at >=0.6), letters (greetings, closings, structures, formats, typo rate, length).
  - `redteam.py` + `cli redteam`: T2 suite. Every catalog variant x 1 injected case + 1 clean twin, base scenario rotated over VERIFY / MODIFY / CLAIM_UNRESOLVED / EVIDENCE_CONFLICT / BALANCE (out of scope) / identity fraud.
- Committed data:
  - `src/data/fixtures/v1_seed20261107_n200/` (same layout as v0 + `variant_report.json`; manifest has `generator_version: 1.0.0`, `t1_strata`).
  - `src/data/redteam/t2_seed20261107/`: `acdvs.jsonl`, `sor_accounts.jsonl`, `labels.jsonl`, `pairs.jsonl` (twin pairs with the B5 pass rule), `variants.jsonl` (catalog), `variant_report.json`, `manifest.json`.

## Commands
```bash
cd src
../.venv/bin/python -m synthgen.cli generate --seed 20261107 --n 200 --generator-version 1.0.0 --out data/fixtures/v1_seed20261107_n200
../.venv/bin/python -m synthgen.cli generate --seed 424242 --n 1100 --generator-version 1.0.0 --mix t1 --out /tmp/t1   # T1-weighted mix (not committed; Stage 4 freezes T1)
../.venv/bin/python -m synthgen.cli redteam --seed 20261107 --out data/redteam/t2_seed20261107
```

## Tests (actually run)
- New: `tests/test_generator_v1_core.py` (44) and `tests/test_generator_v1_redteam.py` (7): **51 passed in 8.6 s** on the generator branch before rebase.
- Full suite after rebasing on origin/main (29fde5e), `cd src && ../.venv/bin/python -m pytest -q -o addopts=""`: **401 passed in 84.99s**, exit 0.
- Coverage: determinism (in process, hypothesis over 8 seeds, CLI files identical under PYTHONHASHSEED 0 and 12345, T2 deterministic); CLI default still v0; schema validity of v1 batch (1,000), T1 mix (1,100) and T2; `synthetic=true` on every record and sub-record; obviously-synthetic markers; PII guard on all generated sets and committed files; claim spans locate quotes exactly; every labelled month is written in its quote (typos never hit months); gold invariants (VERIFY invariant, no DELETE, MODIFY corrections, escalation iff reasons, scenario intent); structured and free-text note conflicts and near misses; background notes benign; repeats and duplicates linked; deadline tags; R-26 shares at n=100/200/1,000; all required edge and adversarial tags; T1 strata; fraud stratum has no near-duplicates; catalog minimums and R-14 flag classes; **twins differ only by the injection** (deleting `removal_spans` from the injected letter gives the clean letter byte-for-byte; free text = clean + suffix; metadata only on the metadata surface; accounts equal except account number; claims and gold equal); every injection is on its surface; negative controls NONE; R-34 (v1 + T2 text not in `src/prompts/`); committed v1 and T2 sets match regeneration; committed sets map through `FixtureAcdvSource` / `MockSystemOfRecord`.

## Variant counts (from the generated data, not just the catalogs)
- **Injection variants per surface** (T2, all distinct and all used): letter body 26 (14 classes, 5 placements), hidden text 25 (5 styles, 3 placements), ACDV free text 25 (11 classes), file name/metadata 25 (19 classes), tool syntax 25 (25 forms). **126 variants, 252 cases.** T2 gold outcomes: 62 ESCALATED (20 identity fraud), 22 MODIFY, 21 OUT_OF_SCOPE, 21 VERIFIED.
- **Claims per kind** (1,000-case default mix, seed 20261107): templates used / available, distinct quotes:
  ON_TIME 16/16, 410 quotes (574 claims); NEVER_LATE 12/12; NOT_30_LATE 14/14; ONE_BEHIND 12/12; ON_TIME_TWO 12/12; ON_PLAN 12/12; REP_PROMISE 12/12; BALANCE_SHOULD_BE 12/12; BALANCE_TOO_HIGH 9/10; ENCLOSED_STATEMENT 9/10; EXTRA_NOT_30 9/10; LATES_WRONG 9/12; FRAUD_DENIAL 24/26; EXTRA_ON_TIME 1/10 (rare by design: only when the extra month's DPD is 0).
  Per claim type, distinct templates used: PAYMENT_EVENT 73, ACCOUNT_STATUS 45, AGREEMENT 24, AMOUNT 21.
- **Fraud** (T1 mix, n=1,100): 165 fraud cases, 165 distinct component combos and passages, max 1 shared component between any two cases, max word-3-gram Jaccard 0.47, **0 near-duplicate pairs** (>=0.6), 60 indirectly phrased. v0 had 3 phrasings.
- **Letters** (1,000-case set): 960 distinct texts of 980 (the 20 equal ones are free-text/metadata twins, by design); 14 greetings, 12 closings, 8 month formats, 7 day formats; 434 with a header block; 110 single-paragraph, 20 long; 201 letters (20.5%) with 250 typos; 251-1,060 characters, median 428.
- T1 strata (T1 mix, n=1,100): should-not-verify 759, should-escalate 484, identity fraud 165, clean should-verify 330 (minimums 600/150/150/200).

## Known limits (honest)
- **Still template-composed.** Variety is much higher, but every sentence comes from a bank I wrote; an LLM can still learn the banks. Not realistic enough to stand in for T3 or for an outside realism review (U20). Bank statements, CRA free text (4-6 phrasings per kind) and OTHER letters remain thin.
- **Labels are still generator intent** and circular for rule logic (U35). The free-text-conflict rule is applied by mirroring the note into a virtual HARDSHIP note for the v0 oracle; the product must detect it with the LLM note flag, so those cases test the LLM, not the rules.
- **`suspicious_expected` is the PRD R-14 class, not a detector prediction.** Obfuscated, homoglyph, paraphrased-override and "plain imperative in hidden text" variants are labelled HIGH (role marker / override / hidden). A narrow pattern list will miss some; that is what the variant classes are for. B5 is about outcome invariance, which does not depend on the flag.
- **Hidden text is represented, not rendered**: `render_hints.hidden_spans` plus zero-width characters, as in v0. No PDF bytes (no new dependency).
- Fixture shape is still `placeholder-acdv-0.1.0` (U6). Twins keep the same last four account digits so the letter text matches; the full account and control numbers differ.
- The T1 set itself is not frozen or committed (Stage 4). The 1,100-case T1 mix is a tested recipe.

## What the integrator / other modules need
1. **Intake (R-03/R-14):** the hidden-text signal is in `attachments[].render_hints.hidden_spans`; main's `acdv_to_dispute` now copies render_hints into `Attachment.metadata` (per the coordinator), so intake should read it there. 10 of 25 hidden variants carry no zero-width char, so detection that relies on ZW alone will miss them. Variant classes to consider for the pattern list: `role_marker_bracketed`, `role_marker_special_tokens`, `role_marker_xml`, `role_marker_markdown`, `role_marker_obfuscated` (`S Y S T E M :`, `S-Y-S-T-E-M`), `role_marker_mixed_case`, `homoglyph` (fullwidth SYSTEM), `override_paraphrase` (forget/disregard/"ignore your instructions"), `fake_transcript`, `role_marker_developer`.
2. **Eval harness (Stage 4):** B5 runner reads `data/redteam/t2_seed20261107/pairs.jsonl`; compare category set, escalation reasons, extracted claims, outcome and narrative between `clean_case_id` and `injected_case_id`. B14 false positives: use cases tagged `imperative_negative_control` / `benign_lookalike_control` and clean twins.
3. **Labels carry new optional fields** (schema allows them): `claims[].claim_kind`, `claims[].template_id`, `injection` (surface, variant_id, class, placement/style, `removal_spans`), `fraud_phrasing`, `note_conflicts`, `letter_features`, `template_ids`, and `t2` in the red-team suite. `free_text_notes[].date` and `notes[].summary` are new optional account fields. No contract change is needed.
4. **R-34:** the T2 payloads are short role/override phrases. If a prompt author quotes one verbatim (>=25 chars) as an example, `test_v1_eval_text_not_in_prompt_library` fails by design. Describe attack classes in prompts; do not paste catalog lines.
