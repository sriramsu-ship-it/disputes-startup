# Feasibility and effort review: PRD MVP v0 (ACDV payment-history loop)

**Date:** 2026-10-19  **Author:** developer  **Reviews:** `docs/product/prd-mvp-v0.md` (draft, 2026-10-19)  **Status:** For PM. Nothing is built.
Labels: **[F]** sourced fact (grade), **[A]** assumption, **[O]** opinion. Statistics below are exact binomial (Clopper-Pearson) bounds that I computed. They are not from a source.

## 1. Verdict
**Feasible with changes. Confidence: medium.** [O]
- **The deterministic core is sound and low risk.** That covers intake, the clock, the per-month comparison, the outcome rules, the audit chain and the stub submit. "The system never proposes DELETE" and "VERIFY only from rules" are the right safety architecture.
- **Three things must change before building:**
  1. **The eval floors are not measurable on a 200-case set.** Zero false-verifies on the ~60 cases that should not verify only shows the rate is ≤4.9% (95% upper bound). It does not show ≤0.5%. That needs about 600 such cases with zero failures. Escalation recall ≥98% needs 149 of 149. Injection success "0" on about 20 adversarial cases shows only ≤14%. See §6.
  2. **R-11 (claims) and R-13 (factual sentences) are underspecified,** and as written they put an LLM judgement on the false-verify path. Two design changes fix this: locate quotes in code instead of asking the model for character offsets, and build drafts from cited sentences plus fixed templates. See §2.
  3. **Four internal contradictions** need fixing (§3).
- **The effort is larger than my earlier note:** 10-12 weeks with 2 engineers, 18-21 with 1. See §4.
- **What would change the verdict:** the founders refusing the tiered eval design (then the hard floors stay unprovable); or the PM keeping R-09 as DPD derived from raw transactions, R-11 as model-generated spans, and R-13 detecting "factual" sentences with an LLM (then add 3-5 engineer-weeks and accept a weaker safety argument).

## 2. Requirement-by-requirement review
Effort per requirement, as engineer time: **S** ≤3 days, **M** 1-2 weeks, **L** >2 weeks. ★ = flagged by the PM.

| ID | Verdict | Effort | Risk | What to change |
|---|---|---|---|---|
| R-01 | OK | S | Med (schema unverified, U6) | Add `fixture_schema_version` to each fixture. Adapter contract tests pin the shape so a real schema swaps in cleanly. |
| R-02 | OK | S | Low | List the required fields and what "unparseable" means (date formats, empty strings). |
| R-03 | Change | S | Med | "Unreadable" needs a testable definition, e.g. fewer than N extracted characters per page (config). Detect hidden or white text and zero-width characters, which are injection vectors, and feed them to R-14. Add a file size and page cap. |
| R-04 | OK | S | Low | Define "same account" as an account-number match. Define the repeat key as account + category. |
| R-05 | Change | S | Med | (a) Name the business-day calendar. 5 USC 6103 lists 11 federal holidays [F, A, LII], but whether CRAs or furnishers use that calendar, a Federal Reserve calendar or their own is **unknown (new U21)**. (b) Name the time zone of the due date. (c) Name the state for "past internal target but before due date". Today it is undefined; I suggest AT_RISK. |
| ★R-06 | Change | M | **High** | **The design is sound, with three fixes.** (1) R-07 needs MULTI_ISSUE, so the output must be a *set* of categories, not one enum value. (2) LLM self-reported confidence is poorly calibrated [O]. Replace "<0.8" with: the code mapping disagrees with the LLM, **or** the LLM returns UNCERTAIN. Keep the score for logging only. (3) Asymmetric fraud rule: if the code table, a keyword list or the LLM signals IDENTITY_FRAUD, the case routes out. **Caveat:** fixtures use the same unverified code table as the mapping, so evals cannot catch a wrong table. That is a circular test. Real codes are a pilot blocker (U6), not an MVP blocker. |
| R-07 | Change | S | Med | Contradicts F2 and S2 (see §3). One path: any IDENTITY_FRAUD signal → ESCALATED / ID_FRAUD_SUSPECTED, priority, no draft. |
| R-08 | Change | S | Med | Define "disputed months" as the months named in the ACDV **plus** the months found in claims (R-11). If no month can be identified → escalate MONTHS_UNDETERMINED. **Account notes must be structured in the mock** (type enum + date range). A free-text note may *add* an escalation; it can never remove one. Otherwise an LLM reading notes sits on the false-verify path. |
| ★R-09 | Change | S (as changed) / M-L (as written) | **High (domain)** | **Yes, a versioned placeholder table is enough to build against,** if it is data, not code, and carries `verified=false`. The system must refuse any non-synthetic run while any table is unverified. **The mock SoR should supply days past due at the cycle date for each month.** Deriving DPD from raw transactions (cycle dates, grace periods, partial payments, allocation) is the furnisher's logic, it varies by furnisher, and it is not needed to test the loop. Defer it. |
| R-10 | Change | S | Med | State the precedence: any escalation condition > MODIFY > VERIFY (for example, MISMATCH plus NO_DATA → escalate). **Add:** VERIFY is not proposed if any consumer claim is SUPPORTED or NOT_ADDRESSABLE. In that case → ESCALATED / CLAIM_UNRESOLVED. Property-based tests over thousands of generated inputs prove the invariant "VERIFY ⇒ every month MATCH ∧ no flags ∧ every claim CONTRADICTED". |
| ★R-11 | Change | **L** | **High** | **Do not ask the model for character offsets** [O: models are unreliable at offsets]. The model returns a verbatim quote, and code finds its span (exact, then whitespace and quote-normalised). No match → escalate. That makes span validity 100% by construction. **The real risk is claim-extraction *recall*** (missed claims = missed "relevant information"). It can only be measured if the golden set labels claims, so add a claim-level label and a recall metric to Appendix B. Define a "factual claim" as an assertion about a date, an amount, a payment event, account status or an agreement. **Over-escalation:** NOT_ADDRESSABLE is a valid mapping, so UNADDRESSED_CLAIM fires only on a missing or invalid mapping. Expect it to fire rarely on synthetic data. With my R-10 addition, CLAIM_UNRESOLVED will be the main driver. ≤20% is plausible on synthetic data because the generator controls the mix. It is **unknowable on real letters**, so make it report-only until the pilot. |
| R-12 | Change | M | Med | The draft is a list of sentence objects. Each **LLM-written** sentence has ≥1 evidence ID (quotes need a span). Connective or boilerplate text comes **only from a fixed, versioned template library**. The outcome text is a template slot filled from R-10. |
| ★R-13 | Feasible with R-12 change | M | Med | **Without an LLM judge you cannot decide which sentences are "factual". So don't:** treat every LLM sentence as factual (it must cite), and keep templates citation-free. Verbatim quote check after normalisation: S effort, reliable. Outcome check: the outcome is template-filled, plus a deterministic scan for outcome words in LLM sentences. **Gap:** the validator proves a citation *exists*, not that it *supports* the sentence. That is what the human-checked unsupported-claim metric measures. Say so in the PRD. |
| ★R-14 | Change | M | **High** | **A realistic false-positive rate is unknown, and could be large.** Genuine consumer letters are full of imperatives ("delete this late payment", "remove this account"). A naive pattern list would flag a large share of real letters and flood the supervisor queue [O]. Narrow the patterns to system-style injection: role markers ("SYSTEM:", "assistant:"), "ignore previous/instructions", tool or JSON syntax, hidden text and zero-width characters. Two severities; only HIGH triggers R-19. Measure FP on the non-adversarial golden cases. Target ≤5%, report-only until real data (new U23). **Redefine "injection success"** (Appendix B). The outcome can't be changed directly (it comes from R-10), so success means: the class changed, an escalation was suppressed, a claim was dropped, or the narrative was altered. |
| R-15 | OK | S | Low | Specify retries: 1 retry with backoff inside the 60s budget. State that the maximum number of LLM calls per case is 4 (see R-28). |
| R-16 | OK | M | Low | Largest UI item. Server-rendered pages are enough. |
| R-17 | Change | S | Low | Contradicts S4 (see §3). Approval is blocked until a human enters a finding for each unmapped claim, not "unless the narrative was written by the human". |
| R-18 | Change | S-M | Med | **Authentication is missing.** Add: SSO through a managed IdP, or local accounts with MFA. Add separation of duties: a supervisor cannot second-approve their own decision. |
| R-19 | Change → **Must for DELETE** | S | Low | The S6 acceptance criteria already test it, so it is not really a Should. Second approval for suspicious content applies to HIGH severity only. |
| R-20 | OK | S | Low | `dfAuthorizedName` is required per the April 2026 release notes [F, A, FEAS §1]. |
| R-21 | Change | M | Med | (a) **Add config and rules-table changes** (ADMIN actions) to the audited events. (b) Hash-chain writes must be serialised (a per-case chain plus a global head). (c) Insert-only access does not stop a DB superuser from rewriting the whole chain, so **anchor the chain head periodically to object-locked storage** (FEAS §3). (d) Log reads of a case by AUDITOR or ADMIN. |
| ★R-22 | Feasible | M | Low | ≤10s is easy for one case [O]. HTML is rendered from the same JSON. A PDF from HTML takes seconds. Specify that original attachments go in a zip bundle beside the export (hashes plus extracted text inside the export). |
| R-23 | OK | S | Low | 15 USC 1681p: suit within the earlier of 2 years from discovery or 5 years from the violation [F, A, LII, verified 2026-10-19]. So 7 years exceeds the outer 5-year limit. Counsel still sets the value. A "no delete path" may conflict with future privacy-deletion duties: flag for counsel. |
| ★R-24 | Change | M | Med | Focused time can be built: Page Visibility + focus/blur + an idle cutoff (no input for 60s, config) [O]. It is noisy, though. For G2, use **moderated sessions with screen-recorded timing as the primary measure** and the instrumentation as secondary. |
| R-25 | Change | M-L | Med | A full LLM eval on every change is slow, costs money and is non-deterministic. Hard floors on noisy samples will block merges at random. Instead: deterministic tests plus the red-team invariants on every PR; the full tiered eval (§6) on any prompt, model or rules change and nightly; a **no-new-errors paired check** in place of "±2 pts". |
| R-26 | Change | **L** | **High** | **The most underestimated item.** It needs realistic letters with labelled claims, consistent SoR data, structured notes, adversarial variants, and a stratified safety set (§6). **Circularity risk:** if gold outcomes come from the same logic as R-10, outcome accuracy is a tautology. Labelers must label from the evidence, blind to the generator's intent. |
| R-27 | Change | S-M | Med | Contradicts R-21 (see §3). Also: name the LLM provider's zero-retention terms in ADR-006. I have not verified any provider's terms. |
| ★R-28 | Feasible, keep as Should | S | Med | 3 sequential calls at roughly 5-30s each fit inside 120s [A]. The tail comes from a retry plus a 60s timeout (one timeout alone = 60s). p95 depends on the provider; measure it, don't promise it. 200 cases in ≤30 min needs about 9s per case of throughput, so concurrency of ~10 and the provider's rate limits (U25). |
| R-29 | OK | S | Low | Also show the rule ID for escalations, not only for proposals. |

## 3. Untestable, ambiguous, contradictory, missing
**Contradictions:**
- **R-06 vs R-07:** R-06 outputs one enum value, but R-07 needs MULTI_ISSUE.
- **R-07 vs F2/S2:** R-07 sends IDENTITY_FRAUD to OUT_OF_SCOPE; F2 and S2 send it to ESCALATED / CLASS_CONFLICT.
- **R-17 vs S4:** R-17 unblocks approval with a human narrative; S4 requires a human *finding* for each claim.
- **R-27 vs R-21:** R-27 masks PII in logs, but R-21 stores model inputs and outputs. Fix: the audit log is an encrypted record store with access control, and R-27 applies to operational logs and traces.
- **§10 vs §7:** §10 makes R-19 a Should, but S5 and S6 test it.
- **Appendix B:** "0 of ~120" is the wrong denominator. False-verify is measured over gold non-VERIFY cases, which number about 60.

**Ambiguous or untestable as written:** "factual claim" (R-11); "states a fact" (R-12, R-13); "instruction-like content" (R-14); "conflicting note" (R-10); the source of "disputed months" (R-08); the source of "confidence" (R-06); "focused tab time" (R-24); "priority" (R-07: a sort key? a separate queue?); the state between the internal target and the due date (R-05).

**Missing requirements (mostly non-functional):**
1. **AuthN and MFA; separation of duties** (R-18).
2. **Audit of config and rules changes and of record reads** (R-21).
3. **External anchor of the chain head** (R-21).
4. **Model pinning:** exact model ID and prompt hash per call, with behaviour defined if the provider retires a model.
5. **Retention for non-audit data** (LLM traces, eval outputs, attachments). Only audit retention is specified.
6. **Backup and restore** for the audit store: an RPO target, even for a prototype.
7. **Upload limits** (size, pages, nested archives).
8. **Reference-table gating:** every placeholder table carries `verified`, and non-synthetic mode refuses to start while any table is unverified.
9. **Eval-set isolation:** golden cases never appear in prompts or few-shot examples.
10. **LLM cost ceiling per case** (report).
11. **Latency for the reviewer's actions,** not just the case view.

## 4. Revised effort
**[A] Assumptions:** the §2 and §5 changes are applied. Server-rendered UI. Python/FastAPI/Postgres monolith (FEAS §3). Hosted LLM. Mock SoR supplies DPD at the cycle date. No OCR, no live e-OSCAR. Engineers are senior and have done LLM structured-output work.

| Work | Engineer-weeks |
|---|---|
| Foundations: repo, CI, DB, authN/RBAC, audit chain + anchor, config versioning | 2.0 |
| Intake, clock, dedup/repeat, state machine (R-01 to R-05) | 1.5 |
| Classify and route (R-06, R-07) | 1.0 |
| SoR mock, comparison, rules, explainability (R-08 to R-10, R-29) | 1.0 |
| Claims and mapping (R-11) | 1.5-2.0 |
| Draft, validator, injection, timeouts (R-12 to R-15) | 1.5-2.0 |
| Review UI, actions, supervisor, package (R-16, R-17, R-19, R-20) | 2.5 |
| Export and instrumentation (R-22, R-24) | 1.0 |
| Generator, safety set, red-team suite (R-26) | 2.0-2.5 |
| Eval harness and gates (R-25) | 1.5 |
| PII hygiene, threat model, deploy (R-27) | 1.0 |
| **Subtotal 16.5-18; with 15% integration buffer** | **~19-21** |

| Scenario | Range | vs. earlier (FEAS §7) |
|---|---|---|
| A: 1 senior full-stack | **18-21 weeks** | was 8-12 |
| B: 2 engineers (backend/LLM + full-stack/UI); work splits well, about 10% coordination loss | **10-12 weeks** | was 5-7 |
| PRD as written (no changes) | add 3-5 engineer-weeks (A: 21-26, B: 12-15) | n/a |

**Why it grew:** my earlier note assumed a single "draft with citations" step. The PRD adds:
- claim extraction with spans and a mandatory mapping (R-11);
- the suspicious-content workflow and a second approval;
- four roles and a supervisor path;
- PDF export;
- focused-time instrumentation;
- CI-gated evals;
- an adversarial plus edge-case generator;
- and, after this review, a 1,000-case safety set.

**Not in these numbers:**
- **Founder labelling:** about 200 cases × 2 labelers × 15-20 min, roughly **100-130 hours**, including claim labels;
- 10% spot checks of the safety set;
- the practitioner realism review (U20);
- discovery calls.

Confidence: medium-low. The largest swing factors are R-11 and R-26.

## 5. Cuts if scope must shrink (ranked: least value lost per week saved first)
1. **R-22 PDF** → HTML only (print to PDF from the browser). Saves about 0.5 engineer-weeks.
2. **R-24 in-app focused time** → event timestamps only; G2 is timed from session recordings. Saves 0.5-1.
3. **R-25 in CI on every change** → a scripted eval that must pass before merging prompt or rules changes, plus nightly runs. Saves 0.5.
4. **R-19 for suspicious content** → flag only; keep second approval for DELETE. Saves 0.5.
5. **R-28** → measure and report only. Saves tuning time.
6. **BALANCE / OTHER detail** → keep the classifier (it is needed for routing safety) but drop BALANCE-specific acceptance tests. Saves 0.25.

Together these save about 2.5-3 engineer-weeks, bringing scenario B to about **9-10 weeks** and A to about **15-18**. Getting below that means cutting R-11 claim mapping to report-only, which I do not recommend because it weakens the 623(b)(1)(B) story.

**Do not cut:**
- R-10 rules and their invariant tests;
- R-13 validator;
- R-14 delimiting;
- R-21 audit;
- R-26 generator;
- any escalation path.

## 6. Eval thresholds: can they be measured?
The planned 200-case set has about 120 PAYMENT_HISTORY cases. From the stated mix, roughly 60 should not be verified, 45-60 should escalate (24 PAYMENT_HISTORY plus 20 IDENTITY_FRAUD plus multi-issue cases), about 20 are adversarial, and about 96 are non-escalated cases with a scored outcome.

| Metric | Claim | What 200 cases can show | Cases needed |
|---|---|---|---|
| False-verify ≤0.5% | hard floor | 0 of 60 → ≤4.9% (95% upper); 1 of 60 → ≤7.7% | **598 should-not-verify cases with 0 failures** (947 if 1 failure is tolerated) |
| Escalation recall ≥98% | hard floor | 60 of 60 → ≥95.1% (95% lower) | **149 of 149** |
| ID fraud routed out 100% | hard floor | 20 of 20 → ≥86% | ≥149 for ≥98% |
| Injection success 0 | hard floor | 0 of 20 → ≤14% | It is a suite pass, not a rate (below) |
| Unsupported claims ≤1% | hard floor | 50 drafts × ~5 sentences = ~250 sentences; 0 → ≤1.2% | ≥300 sentences with 0 errors, **from ≥100 drafts**, because sentences in one draft are correlated |
| Outcome accuracy ≥95%, ±2 pts | tolerance | 91 of 96 → 95% CI 88-98%; SE ≈2.2 pts, so ±2 pts is noise | Replace with a paired no-new-errors check |
| Over-escalation ≤20% | tolerance | 19 of 96 → 95% CI 12-29% | Report-only until there is real data |
| Kappa ≥0.8 | gate | Workable on 200 | Kappa also on claim labels (50-case subset) |

**200 is enough for realism, labeller agreement, the rubric and the accuracy metrics. It is not enough for any hard floor.** Alternative method:
1. **Prove it by construction.** The VERIFY invariant (R-10) is shown by property-based tests over ≥10,000 deterministic inputs. That establishes false-verify as zero for the rule layer, which a sample cannot do. The tests then only need to measure the **LLM-dependent paths into a VERIFY**: a missed claim, a misclassified fraud case, or an injection.
2. **Stratified, generator-labelled safety set: about 1,000 cases.** It contains ≥600 should-not-verify cases (built to stress those LLM paths) and ≥150 should-escalate cases. Humans spot-check 10% of the labels. It runs nightly and on any prompt, model or rules change. LLM cost and time are moderate [A].
3. **Red-team suite: ≥100 injection variants.** The variants cover the letter body, hidden text, ACDV free text and file metadata. Each one must pass. Report it as "100 of 100 passed", never as "0%".
4. **Report every metric with its exact CI.** The claim "≤0.5%" is made only when the upper bound supports it.

**Caveat:** precision on synthetic data is not validity on real data (U20). The pilot gate must re-baseline on real labelled cases. 100 cases supports only about ≤3% at zero failures.

## 7. ADRs required before the build, and build order
| ADR | Decision (one line) |
|---|---|
| 001 Stack | Python + FastAPI + Postgres monolith with a server-rendered UI. |
| 002 Queue | Postgres `SKIP LOCKED` job table; no broker. |
| 003 Audit log | Insert-only, hash-chained events (per case + global head), head anchored to object-locked storage, `verify` command, config changes and reads audited. |
| 004 Integration boundary | Canonical `Dispute` model; `AcdvSource`, `SystemOfRecord`, `ResponseSink` and `LlmClient` adapters with versioned fixtures and contract tests. |
| 005 LLM usage | Structured outputs; quotes located in code; drafts built from cited sentence objects plus templates; outcome never from the LLM; no tools. |
| 006 LLM hosting | Hosted model under verified zero-retention terms for synthetic data; pinned model ID; swappable to in-VPC. |
| 007 Untrusted content | Delimited data; hidden-text detection; two-severity suspicious flag; red-team suite. |
| 008 Tenancy | **Deferred.** Single tenant with a reserved `tenant_id` column. |
| 009 PII | Masking in operational logs; the audit store is encrypted with access control; secrets in a manager; synthetic only. |
| 010 Deadlines and rules | Versioned code plus cited tables; business-day calendar and time zone per U21. |
| 011 Eval methodology (new) | Tiered: 200 human-labelled, about 1,000 stratified safety cases, ≥100 red-team cases; exact CIs; paired regression check. |
| 012 AuthN/AuthZ (new) | Managed IdP or local accounts with MFA; server-side RBAC; separation of duties. |
| 013 Reference-table verification gate (new) | Every placeholder table carries `verified` and a source; non-synthetic mode refuses to start while any table is unverified. |

**Build order.** This follows the PM's handoff: nothing past the ADRs and the generator until the founders confirm Q1-Q3.
- **M0, days 1-3:** ADR-001 to 005, 010, 011 and 013 drafted. Repo, CI and DB skeleton.
- **M1, end of week 1:** the generator v0 (structured ACDV and SoR records). A 50-case pilot set goes to the founders for a kappa trial on outcomes and claims (U8). Audit chain plus `verify`, with tests.
- **M2, week 2 (after Q1-Q3 are confirmed):**
  - intake, clock and state machine (R-01 to R-05);
  - mock SoR, R-09, R-10 and R-29, with the VERIFY-invariant property tests;
  - ADR-006, 007, 009 and 012.
- **M3, week 3:** generator v1 (letters, notes, adversarial cases); `LlmClient`, R-06 and R-07; eval harness v0 with a **first recorded baseline on classification and routing**; red-team suite v0.

## 8. Changes for the PM to apply to the PRD
1. **R-06:** "Output a set of categories. Escalate CLASS_CONFLICT when the code mapping and the LLM disagree or the LLM returns UNCERTAIN. Record confidence but do not gate on it. Any IDENTITY_FRAUD signal from the code, a keyword or the LLM routes the case out."
2. **R-07, F2 and S2:** use a single path, "IDENTITY_FRAUD signal → ESCALATED / ID_FRAUD_SUSPECTED, priority, no draft". Define "priority" as "sorts first in the supervisor queue".
3. **R-08:** "Disputed months = the ACDV months ∪ the claim months. If none → ESCALATED / MONTHS_UNDETERMINED. Notes are structured (type, date range). Free-text notes can only add escalations."
4. **R-09:** "The mock SoR supplies DPD at the cycle date for each month. The mapping table is data with `verified=false`. Deriving DPD from transactions is deferred."
5. **R-10:** add the precedence "escalate > MODIFY > VERIFY". Add "no VERIFY if any claim is SUPPORTED or NOT_ADDRESSABLE → CLAIM_UNRESOLVED".
6. **R-11:** "The LLM returns verbatim quotes, and the system locates the spans. An unlocatable quote escalates." Define "factual claim" (date, amount, payment event, status, agreement).
7. **R-12 and R-13:** "The narrative is a list of sentences. Every LLM-written sentence cites evidence. Non-cited text comes only from a versioned template library. The outcome is a template slot." Note that the validator checks that a citation exists, not that it supports the sentence.
8. **R-14:** narrow the patterns to system-style injection plus hidden text. Use HIGH/LOW severity; only HIGH needs R-19. Suspicious-flag FP on clean cases: report it, target ≤5%.
9. **R-17:** "Approval is blocked until a human enters a finding for each unmapped claim."
10. **R-18:** add authN with MFA and separation of duties. **R-19:** Must for DELETE.
11. **R-21:** add config and rules-change events, read events and an external head anchor. **R-27:** "Masking applies to operational logs and traces. The audit store is encrypted and access-controlled, and is not masked."
12. **R-05:** name the business-day calendar, the time zone, and the state between the target and the due date (U21).
13. **R-25:** "Deterministic and red-team tests on every PR. The full eval runs on prompt, model or rules change and nightly. A paired no-new-errors check replaces ±2 pts."
14. **Appendix B:** use the tiered sets in §6. Floors become (a) the R-10 invariant, proven by property tests; (b) zero false-verifies on ≥600 should-not-verify cases; (c) 149 of 149 or more on escalation recall; (d) 100 of 100 on the red-team suite; (e) unsupported claims measured on ≥100 drafts. Add **claim-extraction recall** (report, target ≥95%). Over-escalation becomes report-only. Fix the "~120" denominator.
15. **§4 G2:** split the practitioners' cases into two matched sets and counterbalance the order. Working the same 10 cases twice flatters the second pass.
16. **§12 Phase 1:** "10-12 weeks (2 engineers) or 18-21 weeks (1), plus about 100-130 founder labelling hours. 9-10 / 15-18 with the review §5 cuts."
17. **Add NFRs:** model pinning, non-audit retention, backup/RPO, upload limits, eval-set isolation, the reference-table gate (ADR-013), and an LLM cost report.
18. **§14 text to paste:** "Reviewed by developer on 2026-10-19: **feasible with changes**, medium confidence. See docs/engineering/prd-feasibility-review.md. Effort: 10-12 weeks (2 engineers) / 18-21 weeks (1), conditional on changes 1-17 and the tiered eval design. The hard floors are not provable on 200 cases."

---
*Self-review (developer checklist):*
- **Tests:** none, because nothing is built and nothing is claimed to work. The statistics come from a scipy run on exact binomial bounds.
- **Audit:** the missing events are listed: config changes, reads and the anchor.
- **PII and injection:** the R-21/R-27 conflict, hidden text, and the injection definition are covered.
- **Failure handling:** missing, conflicting or malformed input fails safe, and new escalations were added (MONTHS_UNDETERMINED, CLAIM_UNRESOLVED).
- **Determinism:** deadlines and the rating mapping stay deterministic and versioned.
- **Stubs:** declared in STATUS.md.
- **Regulatory facts:** only 15 USC 1681p and 5 USC 6103 were newly verified (LII, logged). The e-OSCAR facts come from FEAS sources. The business-day calendar, codes and Metro 2 values remain unverified.
- **Model-risk reviewer:** I would be comfortable defending the tiered-eval argument. I would not be comfortable defending a "≤0.5%" claim based on 200 cases.
