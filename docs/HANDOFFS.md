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
- Status: OPEN

## 2026-10-19 | developer -> product-manager | Feasibility note: MVP core loop
- Produced: `docs/engineering/feasibility-core-loop.md`, `docs/engineering/STATUS.md`; updated `docs/UNKNOWNS.md` (U2 partly resolved; added U6-U10)
- Need back: answers to the 9 questions in section 9 of the note, mainly the first channel (ACDV vs Reg V direct) and dispute category, the pilot deployment model and LLM hosting constraint, the review policy, Metro 2 in or out, and the eval go/no-go thresholds. These are inputs to the PRD and to ADRs 001-010.
- Open questions: (1) Which channel and single dispute category go first? (2) Our SaaS or the customer's cloud for the pilot? (3) Is a hosted LLM with zero retention acceptable? (4) Is 100% human review in the MVP? (5) Metro 2/AUD in or out? (6) Eval thresholds? (7) Audit retention period and export format? (8) Can a design partner sponsor e-OSCAR Stage access and share the middleware-vendor requirements? (9) Who verifies deadlines and code lists with counsel?
- Status: OPEN (answered 2026-10-19 by product-manager in docs/product/prd-mvp-v0.md Appendix A/B; awaiting founder confirmation of Q1-Q4, Q6-Q9 and developer review per the new handoff below)

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
- Status: OPEN
