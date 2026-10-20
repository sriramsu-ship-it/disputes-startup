# Discovery Plan: First 10 Calls (PHASE 2, DEFERRED; Sriram runs it; nobody has been contacted)

> **Status 2026-10-19 (Sriram decision): DEFERRED to Phase 2. Not deleted.** Phase 1 builds from desk research with no interviews. This plan runs after the Phase 1 exit gate (PRD v1.1 §12), or earlier if Sriram pulls it forward. Until it runs, U1, U4, U5, U7, U9, U13, U14, U16, U17 and U18 stay open, and no pricing claim, pilot or hire may rest on them. Sriram is the sole founder and runs every call. Re-date the target finish when Phase 2 starts. The Reg V fallback clock (no e-OSCAR sponsor) is proposed to start on the first call.

**Date:** 2026-10-19  **Owner:** product-manager  **Goal:** confirm or kill the wedge in `icp-and-wedge-memo.md` (resolves U1, U4, U5, U7, U9, U13, U14, U16, U17, U18; Phase 2 also adds the U29-U31 practitioner checks in PRD §12). **Target finish:** ~~2026-11-27~~ to be set when Phase 2 starts.

**Who to call:** 4 fintech/online lenders, 3 independent auto finance companies, 3 regional banks ($10-100B, the control group). Talk to the **credit bureau disputes manager or director** (the champion); add the head of ops or the COO where possible. Firms should have an estimated 500-5,000 disputes a month and an in-house team. Do not call BPOs or vendors in this round. Source the calls from Sriram's professional and Tepper networks, public sources and LinkedIn job titles (for example "Credit Bureau Disputes"), excluding any current or former employer's confidential information or relationships. The calls are 45 min, framed as research rather than a pitch, and nothing confidential is solicited. Show no demo until question 14.

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

**Willingness to pay** (ask before the demo)
12. Van Westendorp, per dispute and per year: at what price is it too cheap to trust, a bargain, getting expensive, too expensive?
13. Which do you prefer: (a) platform fee plus per-dispute, (b) per-dispute only, or (c) per seat? Which budget line would it come from?

**Close**
14. [Show the 1-page concept] What is wrong with this? Would you run an 8-week shadow pilot on real ACDVs with your own team reviewing? What would block it?

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

Market-research synthesizes the calls into `docs/research/discovery-synthesis.md`, and the PM re-scores the ICP within 2 days of call 10.
