# ICP and Wedge Decision Memo

**Date:** 2026-10-19  **Owner:** product-manager  **Status:** Segment, channel and category **DECIDED by Sriram (2026-10-19)**, on desk evidence only. Pricing hypothesis remains PROPOSED and its test is **deferred to Phase 2**.
**v1.1 note (2026-10-19, Sriram decisions):** Sriram is the sole founder. **Phase 1 runs with no interviews**, so every hypothesis in this memo (segment, buyer roles, pricing, e-OSCAR sponsorship, LLM-hosting tolerance, payment history's share of volume) stays **untested through Phase 1**. The Phase 1 prototype can show only that the investigation, citation and audit loop works on synthetic data with measured safety behaviour (PRD v1.1, "What Phase 1 can and cannot prove"). The "first 10 calls" section below is the **Phase 2** test. The six-month pilot timing in "Options considered" was based on human-engineer estimates and no longer applies; Phase 1 calendar time is unknown (U28). The Reg V fallback clock is proposed to start at Phase 2 discovery. No price may be quoted before the evidence bar in PRD §12.
**Inputs:** `docs/research/wedge-segments-and-buyers.md` (WSB), `competitive-landscape.md` (CL), `regulatory-and-enforcement-landscape.md` (REG), `docs/engineering/feasibility-core-loop.md` (FEAS).

## Recommendation
- **Segment:** US **fintech / online consumer lenders (unsecured installment loans and cards)** that handle **about 500-5,000 disputes a month** with an in-house team of 3-15 and a named credit bureau disputes manager. **Independent auto finance** is the adjacent segment and gets the same product. **Regional banks** come second.
- **Channel:** **ACDV (indirect, via e-OSCAR)**. The MVP works alongside the e-OSCAR UI: we ingest the dispute and draft the response, and a human approves and submits it.
- **Single first category:** **payment history** (a disputed late-payment or delinquency rating on a specific month). The furnisher can check it field by field against its own payment ledger.
- **Confidence: low-medium.** This rests on desk research with grades B/C on segment and buyer and A on law. **We have had zero customer conversations.** The first 10 discovery calls can overturn every line in this section.

## Buying roles (hypothesis; WSB, grade B/C)
| Role | Who | What they need to hear |
|---|---|---|
| Economic buyer | COO or head of lending/servicing operations | Cost per dispute, and defensibility in litigation |
| Champion | Credit bureau disputes manager (the Upstart-type role, WSB S17) | Fewer late cases, consistent decisions, a record they can defend |
| User | Dispute specialist, $23-31/hr (A, job postings) | Evidence in one screen and a draft they can trust and edit |
| Blockers | Compliance/FCRA officer; vendor risk and InfoSec (PII sent to an LLM, U7); the e-OSCAR administrator (the ToU requires notice of automation tools, A) | Human approval on every response, a tamper-evident audit trail, zero-retention LLM terms, no auto-submit |

## Options considered (scores are opinion, 1-5 where 5 is best; evidence grade in brackets)
| Segment | Pain [B] | WTP [C] | Speed to buy [C] | Founder reach [O] | LLM tolerance [C] | **Total** |
|---|---|---|---|---|---|---|
| **Fintech / online lenders** | 4 | 3 | 5 | 3 | 4 | **19** |
| Regional banks ($10-100B) | 4 | 4 | 2 | 4 | 2 | 16 |
| Independent auto finance | 4 | 3 | 3 | 2 | 3 | 15 |
| Top-10 issuers | 3 | 5 | 1 | 4 | 1 | 14 |
| Mortgage/student servicers | 4 | 4 | 2 | 2 | 2 | 14 |
| Credit unions over $500M | 3 | 1 | 3 | 2 | 3 | 12 |
| Collectors | 3 | 1 | 4 | 1 | 3 | 12 |

Fintech wins on speed to buy and LLM tolerance. Both factors are assumptions, and they are what make a pilot achievable inside six months. **Updated 2026-10-19 after the developer's review (`docs/engineering/prd-feasibility-review.md` §4):** the prototype now takes 10-12 weeks with 2 engineers (18-21 with 1) from the engineers' start, plus 2 weeks of practitioner sessions. A shadow pilot can start inside six months **only on the 2-engineer path and only if hiring takes about 4-6 weeks or less** [A]. On the 1-engineer path it cannot. This does not change the segment ranking; it makes speed to buy matter more. Regional banks score close behind because of the founders' bank network and a CFPB focus that is moving toward banks (WSB #7, B). They lose on vendor-risk and model-risk friction.

| Channel | Why / why not |
|---|---|
| **ACDV (chosen)** | Private right of action under 623(b) (A). Highest volume and most structure. Courts keep raising the investigation bar (*Roberts*, 4th Cir. 2025, B). Requires e-OSCAR access through the customer (A). |
| Reg V direct | Not privately actionable (623(c), A). Messy letters. **No e-OSCAR dependency, so this is the fallback wedge** (as direct-dispute triage). |
| Both | Doubles intake work and adds 2-4 weeks (FEAS §7). Cut. |

| Category | Verifiable against the system of record | Risk | Pick |
|---|---|---|---|
| **Payment history** | Yes: ledger dates and amounts against the reported profile | Deferral and hardship arrangements cause conflicts (escalate) | **1st** |
| Balance / account status | Yes, but fee and interest logic varies | More furnisher-specific rules | Next (in the MVP it is classified only) |
| DOFD | Yes | Errors propagate across the whole tradeline (SH 2024, B) | Later |
| Identity theft / not mine | No; it follows 605B rules | High harm if wrong | **Route out** |

## Value hypothesis
**For** the credit bureau disputes manager at a fintech or online lender handling 500-5,000 disputes a month, **who** must complete a reasonable investigation of every ACDV before the CRA's deadline with a small team working in the e-OSCAR UI and spreadsheets, **our product** produces an evidence-cited investigation and a ready-to-approve response for payment-history disputes, plus a tamper-evident record of why each response was given, **unlike** the e-OSCAR UI, spreadsheets, or workflow tools such as PMG Case Central, which route cases but do not reason over evidence or record why.
**Proof metrics:** specialist minutes per in-scope dispute (target a 40% reduction), false-verify rate (guardrail; on synthetic data the MVP can support ≤0.5% only via the tiered eval in PRD Appendix B, and makes no real-data claim until the pilot), and the share of cases whose record a compliance officer accepts without rework.

## Pricing hypothesis (ASSUMPTION; the founders decide)
**Platform fee of $30K a year (the floor) plus $3 per dispute processed.** At 1,000-2,000 disputes a month that is an ACV of **$66-102K**, which sits inside the research range of $60-150K (WSB, assumption-grade).
**The weak spot, stated plainly:** if loaded labor is about $10 per dispute (assumed $6-15, U13) and we save 40% of handle time, the saving is about $4 per dispute. At 1,000 a month that is about $48K a year in labor against a $66K price, which is roughly break-even at 2,000 a month. **Labor savings alone do not justify this price.** The price only works if buyers also value litigation and audit defensibility, and we have not measured that (new U17).
**How to test it:** run Van Westendorp questions on both the per-dispute and the annual price in all 10 calls. Ask for FTEs and volume to compute each caller's real cost per dispute. Show three structures and record which one they prefer: (a) platform fee plus per-dispute, (b) $4 per dispute only, (c) per seat. Ask "what did your last FCRA lawsuit or audit finding cost you?"

## Not serving yet (and what would make us revisit)
| Not serving | Revisit when |
|---|---|
| Regional banks | 2 or more of 3 bank calls report a funded remediation mandate (MRA or consent order), **or** we have SOC 2 Type I, an in-VPC LLM option and 2 fintech references |
| Top-10 issuers | Year 2, through a BPO channel partner (CL) |
| Credit unions | A CUSO channel partner appears |
| Collectors, mortgage and student servicers | After the wedge is proven; their buying rules differ |
| Reg V direct disputes | No design partner can sponsor e-OSCAR access within 90 days (this triggers the fallback wedge), or ACDV is live at one pilot |
| Identity theft (605B), Metro 2/AUD correction, OCR of scanned documents | After the pilot gate (PRD §10) |
| Other ACDV categories | Payment history is under 25% of in-scope ACDVs at 3 or more nonbank calls. In that case, switch to the largest category that can be verified against the system of record |

## Expansion story
1. Payment history
2. Balance and status, then DOFD (same adapters)
3. Reg V direct-dispute triage and investigation
4. Metro 2 correction, AUD and notification of the other CRAs
5. Proactive accuracy QA, which prevents disputes
6. Regional banks (SOC 2, in-VPC deployment), then a BPO channel for the top tier
7. The parked audit and context layer for banking AI agents. The evidence-cited, hash-chained decision record is the same primitive.

This expansion is what turns a base SAM of about $41M (WSB, assumption-heavy) into a fundable story.

## Weakest points in the evidence
1. **No interviews.** Buyer roles, WTP, volume per firm and LLM tolerance are all C-grade or assumptions.
2. **WTP beyond labor is unproven.** At the hypothesized price, labor savings are only break-even.
3. **e-OSCAR access depends on a customer** sponsoring us (A). We do not know whether fintechs will do that, and the middleware prerequisites are not public (U2).
4. **Fintech regulatory urgency is down** (CFPB shift to banks, B). Litigation has to carry the urgency, and we have not quantified it (U14).
5. **Payment history's share of volume is unknown** (new U18).
6. **AI appetite is low:** only 27-32% of furnishers want more automation (C/B). Position the product on defensibility, not autonomy.

## What the first 10 calls must prove or kill (Phase 2; deferred 2026-10-19)
These are detailed in `discovery-plan.md`. The calls must **prove**, at 4 or more of the 7 nonbank calls: volume of 500 or more a month, dispute quality ranked among the top 3 ops pains, and a hosted zero-retention LLM acceptable. They must also show at least 2 firms willing to sponsor e-OSCAR Stage or share the developer guide, and at least 3 firms whose acceptable price range includes the hypothesis. **Kill or pivot** if any of these holds: 5 or more of the 7 have already bought a solution (BPO or tool); acceptable WTP is under $1 per dispute; 5 or more of the 7 ban PII to a hosted LLM; or none will share e-OSCAR access. The last case triggers the Reg V fallback.
