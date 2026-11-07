# Discovery Plan: First 10 Calls (PHASE 2, DEFERRED; Sriram runs it; nobody has been contacted)

> **Status 2026-10-19 (Sriram decision): DEFERRED to Phase 2. Not deleted.** Phase 1 builds from desk research with no interviews. This plan runs after the Phase 1 exit gate (PRD v1.1 §12), or earlier if Sriram pulls it forward. Until it runs, U1, U4, U5, U7, U9, U13, U14, U16, U17 and U18 stay open, and no pricing claim, pilot or hire may rest on them. Sriram is the sole founder and runs every call. Re-date the target finish when Phase 2 starts. The Reg V fallback clock (no e-OSCAR sponsor) is proposed to start on the first call.

> **v2 (2026-11-07, product-manager): re-targeted at the managed-service buyer** after Sriram's pivot decision (DECISIONS 2026-11-07; `managed-service-model.md`). We now sell "we run your disputes for you", priced per dispute, so the calls must also learn how furnishers handle or outsource disputes today, what they spend on BPOs, how their vendor-risk process works, and whether they would hand e-OSCAR work to a third party. New questions Q15-Q22 below; Q12-Q14 re-worded for a service; the call mix now covers both ICP bands (memo §9) and community banks and credit unions as controls. The pivot's kill criteria K1-K5 (memo §11) are scored from these calls. **PROPOSED (decision D2): run these calls in parallel with Stages 1-3 rather than after the Phase 1 exit; Sriram decides.** Nothing here has been sent to anyone. Adds U37, U38, U41, U42 and U44-U48 to what the calls resolve.

**Date:** 2026-10-19 (v2 2026-11-07)  **Owner:** product-manager  **Goal:** confirm or kill the wedge in `icp-and-wedge-memo.md` (resolves U1, U4, U5, U7, U9, U13, U14, U16, U17, U18; Phase 2 also adds the U29-U31 practitioner checks in PRD §12). **Target finish:** ~~2026-11-27~~ to be set when Phase 2 starts.

**Who to call (v2, service model):** 10-12 calls: 4 fintech/online lenders (include BNPL where it furnishes), 3 independent auto finance companies, 2 community banks, 1-2 credit unions (control groups for the bank-oversight and CUSO-incumbent questions). **Split each segment across both ICP bands:** firms with an in-house team of 3+ and a named disputes manager (the 2026-10-19 ICP), and firms where disputes are handled part-time, by 1-3 people, or already outsourced (the service hypothesis). Talk to whoever owns disputes, plus the COO or head of servicing and, where possible, the compliance officer. Optionally, 1 conversation with a former BPO or CUSO dispute-operations lead for competitor pricing and staffing signals (no confidential information solicited).
~~**Who to call (v1):** 4 fintech/online lenders, 3 independent auto finance companies, 3 regional banks ($10-100B, the control group).~~ Talk to the **credit bureau disputes manager or director** (the champion); add the head of ops or the COO where possible. Firms should have an estimated 500-5,000 disputes a month and an in-house team. Do not call BPOs or vendors in this round. Source the calls from Sriram's professional and Tepper networks, public sources and LinkedIn job titles (for example "Credit Bureau Disputes"), excluding any current or former employer's confidential information or relationships. The calls are 45 min, framed as research rather than a pitch, and nothing confidential is solicited. Show no demo until question 14.

## Question guide (ask for numbers, not opinions)
**Current process**
1. Walk me through the last ACDV you worked, from start to finish. Which systems did you touch, and how many minutes did it take?
2. How many ACDVs and direct disputes do you get a month? Which categories are they? **What share is payment history?** (U18)
3. How many FTEs work on disputes, in-house or outsourced, and what do they cost? (U13: compute the cost per dispute)
4. Which systems of record do you pull evidence from (servicing core, card platform, document store)? (U9)

**Pain and trigger**
5. What last forced a change in your dispute process: a lawsuit, an audit or exam finding, sponsor-bank pressure, or volume? (U14, U16)
6. How do you prove a "reasonable investigation" today if someone challenges it? Show me what you would hand to counsel.
7. What did your last FCRA lawsuit or finding cost in time and money? (U17)

**Build vs buy**
8. What have you built or bought for disputes? Have you used a BPO, PMG, Bloom, or core-processor modules? Did you evaluate anything and reject it, and why? (U4, U15)
9. Who signed your last operations-tooling purchase, how long did security review take, and what did it cost?

**LLM and data handling**
10. Could dispute PII go to a hosted LLM under zero-retention terms? Does it have to be in your VPC or cloud? Who decides? Have you approved any GenAI vendor yet? (U7)

**e-OSCAR and middleware**
11. Do you use the e-OSCAR web UI, the API, or a middleware vendor? Would you authorize a third-party provider under the e-OSCAR addendum? Could you sponsor Stage access or share the developer guide? (U2, U6)

**Outsourcing and the service model (v2; ask before WTP)**
15. Have you ever outsourced dispute handling (a BPO, a CUSO, your servicer, a collection partner)? What did it cost (per dispute, per FTE, minimums), why did you start or stop, and what went wrong? (U37, U38)
16. Who would have to approve handing ACDV handling to an outside firm: who signs, and who can veto (compliance, vendor risk, the board, a sponsor bank)? (U37, U16)
17. Walk me through your vendor-risk process for a provider that sees consumer data: what do you require (SOC 2 Type I or II, pen test, insurance, background checks, onshore staff, subprocessor list), and how long did the last approval take? (U46, U41)
18. Would you let a provider work ACDVs **as your authorised agent in e-OSCAR** (the third-party addendum), or would you rather export ACDVs to them and submit their responses yourself? Who names the `dfAuthorizedName`? (U2, U42)
19. How would a provider get the evidence: read-only access to your servicing system, a daily extract, or your staff answering lookups? What has your security team allowed before? (U44)
20. Which disputes would you insist on deciding yourselves (identity theft, deletes, hardship programmes, attorney letters)? Roughly what share of your disputes is that? (U45)
21. What service levels would you need (days before the CRA due date, escalation turnaround, reporting), and what would you want as proof of quality each month? (U48)
22. If an outside team staffed by trained analysts (not credentialed specialists) ran your disputes on an AI platform with a full audit record, what would worry you most? (U37, U48)

**Willingness to pay** (ask before the demo; v2 wording for a service)
12. Van Westendorp **per completed dispute for the service** (and, as a secondary, per year for software only): at what price is it too cheap to trust, a bargain, getting expensive, too expensive?
13. Which do you prefer: (a) per dispute only, (b) per dispute plus a monthly minimum, (c) per dispute plus onboarding fee, or (d) software only (platform fee plus per dispute)? Which budget line would it come from: operations, compliance, or an existing BPO line?

**Close**
14. [Show the 1-page concept of the service] What is wrong with this? Would you run an 8-week **shadow** pilot in which our analysts work your real ACDVs in parallel and your team still submits? What would block it?

*Order in the call (v2):* Q1-Q11, then Q15-Q22, then Q12-Q13, then Q14. Keep to 45 minutes by dropping Q4 and Q9 for firms that already outsource.

## Interpreting the answers (record each call in a shared table: segment, volume, FTEs, $/dispute, PH share, LLM policy, e-OSCAR mode, WTP range, pilot interest)
| Answer pattern | What it means |
|---|---|
| ≥4 of 7 nonbanks: ≥500/mo, dispute quality is a top-3 pain, hosted LLM OK | **Confirms** the segment |
| ≥2 firms willing to sponsor e-OSCAR Stage or share the guide | **Confirms** the ACDV channel |
| ≥3 firms whose acceptable price range includes $30K plus $3 per dispute | **Confirms** pricing to test in the pilot |
| ≥1 firm agrees to a shadow pilot in principle | **Confirms** we proceed to the Phase 3 PRD |
| ≥5 of 7 already have a tool or BPO they are happy with | **Kills** the segment, so consider banks or a BPO channel |
| Acceptable WTP under $1 per dispute, or "cost center, we won't buy" | **Kills** the pricing model. Re-test as defensibility insurance, or stop |
| ≥5 of 7 ban PII to a hosted LLM | **Re-scope** to in-VPC hosting before the pilot; adds effort |
| No one will share e-OSCAR access | **Pivots** to Reg V direct-dispute triage |
| Payment history is under 25% of ACDVs at ≥3 firms | **Switches** the category to the largest verifiable one |
| ≥2 of 3 banks report a funded remediation mandate | **Reorders** segments: banks first |
| **v2 service rows** (recorded per call in the shared table: outsourced today Y/N, BPO price, approver chain, vendor-risk requirements and lead time, agent vs export preference, evidence-access mode, client-decided share, SLA asked for) | |
| ≥3 of 10 would consider handing ACDV handling to a third party (Q15-Q16) | **Confirms** the service premise. Fewer than 3 = pivot kill criterion **K1** |
| ≥5 of 10 say vendor risk or compliance would not approve a startup provider without SOC 2 Type II (Q17) | **K1** (kill or re-sequence behind SOC 2) |
| ≥1 firm will sign the e-OSCAR addendum or export ACDVs to us within 90 days of the first call (Q18) | **Confirms** an intake path. None = **K2** |
| Part-time or 1-3 FTE firms answer "yes" to Q15-Q16 more often than firms with 3+ person teams | **Supports** the ICP restatement (memo §9, D1); the reverse keeps the 2026-10-19 ICP |
| Client-decided share (Q20) above ~30% at most firms [O threshold] | **Re-scope**: the per-dispute economics weaken; price handbacks separately |
| ≥3 firms' acceptable per-dispute price exceeds our modelled cost at measured analyst minutes (Q12, analyst trial) | **Confirms** pricing to test in the pilot. Otherwise **K4** |
| Firms already outsourcing report BPO prices (Q15) | Sets the price ceiling and the comparison for "BPO-like cost" (U38) |

Market-research synthesizes the calls into `docs/research/discovery-synthesis.md`, and the PM re-scores the ICP within 2 days of call 10.
