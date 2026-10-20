# Competitive Landscape

**Date:** 2026-10-19  **Author:** market-research  **Question:** Who already serves furnisher-side dispute handling, what do they sell, and where is the gap?
**Decision this informs:** positioning, first channel, MVP scope, and the "why now / why us" in the pitch.

## Bottom line
**We found no dominant, AI-native, furnisher-side dispute vendor.** The real competition is **"do nothing": e-OSCAR's own web UI plus spreadsheets (86% of surveyed furnishers [S13])**, plus **BPOs for large furnishers** (HCLTech, PSCU/TriVerity) and **workflow/case-management SaaS (PMG Case Central)**. The open gap is an **investigation-quality and audit layer**: evidence-cited drafts, consistent decisions, and an examiner-ready record. No vendor page we read claims that. Expect BPOs to answer with "AI-enabled" claims and PMG to add AI to Case Central within 12-18 months, so the moat has to be eval-measured quality, the audit record, and e-OSCAR integration depth, not workflow.

**Confidence:** Medium on "no dominant vendor" (we searched for one specifically). Low on the long tail: core-banking, collections-platform, and Metro 2 vendors may bundle dispute modules we could not see within our search budget.
**What would change this answer:** finding a funded, AI-native furnisher dispute vendor with bank logos, or e-OSCAR/OLDE launching its own AI-assisted response tooling.

## Landscape
| Player | Type | What they actually sell / to whom | Channel | Pricing signal | Traction / funding | Gaps vs us | Likely response | Grade |
|---|---|---|---|---|---|---|---|---|
| **e-OSCAR web UI** (OLDE, owned by the CRAs) | Do nothing (default) | Free-to-use UI, transaction fees, REST API; every furnisher | ACDV, AUD | Onboarding fee plus tiered monthly API fee; ACA members averaged ~$10.7K a year in fees [S14] | Used by 86% [S13] | No investigation support, no direct disputes, 120-day archive [primer log] | Could add analytics (it already launched "Insights by e-OSCAR" reports, Jul 2025 [S27]); unlikely to do investigations | A |
| **Spreadsheets / office tools** | Do nothing | — | Direct disputes mostly | Staff time only | 77% use office tools for direct disputes [S13] | No audit trail, no clocks | — | C/B |
| **In-house builds** (top issuers) | In-house | Internal workflow on core systems (TSYS, etc.) [S15] | Both | Internal | Unknown; we could not verify any specific bank's tooling | Slow to change; not AI-native | Build their own with internal GenAI teams | C |
| **HCLTech** (and likely other BPOs: Sutherland, etc.) | BPO | Runs credit bureau dispute and fraud operations for a "leading American FI"; India plus San Antonio; AI letter intake | Both | Not disclosed (typically FTE-based; assumption) | One case study, 2025 [S18]; Sutherland has a bank case study (not read) | Their incentive is billable FTEs; AI is a bolt-on | Claim "AI-enabled"; or **partner** (we could sell to BPOs as a channel) | B/C |
| **PSCU/TriVerity (TLSC)** | BPO for credit unions (CUSO) | Outsourced ACDV processing that "operates autonomously" | ACDV | "Simplified pricing," no figures | Launched 2022 [S19] | Service, not software; credit-union only | Channel partner or competitor for credit unions | B |
| **PMG – Case Central for Dispute Management** | Case-management SaaS | "One central place" for investigators, combining CRA data with internal account data, custom procedures, SLA tracking, audit trails. For furnishers | Not stated on the page (we infer both) | Not public | Ran the 2025 CDIA-distributed survey; Optio Solutions (collections) chose it in Jul 2026 [S20][S21] | No AI claims on the page; workflow, not investigation reasoning | **Closest direct competitor.** Will add GenAI; has distribution through CDIA | A (own page)/B |
| **Bloom Credit** | Furnishing API plus a dispute product | "Pre-built compliance workflows, case management, integrated bureau updates"; sells to fintechs, banks, credit unions | Unclear | Not public | Funded fintech infrastructure company (funding not verified in this run) | Furnishing-first; dispute depth unclear | Bundle disputes into its furnishing contracts. **A threat in the fintech ICP** | C |
| **Metro 2 software** (BureauRelay/Switch Labs and similar) | Adjacent | Metro 2 file generation, $19-49 a month for small furnishers [S22] | Neither (says e-OSCAR is separate) | Very low price points | Small furnishers | No disputes | Possible partner for the AUD/correction step | A (own page) |
| **Collections platforms** (DAKCS + Palinode, 2019) | Adjacent | e-OSCAR dispute integration for collection agencies | ACDV | — | 2019 partnership [primer log] | Collections-only | Not in our ICP | C |
| **Consulting** (FTI prototype, 2023) | Adjacent | Automated dispute prototype, "~90% cost reduction" claim [S24] | ACDV | — | Prototype only | Not a product | Could implement for large banks | C |
| **Consumer credit-repair tools / CRAs' own tooling** | Adjacent (the other side) | Generate disputes, which raises our customers' volume | — | — | — | — | They drive demand for us | B |
| **Generic AI agents** (e.g., digiqt "Credit Bureau Dispute Resolution AI Agent") | Adjacent | Agency marketing pages | Unclear | — | Unverified | Not domain-deep | Noise | C |

## Positioning map (opinion)
Axis 1: **investigation depth / defensibility** (low = routes cases; high = reasons over evidence and produces an examiner-ready record). Axis 2: **delivery model** (service/FTE vs software).
- Low depth, service: BPOs and TriVerity.
- Low depth, software: the e-OSCAR UI, spreadsheets, Metro 2 tools.
- Medium depth, software: PMG Case Central and Bloom.
- **High depth, software: empty. That is our target position.** BPOs could become customers or a channel rather than competitors.

## Disconfirming evidence
- **"A dominant vendor exists":** searched for furnisher ACDV automation vendors, AI dispute startups, and funding news. We found PMG, Bloom, BPOs, and consultancies, none dominant. The AI dispute startups we found are on **other** problems: chargebacks (Disputed.ai) and debt collection (Rezolv, $12.5M raised in 2026).
- **"Large banks already solved it":** BPOs plus in-house teams cover the top tier [S18]. We could not confirm internal AI builds at specific banks. That is a gap, and probably a real risk.
- **Not verified:** PMG's customer count and pricing, Bloom's dispute depth and funding, core-processor modules (Fiserv, Jack Henry, FIS, TSYS) for disputes, Sutherland's case study, and any vendor's e-OSCAR middleware status.

## Assumptions (each with a way to test it)
| Assumption | Why | Test | Cost |
|---|---|---|---|
| Core processors do not offer deep dispute modules | None surfaced in our searches | Ask design partners what their core offers; scan Fiserv/Jack Henry product pages | 1 hour plus discovery |
| PMG lacks AI investigation | Its page claims none | Watch a demo (founders request it as a prospect, with no misrepresentation) | 1 hour |
| BPOs would partner | Margin pressure from AI | 2 conversations with BPO practice leads | Founders' time |

## Implications for product (to product-manager)
1. Differentiate on **cited-evidence investigation plus an audit record**, not on workflow or a queue UI, where PMG and e-OSCAR are good enough.
2. The MVP should **coexist with the e-OSCAR UI** (ingest and draft, with a human submitting) so the buyer doesn't have to replace anything. The current alternative is free.
3. Watch Bloom in the fintech ICP. If design partners already furnish through Bloom, ask about integration.
4. Consider a **BPO channel** for the top tier in year 2.

## Sources (accessed 2026-10-19)
- S13 PMG/CDIA survey (see wedge report). https://pmg.net/wp-content/uploads/PMG-FF-Dispute-Mgmt-02-10-25.pdf
- S14 ACA International study, 2019. https://www.accountsrecovery.net/2019/01/30/study-details-extent-cost-of-managing-generic-disputes/
- S15 TD Bank posting. https://themuse.com/jobs/tdbank/credit-bureau-dispute-specialist-retail-card-services
- S18 HCLTech case study, 2025. https://www.hcltech.com/en-us/case-study/enhancing-credit-bureau-disputes-and-fraud-management-for-a-leading-american-financial-institute
- S19 PSCU/TriVerity, 2022-09-14. https://www.cuinsight.com/press-release/pscus-triverity-announces-new-indirect-credit-bureau-dispute-processing-solution/
- S20 PMG Case Central page. https://pmg.net/case-central-dispute-investigation-saas
- S21 "Optio Solutions Selects Case Central," Business Wire via StreetInsider/Las Vegas Sun, 2026-07-15 (headline seen; the article body did not load). https://lasvegassun.com/news/2026/jul/15/optio-solutions-selects-case-central-to-power-its-/
- S22 BureauRelay (Switch Labs), cost to furnish. https://bureaurelay.com/metro2/cost-to-furnish-credit-data
- S23 Bloom Credit, Credit Dispute Management. https://bloomcredit.io/?p=1712
- S24 FTI via AFSA, 2023. https://afsaonline.org/2023/01/16/how-automated-credit-dispute-handling-can-reduce-costs-by-90/
- S27 e-OSCAR, Insights release notes, 2025-07-15. https://www.e-oscar.org/_files/ugd/6bf0bc_45a5a63b4e56460dadace1fce14d52f6.pdf
- Rezolv funding (2026-08-18): https://www.accountsrecovery.net/2026/08/18/rezolv-raises-12-5m-to-automate-debt-collection-with-ai/ (headline only); DAKCS/Palinode: see primer Verification Log.
