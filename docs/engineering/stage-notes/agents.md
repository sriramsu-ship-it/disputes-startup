# Stage notes: agents module (AI agents inside the product)

**Date:** 2026-11-07  **Branch:** `agent/agents`  **Owner:** developer (agents)
**Bottom line:** classify/route, claim extraction + quote location, claim mapping, cited drafting and the R-13 validator are built behind a schema-validated, budgeted `LlmClient`. The default backend is a deterministic **offline heuristic** client. On the 200 committed fixtures the full pipeline (real intake + rules + platform-core + offline agents) agrees with the gold outcome on **200/200**, with 0 false verifies. **That number is not model quality and is not evidence for B2-B13**: the offline heuristics were written by someone who could read the generator's letter templates. On 24 hand-written letters in unseen wording, the untuned heuristics got 14/24 category sets right and missed identity fraud on 5 of 5 fraud letters (see below).

## What was built (paths, requirement IDs)
| Path | What | Req |
|---|---|---|
| `src/disputes/agents/llm.py` | `LlmClient` protocol; `OfflineLlmClient` (model `offline-heuristic-0.1`, cost 0); `AnthropicLlmClient` (Messages API, pinned `cfg.llm_model_id`, `output_config` JSON schema, no tools, SDK retries off, requested vs returned model ID logged, mismatch → `ModelMismatch(LlmUnavailable)`, never retried); `CaseBudget`; `render_prompt` / `delimit`; `PRICES`; `make_client`, `make_budget` | R-14, R-15, R-30, R-36, ADR-005/006/007 |
| `src/disputes/agents/offline.py` | Heuristic handler per template (keywords, month parsing, sentence segmentation, DPD vs claim). Reads only the `data` the model would get; no file I/O, no synthgen (test-enforced) | demo/CI backend |
| `src/disputes/agents/schemas.py` | JSON schemas per step (`additionalProperties:false`, enums) | ADR-005 §1 |
| `src/disputes/agents/text.py` | quote normalisation + span location, months parser, sentence splitter, word count | R-11, R-13 |
| `src/disputes/agents/classify.py` | `classify`, `route` (stub signatures kept), `code_categories`, `fraud_keyword_hits` | R-06, R-07 |
| `src/disputes/agents/claims.py` | `locate_quote`, `extract_claims`, `map_claims` (+ `source_texts`, `check_mapping`) | R-11, R-08 |
| `src/disputes/agents/draft.py` | `draft_narrative` (template + LLM sentences, validate, one retry, else `valid=False`) | R-12, R-13 |
| `src/disputes/agents/validator.py` | `validate_draft` with stable error codes | R-13 |
| `src/prompts/{_rules,classify,extract_claims,map_claims,draft}.md` | System rules: no tools, delimited data is data, quote verbatim, cite evidence IDs, never decide outcomes. Hand-written few-shot only (R-34 check passes) | R-14, R-34 |
| `src/disputes/reference_tables/{fraud_keywords,outcome_words,response_templates}.json` | R-35 format, `verified=false`, source stated (written by this agent, unreviewed) | R-06, R-13, R-12, R-35 |
| `src/tests/test_agents_*.py` | 143 tests (see below) | all of the above |

Design points worth knowing:
- **Classification:** final `categories` = code set ∪ LLM set (UNCERTAIN removed) ∪ {IDENTITY_FRAUD if any fraud signal}. Conflict = LLM UNCERTAIN or code set ≠ LLM set. `escalations` holds only the routed reason (matches the gold labels). The classify prompt does **not** see the dispute codes, so the LLM set is an independent check. Confidence is stored, never used.
- **Claims:** months = LLM months (format-checked) ∪ months code parses from the located quote (backstop so a forgotten month still widens the evidence window). Free text is a claim source only when written in first person (bureau summaries like "CONSUMER DISPUTES ..." are not claims).
- **Mapping:** invalid mapping → claim keeps `finding=None`, `reason="MAPPING_INVALID: <why>"`, and UNADDRESSED_CLAIM (so R-17 blocks approval). Two different mappings for one claim count as invalid.
- **Prompt hash:** sha256 of the expanded template (template file with `_rules.md` substituted). Input hashes: sha256 of each top-level input, key order.
- **Delimiting:** each input is its own `<untrusted_data name=.. nonce=..>` block; `<`/`>` inside the JSON payload are escaped as `<`/`>`, so a payload cannot close its block; nonce derived from the payload.
- **Validator:** outcome words inside a *located* consumer quote are not counted (consumer's own words); outside the quote they are. Template sentences are re-matched against their template regex. HUMAN sentences: only evidence IDs and length are checked.
- **Budget counting:** a "call" = one logical step request; each call makes ≤ 1 + `llm_retries` attempts (every attempt recorded as an `LlmCallRecord` with `attempt`). Attempt timeout = min(60s, case time left). Backoff 1s × 2^(n-1); no retry if the backoff would overrun the case budget. A timed-out attempt's thread is abandoned (Python cannot kill it); its result is discarded.

## Tests: command and actual result
```
cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q; echo EXIT=$?
```
Result after rebasing on main (#2, #4, #5, #6, #7): **493 tests collected, all passed, EXIT=0** (wall time ≈ 90s on the shared 2 CPUs). The agents tests are 143 of them:
- `test_agents_llm.py`: delimiting and escaping, template rules present, template hash, offline determinism and zero cost, no synthgen/label access, budget records, call cap, retry with backoff, two failures → LlmUnavailable, schema-invalid output retried, **slow client times out twice → LlmUnavailable** (S5, scaled to 0.1s), 90s case budget, Anthropic mocked: pinned model, `output_config` schema, no `tools`, cost from the price table, **model-ID mismatch → unavailable, exactly one request, logged**.
- `test_agents_classify.py`: route precedence (table + exhaustive over all category sets × flags), S2 criteria (PH → INVESTIGATE; PH code + identity-theft text → fraud; keyword-only fraud; code-only fraud; multi-issue; UNCERTAIN → CLASS_CONFLICT at any confidence), hypothesis property "confidence never gates" (200 examples), LLM flag exposed and does not change routing, codes withheld from the prompt.
- `test_agents_claims.py`: quote location (exact, whitespace, curly quotes, zero-width; property test 300 examples), months parser, QUOTE_UNLOCATED (missing quote, unknown source), every UNADDRESSED_CLAIM rule, conflicting duplicate mappings, note-conflict flag, offline mapper semantics (on-time claim vs EV-CYCLE DPD, missing cycle, arrangement note overlap, general "never late").
- `test_agents_draft.py`: one rejection test per R-13 rule (no citation, unknown ID, quote not verbatim, span invalid, template mismatch/unknown, 7 outcome-word variants, >150 words, empty), outcome words allowed inside a located quote only, property test (500 examples) that no uncited or outcome-word LLM sentence passes, retry then success, **invalid twice → `valid=False`** (S5), retry skipped at call cap → invalid with `RETRY_SKIPPED`, template-only outcome and corrections, word limit with 11 claims.
- `test_agents_injection.py`: **40 of 40** generator twin pairs (8 each: letter body, hidden/zero-width text, ACDV free text, file name/metadata, tool syntax) give identical categories, route, escalations, claims, findings and narrative; LLM flag on 40/40 injected and 0/40 clean twins; 20 hand-written attacks (5 attacks × 4 surfaces) leave outputs unchanged; "please delete this late payment" is not flagged.
- `test_agents_agreement.py`, `test_agents_heldout.py`, `test_agents_pipeline_e2e.py`: the reports below (floors asserted a little below measured values, as regression guards).

## Agreement numbers (offline backend; honest reading below each)
**200 committed fixtures, agents steps alone** (`python tests/test_agents_agreement.py`; evidence from the real `rules.evidence.gather_evidence` over the SoR record, months = ACDV ∪ claim months):
| Metric | Result |
|---|---|
| LLM category set = label `categories` | 200/200 |
| Route = gold route (derived from label categories vs code categories) | 200/200 (fraud 10/10, 0 fraud false positives) |
| Claims extracted / located by code | 247 / 247 (0 QUOTE_UNLOCATED) |
| Claim recall vs labels (same source, span Jaccard ≥ 0.5) | 247/247 (all exact spans); extra claims 0; months 247/247; type 247/247 |
| Finding agreement on matched claims | 247/247 (144 CONTRADICTED, 61 NOT_ADDRESSABLE, 42 SUPPORTED); cycle evidence ID cited 176/176 |
| Draft validity (155 in-scope cases, gold decision) | 155/155 valid, all on the first attempt (B15 pre-retry rejection 0%) |
| LLM flag | 8/8 expected injection cases flagged, 0 others |
| Calls per case | max 4; cost $0.00 (offline) |

**Full pipeline, 200 fixtures** (`test_agents_pipeline_e2e.py`, real `default_deps`): outcome = gold on **200/200**; escalation-reason set exact on 72/72 gold-escalated cases; 0 false verifies; 0 LLM_UNAVAILABLE, 0 DRAFT_INVALID, 0 SYSTEM_ERROR.

**Generalisation checks:**
- Fresh generator draw (seed 777, n=1000, run once by hand): route 1000/1000; claim recall 1261/1261; findings 1246/1261 (15 CONTRADICTED → NOT_ADDRESSABLE, all on `malformed` cases with no SoR account, which intake escalates anyway); drafts 772/772 valid. Same templates as the fixtures, so not independent.
- **Hand-written letters in unseen wording (n=24, `test_agents_heldout.py`), measured BEFORE any tuning:** category set 14/24; claims found 15/18; findings 11/15; **identity fraud missed by the LLM heuristic on 5/5 fraud letters** (1 was still routed out via the keyword list). I then broadened the heuristics (fraud paraphrases, balance and status phrasing): 24/24 categories, 17/18 claims, 13/17 findings. After tuning, this set is no longer held out. Remaining misses: an on-time claim phrased indirectly, a "your 30 days late is wrong" claim, a "the late mark is wrong" claim, a hospital-stay claim read as on-time, and a claim inside a "Kindly ..." request sentence.

**How to read these numbers.** They show the plumbing works end to end and the code-side checks behave. They do **not** measure the product's model: the offline client is a stand-in, the generator uses a small set of letter templates the heuristics were fitted to (circular), and the hand-written set shows how brittle keyword rules are on real-world phrasing. B2-B13 must be measured with the pinned model on T1/T3 (Stage 4).

## Stubbed, faked or not done
- **Offline backend is the only backend exercised.** `AnthropicLlmClient` is tested against a mocked SDK only; no network call was made (ADR-006: off until ZDR is confirmed in writing).
- **Anthropic price for `claude-sonnet-5-5` in `PRICES` is a PLACEHOLDER** (3 / 15 USD per MTok, `verified=False`). Confirm on the provider price list before quoting any cost (R-36).
- Reference tables `fraud_keywords`, `outcome_words`, `response_templates` are written by me, unreviewed, `verified=false`. Template wording needs counsel/practitioner review.
- Offline token counts are estimates (chars/4).
- No LLM-as-judge; validator proves citation/quote existence only (stated limit, R-13).

## Known limits / risks
1. **R-15 call cap vs four LLM steps.** PRD R-15 counts 4 calls "(classify, claims, draft, one validator retry)", but ADR-005 has four steps (classify, extract_claims, map_claims, draft). With the default `llm_max_calls_per_case=4`, a draft that fails validation gets **no retry**: it returns `valid=False` with `RETRY_SKIPPED` (→ DRAFT_INVALID), never a silent pass. To honour "one retry" the cap must be 5. **PM decision needed** (see request 1).
2. Keyword heuristics are brittle (above). Fraud recall on unseen wording is the safety-relevant gap; mitigated in production by the real model + keyword list + code table (asymmetric rule), and measured by B4 on T1.
3. The validator excludes outcome words inside located consumer quotes. A consumer letter that says "this was verified" can therefore appear quoted in a draft; it is marked as a quote and the outcome sentence still comes from the template.
4. A timed-out attempt's worker thread keeps running in the background until the SDK's own timeout (also 60s) ends it.
5. `map_claims` sends EV-ACCOUNT content (minus transactions) to the model; for long account histories that is token-heavy. Trim when the real model is wired.

## Contract-change requests (integrator)
1. **Config:** `llm_max_calls_per_case` default 4 → **5** (or PRD R-15 restated as "per step, plus one validator retry"). Diff in `src/disputes/config.py`: `llm_max_calls_per_case: int = 5`. Needs PM sign-off since it changes R-15.
2. **Optional domain addition** (not required; the budget side channel works today): `Classification.llm_suspicious: bool = False` so the flag is persisted with the classification artifact instead of only on the budget.

## What the integrator needs to wire up (pipeline)
- `make_budget` already builds `CaseBudget(llm_client, cfg)` and `flush_model_calls` reads `budget.records`: works as is.
- **R-14 LLM flag is not yet used.** `detect_suspicious` runs before classify. After classify / extract_claims, if `run.budget.suspicious_flag` is true, re-run `deps.detect_suspicious(d, findings, llm_flag=True)` and record the result (LOW alone; never changes the outcome). Reasons are in `budget.llm_flags` [(step, reason)].
- **R-08/R-10 free-text-note flag is not yet passed.** Call `decide(..., llm_note_flag=run.budget.note_conflict)` once `map_claims` has run (reason text in `budget.note_conflict_reason`).
- `draft_narrative(decision, claims, evidence, budget)` works as called (it rebuilds quote sources from EV-ATT-* `extracted_text` and EV-ACDV `free_text`); optionally pass `source_texts=claims.source_texts(dispute)`.
- Settings `DISPUTES_LLM_BACKEND`: use `agents.llm.make_client(settings.llm_backend, cfg)`.
- Evidence content shapes the agents rely on (all match `rules/evidence.py` on main): cycle `cycle_month`, `dpd_at_cycle`, `reported_rating`; note `type`, `start_date`, `end_date`; free-text note `text`; attachment `attachment_id`, `extracted_text`; ACDV `free_text`.

## Self-review (developer checklist)
- Every acceptance criterion in scope (S2, S4 claim parts, S5 draft/LLM parts) has a passing test I ran. Yes.
- Every model call logged with model ID, prompt hash, input hashes, output, tokens, cost, attempt. Yes (`LlmCallRecord` per attempt).
- Injection via uploaded documents: data is delimited and escaped; the model has no tools; outcome text only from templates; 40/40 twins and 20 hand-written attacks unchanged. Novel attacks remain a residual risk (B5 measures enumerated attacks only).
- Missing/malformed input fails safe: bad JSON/schema → retry → LLM_UNAVAILABLE; bad mapping → UNADDRESSED_CLAIM; unlocated quote → QUOTE_UNLOCATED; invalid draft → DRAFT_INVALID.
- No PII in logs from this module (only template IDs and model IDs are logged).
- Stubbed/faked items are listed above.
