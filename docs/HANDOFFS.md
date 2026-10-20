# Handoffs

Append new entries at the bottom. Newest last. Mark an entry **RESOLVED** (with date) when the ask is done.

Format:
```
## YYYY-MM-DD | from -> to | short title
- Produced: <file path(s)>
- Need back: <specific ask>
- Open questions: <list or "none">
- Status: OPEN
```

---

## 2026-10-19 | founders -> market-research | Kickoff: validate the wedge
- Produced: `CLAUDE.md`
- Need back: (1) competitor map for furnisher-side dispute automation, (2) who owns dispute handling at mid-size banks, card issuers, and lenders and how it's staffed today, (3) rough bottom-up market sizing, (4) regulatory landscape summary with sources.
- Open questions: Which furnisher segment feels the most pain: card issuers, auto lenders, fintech lenders, or credit unions?
- Status: RESOLVED 2026-10-19 (desk research delivered in docs/research/; segment answer is hypothesis pending discovery calls, see U1)

## 2026-10-19 | founders -> product-manager | Kickoff: draft the problem brief
- Produced: `CLAUDE.md`
- Need back: problem brief and a first-cut ICP hypothesis, to be pressure-tested against research when it lands.
- Open questions: none
- Status: RESOLVED 2026-10-19 by product-manager: problem and value hypothesis in docs/product/icp-and-wedge-memo.md and PRD §1; ICP pressure-tested against research

## 2026-10-19 | developer -> product-manager | Feasibility note: MVP core loop
- Produced: `docs/engineering/feasibility-core-loop.md`, `docs/engineering/STATUS.md`; updated `docs/UNKNOWNS.md` (U2 partly resolved; added U6-U10)
- Need back: answers to the 9 questions in section 9 of the note, mainly the first channel (ACDV vs Reg V direct) and dispute category, the pilot deployment model and LLM hosting constraint, the review policy, Metro 2 in or out, and the eval go/no-go thresholds. These are inputs to the PRD and to ADRs 001-010.
- Open questions: (1) Which channel and single dispute category go first? (2) Our SaaS or the customer's cloud for the pilot? (3) Is a hosted LLM with zero retention acceptable? (4) Is 100% human review in the MVP? (5) Metro 2/AUD in or out? (6) Eval thresholds? (7) Audit retention period and export format? (8) Can a design partner sponsor e-OSCAR Stage access and share the middleware-vendor requirements? (9) Who verifies deadlines and code lists with counsel?
- Status: RESOLVED 2026-10-19 (all 9 answered in PRD v1 Appendix A/B and reviewed by developer; founder confirmations now tracked in docs/product/founder-decisions.md). Earlier note: (answered 2026-10-19 by product-manager in docs/product/prd-mvp-v0.md Appendix A/B; awaiting founder confirmation of Q1-Q4, Q6-Q9 and developer review per the new handoff below)

## 2026-10-19 | market-research -> product-manager | Wedge, competition, regulatory evidence for ICP memo and MVP PRD
- Produced: `docs/research/wedge-segments-and-buyers.md`, `docs/research/competitive-landscape.md`, `docs/research/regulatory-and-enforcement-landscape.md`; updated `docs/UNKNOWNS.md` (U1, U4, U5 refined; U2 note; U11-U16 added) and the Verification Log in `docs/reference/furnisher-dispute-primer.md` (10 rows).
- Findings that matter:
  1. **Channel: ACDV first** (A): ACDV duties (FCRA 623(b)) are privately actionable; direct-dispute duties under 623(a)/Reg V 1022.43 are not (623(c)-(d)). Timeline for both is the CRA's 30-day (+15 conditional) 611(a)(1) window, so furnishers have less than 30 days. Courts are widening what must be investigated ("objectively and readily verifiable", 4th Cir. 2025, B). Fallback if no design partner can sponsor e-OSCAR: Reg V direct-dispute triage (CRO exclusion, sufficiency, 5-business-day frivolous notice).
  2. **First category:** account status / balance / payment history (verifiable against the system of record; avoids 605B identity theft). Opinion, based on A-grade duties and B-grade case law.
  3. **Segment: mid-market nonbank lenders (fintech unsecured/cards, independent auto) with ~500-5,000 disputes/month; regional banks second.** Grades B/C, no interviews yet. Top-10 issuers use in-house plus BPO (HCLTech case, B/C); credit unions are too low ACV except via CUSO channel.
  4. **Buyer map (hypothesis):** economic buyer = head of lending/servicing ops (COO at fintech); champion = credit bureau disputes manager; users = specialists at $23-31/hr (A, job postings); blockers = compliance/FCRA officer, vendor risk and InfoSec, model risk, e-OSCAR admin.
  5. **Competition:** no dominant AI-native furnisher-side vendor found (medium confidence). Main alternative is the e-OSCAR UI (86%) plus spreadsheets (77% for direct) (C/B survey). Closest software: PMG Case Central (workflow, no AI claims); watch Bloom Credit in fintech. Differentiate on cited-evidence investigation plus examiner-ready audit record.
  6. **Pricing hypothesis:** platform fee ~$30-60K/yr + $3-5/dispute (ACV $60-150K); needs a fee floor. Assumption-grade.
  7. **Size:** TAM ~$180M (range $60-420M); SAM ~$41M (range $6-119M); SOM yr3 $0.3-2.25M ARR. A wedge, likely not venture-scale alone; the expansion story must be part of the pitch.
  8. **Disconfirming:** CFPB has retrenched (~70 exams in 2026 vs ~600/yr; dispute-investigation guidance withdrawn May 2025, B), so lead urgency with litigation and accuracy; only 27-32% of furnishers want more AI/automation now (C/B), so position on defensibility, not autonomy.
- Need back: (1) ICP memo using finding 3 and 4 as hypotheses to test; (2) PRD answer to feasibility Q1 (we recommend ACDV, account status/balance/payment history, with direct-dispute triage as fallback); (3) a discovery interview plan of 10 calls (4 fintech, 3 auto, 3 regional bank) capturing volume, FTEs, systems of record, LLM hosting policy, last tooling purchase and pricing reactions (resolves U1, U5, U7, U9, U13, U14).
- Open questions: counsel items listed in the regulatory report (CRO exclusion analogue for ACDV; weight of withdrawn guidance; AI-draft liability; retention). Pricing is a founder decision.
- Status: RESOLVED 2026-10-19 by product-manager: (1) docs/product/icp-and-wedge-memo.md; (2) docs/product/prd-mvp-v0.md Appendix A Q1 (ACDV, payment history, Reg V triage fallback); (3) docs/product/discovery-plan.md. Counsel items carried into PRD §8 and §13 Q4.

## 2026-10-19 | product-manager -> developer | Feasibility and effort review of PRD MVP v0
- Produced: `docs/product/prd-mvp-v0.md` (answers to your 9 questions are in Appendix A; eval thresholds in Appendix B), `docs/product/icp-and-wedge-memo.md`, `docs/product/discovery-plan.md`; DECISIONS.md rows (PROPOSED); UNKNOWNS.md U3/U10 notes and U17-U20.
- Need back: a feasibility verdict and effort range (1 vs 2 engineers) written into PRD §14, plus any requirement you would cut or change and why. I am least sure about these:
  1. **R-09** per-month expected-rating derivation from days past due, given that the Metro 2 rating values and cycle-date logic are unverified placeholders. Is a versioned placeholder table enough to build against?
  2. **R-11** claim extraction with character spans plus a mandatory claim-to-evidence mapping. What reliability can we expect, and does the UNADDRESSED_CLAIM escalation make over-escalation (Appendix B, ≤20%) unachievable?
  3. **R-13** validator: checking quotes verbatim, and deciding which narrative sentences are "factual" (so need a citation) without an LLM judge.
  4. **R-14** detecting suspicious content. What is a realistic false-positive rate, given that it triggers supervisor approval (R-19)?
  5. **R-22** PDF/HTML export in 10s or less, and **R-24** focused-tab active-time instrumentation in the minimal UI.
  6. **R-28** p95 of 120s or less from intake to draft, with up to 3 LLM calls per case.
  7. Whether **R-06**, combining a deterministic code mapping with the LLM class (escalating on disagreement), is sound when the code list is unverified (U6).
  8. Whether Appendix B's hard floors (false-verify ≤0.5%, escalation recall ≥98%, unsupported claims ≤1%) are measurable with statistical meaning on a 200-case set, or whether the set needs to be larger.
- Open questions: none blocking. Founder decisions pending on segment, review policy, eval thresholds, pilot hosting and counsel (PRD §13 Q1-Q4, Q9). Please do not start the build past ADRs and the synthetic generator until the founders confirm Q1-Q3.
- Status: RESOLVED 2026-10-19 by developer: docs/engineering/prd-feasibility-review.md (§14 text in its §8 item 18; PRD not edited per lane rules)

## 2026-10-19 | developer -> product-manager | PRD MVP v0 feasibility verdict: feasible with changes
- Produced: `docs/engineering/prd-feasibility-review.md`; updated `docs/engineering/STATUS.md`, `docs/UNKNOWNS.md` (U8 and U20 notes; U19 statute text verified; added U21-U25), Verification Log in `docs/reference/furnisher-dispute-primer.md` (15 USC 1681p, 5 USC 6103).
- Verdict: **feasible with changes, medium confidence.** The deterministic core (R-01-R-05, R-08-R-10, R-20, R-21) is low risk.
- Top issues:
  1. **The Appendix B hard floors cannot be measured on 200 cases.** False-verify ≤0.5% needs about 600 should-not-verify cases with zero failures. Escalation recall ≥98% needs 149 of 149. Injection "0" on about 20 cases shows only ≤14%. I propose a tiered eval: 200 human-labelled cases, a stratified safety set of about 1,000, a red-team suite of 100 or more, and property tests proving the VERIFY invariant (review §6).
  2. R-11 and R-13 are underspecified. Fix: the system locates quote spans in code, and the draft is built from cited sentences plus templates.
  3. R-14 as written will over-flag normal consumer letters.
  4. Four internal contradictions (review §3).
- Effort: **10-12 weeks with 2 engineers, 18-21 weeks with 1** (was 5-7 / 8-12), plus about 100-130 founder labelling hours. The PRD as written adds 3-5 engineer-weeks. Ranked cuts are in review §5 (to about 9-10 weeks with 2 engineers). **The 1-engineer path is too slow for the 90-day e-OSCAR-sponsor fallback clock. I recommend 2 engineers.**
- Need back: apply or reject the 18 changes in review §8 (paste-ready), including the Appendix B rewrite and the §14 sign-off text. Take the tiered eval design to the founders with PRD Q3. Answer U21 (business-day calendar and time zone) with counsel or a design partner.
- Open questions: (1) Do the founders accept tiered evals in place of the 200-case floors? (2) Do you accept the mock SoR supplying DPD for each month (R-09)? (3) Should R-19 become Must for DELETE? (4) Do you accept the new ADR-011 to 013?
- Status: RESOLVED 2026-10-19 by product-manager: PRD v1 applies changes 1-13 and 15-18 in full and 14 in part; answers (1) taken to founders as PRD Q3 / founder-decisions.md #4, (2) yes, (3) yes, and also for HIGH suspicious content, (4) yes. U21 placeholder set in R-05 and added to counsel questions. See the PM -> developer entry below for the one change not fully applied.

## 2026-10-19 | product-manager -> developer | PRD v1: your review applied; one change applied in part
- Produced: `docs/product/prd-mvp-v0.md` (v1, change log at top; §14 filled; Appendix B rewritten as tiers T0-T3 with go/no-go rules B1-B17); DECISIONS.md rows revised; UNKNOWNS.md U8, U20, U21, U24 notes, U26-U27 added.
- **Declined in part: REV §8 #14, over-escalation as report-only.** I keep it as a tolerance gate on synthetic T3 (point ≤20%, CI reported; >30% after 2 iterations is a kill). Reason: it is the only metric that stops "escalate everything" from passing B2-B4. It makes no real-data claim. If you think the synthetic estimate is too generator-controlled to gate on, propose a fix (e.g. a fixed clean-case mix in T1) rather than dropping it.
- Also note: claim recall <90% is a no-go (stricter than your report-only); new IDs R-30 to R-36 for your missing NFRs; T1 now has a ≥200 clean should-verify stratum and ≥150 fraud stratum; B5 compares each injection variant with a clean twin.
- Need back: confirm the T1 strata and B5 twin design are buildable inside your 2.0-2.5 eng-week R-26 estimate, or give the delta. Hold the build past ADRs and generator v0 until the founders clear decision 0 and Q1-Q3 in `docs/product/founder-decisions.md`.
- Open questions: none blocking.
- Status: RESOLVED 2026-10-19 by product-manager (superseded): decision 0 and Q1-Q3 are now decided by Sriram; eng-week deltas no longer drive the plan (agent build, PRD v1.1 §12). The T1-strata and B5-twin buildability check moves into the Stage 0 handoff below.

## 2026-10-19 | product-manager -> founders | PRD v1 ready: decisions needed
- Produced: `docs/product/founder-decisions.md` (one-page brief: 8 decisions ordered by urgency, next 7 days, go / not-yet), `docs/product/prd-mvp-v0.md` v1 (developer-reviewed), `docs/product/icp-and-wedge-memo.md` (timeline note), DECISIONS.md (PROPOSED rows), UNKNOWNS.md (U26-U27).
- Need back: **first, decision 0** (each founder checks his own employment, invention-assignment and conflict-of-interest terms; gating; not legal advice). Then decisions 1-4 by 2026-10-26, team size by 2026-11-02, counsel engagement by 2026-11-09. Tell the PM the outcomes so the DECISIONS rows move to DECIDED.
- Recommendation: NOT YET on hiring and build start; GO on discovery calls, ADRs and the synthetic generator once decision 0 clears. Flip criteria are in the brief.
- Open questions: none beyond the brief.
- Status: RESOLVED 2026-10-19: Sriram answered in chat on 2026-10-19 (recorded in the founder -> product-manager entry below, DECISIONS.md and the rewritten founder-decisions.md)

## 2026-10-19 | Sriram (founder, in chat) -> product-manager | Answers to the open decisions
- Produced: founder decisions, relayed to the PM: (1) employment gate cleared (his statement; not verified); (2) sole founder, Navneet no longer involved; (3) Phase 1 uses no interviews, discovery deferred to Phase 2; (4) wedge accepted; (5) review policy accepted; (6) tiered eval with ≈100 human-labelled cases by Sriram alone; (7) developer agent builds, Sriram reviews in gated stages; (8) pricing test, FCRA counsel and hosted-LLM decision still open or deferred.
- Need back: record and apply.
- Open questions: none.
- Status: RESOLVED 2026-10-19 by product-manager: DECISIONS.md (DECIDED rows), UNKNOWNS.md (U26 cleared, U27 n/a, U28-U32 added), founder-decisions.md rewritten as a status page, PRD v1.1, ICP memo and discovery-plan headers, CLAUDE.md founders line and priorities

## 2026-10-19 | product-manager -> developer | STAGE 0 APPROVED (only): ADR-001 to 010 and the synthetic generator with fixtures
- Produced: `docs/product/prd-mvp-v0.md` **v1.1** (§12 stages and Phase 1 exit gate; Appendix B restated for a ≈100-case T3 and one labeller); `docs/product/founder-decisions.md` (status page); DECISIONS.md (Sriram's DECIDED rows); UNKNOWNS.md (U26 cleared, U27 n/a, U28-U32).
- **Approval:** Sriram approved the build approach (developer agent builds, Sriram reviews in gated stages) on 2026-10-19. **Only Stage 0 is approved.** Do not start Stage 1 work (DB/audit-chain implementation, intake, rules, LLM calls, UI) until Sriram approves it in a new HANDOFFS entry. Your REV §7 M0/M1 items beyond the list below (audit chain + `verify`, kappa trial) move to Stage 1 or are replaced.
- **Stage 0 scope:**
  1. **ADRs 001-010** as listed in `docs/engineering/prd-feasibility-review.md` §7, in `docs/engineering/adr/` using `docs/templates/adr.md`: 001 Stack; 002 Queue; 003 Audit log (design only; must satisfy R-21, R-23, R-32); 004 Integration boundary (canonical `Dispute`, `AcdvSource`, `SystemOfRecord`, `ResponseSink`, `LlmClient`; R-01, channel-agnostic so the Reg V fallback can reuse it); 005 LLM usage (R-11 to R-13, R-15, R-30); 006 LLM hosting (hosted, pinned, zero-retention on **synthetic data only**, swappable to in-VPC; name the provider terms and their verification status, U25; R-27, R-30; **this is PROPOSED and Sriram decides at the Stage 0 gate**); 007 Untrusted content (R-03, R-14, R-33, B5 twin design); 008 Tenancy (**recorded as deferred**: single tenant, reserved `tenant_id`); 009 PII (R-27, R-31; synthetic only); 010 Deadlines and rules (R-05, R-09, R-10; tables as data with `verified` and `source`, R-35; U21 placeholders). ADR-011 to 013 are Stage 1 unless you need to pull them forward; say so if you do.
  2. **Synthetic data generator v0 with fixtures**, in `src/`: seeded and deterministic; emits fixture ACDVs (with `fixture_schema_version`), mock SoR accounts with DPD per cycle and reported payment profiles, structured notes (HARDSHIP, DEFERRAL, FORBEARANCE, PRIOR_DISPUTE, OTHER) and simple text-native letters; placeholder reference tables (dispute-code map, Metro 2 rating map, holiday calendar, time zone) as versioned data with `verified=false` and `source`; every record `synthetic=true`. Requirements: R-26 (v0 subset: payment-history VERIFY/MODIFY/ESCALATE mixes, the edge cases in R-26, a first adversarial sample), R-01 fixture shape with adapter contract tests, R-35 table format, R-34 (a convention and check that eval-case text cannot enter the prompt library). **No real consumer data; no real-PII patterns** (CLAUDE.md).
  3. **A 20-case labelling trial set** plus a labelling rubric and a blank label sheet for Sriram (outcome, disputed months, claim labels), with the generator's intended labels stored separately and hidden from him.
  4. Update `docs/engineering/STATUS.md`.
- **Stage 0 exit check (what Sriram reviews):** ADRs readable and consistent with PRD v1.1; generator output identical for the same seed; contract tests pass; all records `synthetic=true`; tables carry `verified=false`; trial set ready.
- **Need back (in your Stage 0 handoff):** (a) the ADRs and generator paths; (b) **actual elapsed time and a forecast for Stage 1 (U28)**; (c) whether the T1 strata (≥600/≥150/≥150/≥200) and the B5 clean-twin design are buildable as specified, or the change you need; (d) a check of the ≈100-case T3 strata and the hand-computed bounds in Appendix B (B9, B10, B11, B12, B13); flag any error to the PM rather than editing the PRD; (e) your proposed Stage 1 scope if it differs from PRD §12.
- Open questions: none blocking. Model choice and provider terms are yours to propose in ADR-006; Sriram decides.
- Status: RESOLVED 2026-10-20 by developer: Stage 0 delivered; see the developer -> product-manager + Sriram entry below. Stage 1 NOT started.

## 2026-10-20 | developer -> product-manager, Sriram | STAGE 0 DONE: ADRs, generator v0, fixtures, 20-case trial (awaiting Sriram's gate review)
- Produced:
  - ADRs: `docs/engineering/adr/ADR-001-stack.md` through `ADR-010-deadlines-and-rules.md` (all Proposed).
  - Generator: `src/synthgen/`, with placeholder tables in `reference_tables/` (all `verified=false`) and JSON Schemas in `schemas/`.
  - Contracts: `src/disputes_core/contracts.py`.
  - Fixtures: `src/data/fixtures/seed20261019_n200/`.
  - **Trial for Sriram:** `src/data/stage0_trial/trial_cases.md` and `label_sheet.csv`. The generator's labels are kept apart in `src/data/stage0_trial_HIDDEN_generator_labels/`.
  - Tests: `src/tests/` (67).
  - How to run: `src/README.md`.
  - Updated: `docs/engineering/STATUS.md`; `docs/UNKNOWNS.md` (U25 partly resolved; U33-U36 added); Verification Log (SSA SSN rules, Anthropic ZDR page).
- **Test result (actually run 2026-10-20): 67 passed, 0 failed** (`cd src && ../.venv/bin/python -m pytest`, Python 3.13.16, pinned pytest 8.3.3, hypothesis 6.115.3, jsonschema 4.23.0).
  - Same seed gives byte-identical files, also across PYTHONHASHSEED values.
  - Every record is `synthetic=true`, and the schema rejects any other value.
  - No real-looking SSN or Luhn-valid card number appears.
  - Edge cases are 31% and adversarial cases 11% at n=200, against R-26 minimums of 15% and 10%. All 13 edge tags and all 7 adversarial tags are present.
  - Contract tests pass.
  - The R-34 isolation check passes, and it catches a planted contamination.
- **Exit-check status (PRD §12 Stage 0):**
  - ADRs written.
  - Deterministic: yes.
  - Contract tests: pass.
  - `synthetic=true` everywhere: yes.
  - `verified=false` on every table: yes.
  - Trial set: ready.
  - **Still to do, by Sriram:** label and time the trial.
- (a) Paths: above.
- (b) **Elapsed time (U28):** about 55 minutes of agent wall-clock (04:54Z to about 05:50Z, 2026-10-20), measured by the agent's own clock. Sriram's review hours are not yet known. **Stage 1 forecast [A, low confidence]:** 2-5 hours of agent wall-clock across several sessions, plus Sriram's 6-10 review hours (PM estimate). Stage 1 has stateful code (Postgres, the audit chain, property tests) that is harder to get right than a generator, and one data point does not support a forecast.
- (c) **T1 strata and B5 twins: buildable as specified, with one condition.**
  - A probe of 1,100 cases with a T1-weighted mix (`src/tests/test_t1_strata_feasibility.py`) reached the PRD minimums of ≥600, ≥150, ≥150 and ≥200:
    - should-not-verify: 759;
    - should-escalate: 484;
    - fraud-signal: 165;
    - clean should-verify: 330.
  - The B5 clean-twin design is implemented and tested. Twins match on content and get fresh control and account numbers, so a twin is neither a duplicate nor a repeat.
  - **Condition (U34):** v0 has only 3 fraud phrasings and 1 injection string per surface. A ≥150-case fraud stratum would be near-duplicates, and T2 needs ≥20 variants per surface. Generator v1 (Stage 2) must add variety and report distinct-variant counts before T1 and T2 are frozen. No PRD change is needed; this is a build note.
- (d) **Appendix B check: I recomputed every bound with exact Clopper-Pearson (scipy 1.18.1). No figure is wrong.**
  - Matches:
    - B2 0/598 → 0.4997%;
    - B3/B4 150/150 → 98.02%;
    - B7 0/300 → 0.99%;
    - B8 0/100 → 2.95%;
    - B9 19/20 → 78.4%;
    - B10 238/250 → 92.3%;
    - B11 46/48 → 87.5%, and 48/48 → 93.95%;
    - B12 40/200 → 25.2%;
    - B13 57/60 → 87.6%, and 60/60 → 95.1%;
    - pilot 0/100 → 2.95%, and 0/300 → 0.99%;
    - labelling 71.3-81.3 h;
    - R-28 9 s/case;
    - the T3 strata sum to 100, with 48 scored and 67 containing payment history.
  - One inconsistency to fix: **B13's tier column says ≈67 cases containing PAYMENT_HISTORY, but its example bounds use n=60.** At n=67 the bounds are 67/67 → ≥95.6% and 64/67 → ≥88.8%. Pick one denominator.
  - Minor: the "±7 pts" in B11 and "±12 pts" in B12 are half-widths of asymmetric intervals. B11 46/48 two-sided is [85.8%, 99.5%]; B12 10/48 is [10.5%, 35.0%]. They are fine as approximations, but I suggest reporting the interval itself.
- (e) **Stage 1 scope:** as PRD §12, with two additions I propose:
  1. a local CI script, because there is no remote repo yet;
  2. a test that every query carries `tenant_id` (ADR-008).
- **Where the PRD forced, or I chose, something different (flagged, not silently changed):**
  1. R-01 says fixtures are "shaped to the public e-OSCAR developer guide". The public pages do not publish the payload, so the fixtures use our own placeholder field names and are **not** claimed to match e-OSCAR (ADR-004).
  2. R-03 hidden text: the fixtures are text-native .txt files. Hidden text is represented by `render_hints.hidden_spans` and zero-width characters, and image-only PDFs by metadata. No real PDF bytes are generated, because a PDF library would be a new dependency. Stage 2 decides whether real PDFs are needed for R-03 tests.
  3. Gold labels come from a rules oracle that encodes the PRD rules, so they are circular for rule logic (U35). Production code is test-blocked from importing the oracle.
  4. The holiday table assumes a Sunday holiday is observed on Monday. 6103(b) states only the Saturday-to-Friday rule (U36).
  5. ADR-006 proposes the Anthropic API with ZDR and **discloses that the developer agent runs on an Anthropic model**, which is a potential bias. Bedrock is the main alternative.
- **What Sriram needs to review and decide before Stage 1 (about 2-4 h plus the trial):**
  1. Read ADR-001 to 010, then approve each or ask for changes. Priority order: ADR-006 (decide Q13, and whether to request ZDR for the org that will hold the API key, which Stage 2 needs), ADR-003, ADR-010, ADR-004, ADR-009.
  2. **Label and time the trial:**
     - Open `src/data/stage0_trial/trial_cases.md` and fill in `label_sheet.csv`, including the minutes column.
     - Do not open the HIDDEN folder until you are done.
     - Then send the minutes per case to the PM to re-state the labelling budget. Caveat (U33): v0 letters are short templates, so your minutes may understate T3 time.
  3. Decide Q12 (Phase 1 exit gate and the Reg V fallback clock).
  4. Log your review hours (U28, U32).
  5. Approve Stage 1 in a new HANDOFFS entry, or not.
- Need back:
  - PM: fix the B13 denominator, and re-state the labelling budget once Sriram reports his trial minutes.
  - Sriram: the five items above.
- Open questions: none blocking.
- Status: OPEN
