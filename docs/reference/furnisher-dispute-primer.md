# Furnisher Dispute Primer

Shared starting knowledge for all agents. **Everything here is a starting hypothesis from general knowledge, not a verified source.** Before any item goes into a PRD, spec, pitch, or customer-facing claim, verify it against a primary source (statute, regulation, CFPB publication, CDIA/e-OSCAR documentation, bureau furnisher guidance) and record the source and date in the Verification Log at the bottom. Flag legal interpretation for counsel review. Regulation and enforcement posture change; always search for the current state rather than relying on this file.

## 1. The ecosystem
- **Furnishers**: banks, card issuers, auto and mortgage lenders, fintechs, credit unions, collectors, utilities. They report account data to consumer reporting agencies (CRAs: Equifax, Experian, TransUnion, plus specialty CRAs).
- **Reporting format**: Metro 2, maintained by the Consumer Data Industry Association (CDIA). Data is typically submitted monthly.
- **Indirect dispute path**: consumer disputes with a CRA -> CRA sends the dispute to the furnisher as an ACDV (Automated Consumer Dispute Verification) through e-OSCAR -> furnisher investigates and responds (verify, update, delete) -> CRA updates the file and notifies the consumer. Furnishers may also send AUDs (Automated Universal Dataform) to push updates outside a dispute.
- **Direct dispute path**: consumer disputes directly with the furnisher, governed by Regulation V (12 CFR 1022.43). The furnisher investigates, then reports the result to the consumer, and corrects bureau reporting if needed.
- **Identity theft and fraud disputes** follow different rules and tooling (e.g., blocking provisions under FCRA 605B) and are likely out of MVP scope.

## 2. Core legal anchors (verify all)
- FCRA Section 623 (15 U.S.C. 1681s-2): furnisher duty to report accurately; duties on receipt of a CRA dispute notice (conduct a reasonable investigation, review all relevant information the CRA provides, report results to the CRA, correct or delete information found inaccurate, incomplete, or unverifiable, and notify other CRAs where applicable).
- FCRA Section 611 (15 U.S.C. 1681i): CRA reinvestigation timelines (commonly 30 days, extendable to 45 in specific circumstances). Confirm how those translate into furnisher response windows set by the CRAs on e-OSCAR.
- Regulation V, 12 CFR 1022.42 (furnisher policies and procedures on accuracy and integrity) and 1022.43 (direct disputes: scope, exceptions such as frivolous or irrelevant disputes, timelines, notices to the consumer).
- Private right of action and exposure: FCRA civil liability provisions (willful and negligent noncompliance); active litigation area. Counsel must frame any risk statements.
- Regulator interest: CFPB supervision and enforcement themes on furnisher investigation quality (e.g., "reasonable investigation" vs. rubber-stamping responses), plus state AGs. **Current enforcement posture must be researched fresh.**

## 3. Operational reality (hypotheses to test in discovery)
- Volume is large and spiky; dispute teams are often outsourced or offshore, staffed by agents working across several legacy systems.
- Investigation quality varies: agents match the ACDV against internal records and respond quickly, with limited review of attached documents.
- Repeat and mass disputes (including from credit repair organizations) create volume and risk of both over- and under-reacting.
- Metro 2 corrections and compliance condition codes (e.g., dispute-related flags) are easy to get wrong; errors propagate to the bureaus.
- Quality assurance and audit evidence are sampled and manual; reconstructing "why did we respond this way" later is hard.
- Training, turnover, and policy updates drive inconsistent decisions.

## 4. Common dispute categories (verify against e-OSCAR dispute code list)
Not my account or identity; balance or amount; payment history / late payments; account status (open, closed, paid, charged off); duplicate or mixed file; bankruptcy; deceased; personal identifying information; account ownership or authorized user; dates (e.g., date of first delinquency).

## 5. Technical surface (verify)
- Integration points: e-OSCAR (ACDV/AUD handling; check access model, vendor rules, and any automation restrictions), the furnisher's core servicing and card platforms, document stores, CRM/case management, Metro 2 file generation.
- Key engineering concerns: deadline tracking, strict field mappings, immutable audit trail, PII handling, human review gates, explainability for regulators and examiners.

## 6. Open questions that decide the company
1. Which segment feels the most acute pain: large issuers, mid-size banks, credit unions, auto lenders, fintech lenders, servicers?
2. Build vs. buy: how many already built in-house or buy from BPOs, e-OSCAR-adjacent vendors, or core-system add-ons?
3. Is the buyer the head of dispute operations, compliance, a CRO org, or a platform/product owner? Who holds budget?
4. What are the e-OSCAR access and automation constraints for a third-party vendor?
5. What would a regulator accept as an AI-assisted investigation with a defensible audit trail?
6. Pricing model: per dispute, per seat, platform fee, outcome-based?

## Verification Log
| Date | Item verified | Source URL | Verified by | Notes |
|---|---|---|---|---|
| 2026-10-19 | e-OSCAR offers a REST API ("Services by e-OSCAR") for data furnishers; ACDV call sequence strictly ordered; middleware vendors common; 7-stage onboarding; fees | https://www.e-oscar.org/services-by-e-oscar ; https://www.e-oscar.org/copy-of-api-services-developers | developer | A-grade. Middleware prerequisites not public |
| 2026-10-19 | e-OSCAR ToU (eff. 2023-06-23): automation tools incl. AI permitted with Operator ID notice; OLDE may suspend; no third-party use except authorized agent; 24h access disable; >=120-day archive | https://www.e-oscar.org/_files/ugd/0823b4_51f440053d1b42fcaa99d651ad588bfb.pdf | developer | A-grade; may be superseded; counsel to review |
| 2026-10-19 | Template addendum lets furnisher authorize a third-party service provider to access e-OSCAR/API on its behalf; furnisher remains liable | https://www.e-oscar.org/_files/ugd/0823b4_f850b663c72b4f079e87d0366200d679.pdf | developer | A-grade; unsigned template; counsel to review |
| 2026-10-19 | FCRA 623(b)(1)(A)-(E) ACDV duties: investigate, review all relevant info from CRA, report to CRA, notify other nationwide CRAs if inaccurate/incomplete, modify/delete/block if inaccurate, incomplete or unverifiable | https://www.law.cornell.edu/uscode/text/15/1681s-2 | market-research | A-grade (LII copy of USC); counsel to confirm |
| 2026-10-19 | FCRA 623(b)(2): furnisher must complete before CRA's 1681i(a)(1) period expires | https://www.law.cornell.edu/uscode/text/15/1681s-2 | market-research | A-grade |
| 2026-10-19 | FCRA 623(c)-(d): no private right of action for 623(a) duties (incl. Reg V direct disputes); (b) ACDV duties remain privately actionable via 1681n/1681o | https://www.law.cornell.edu/uscode/text/15/1681s-2 | market-research | A-grade text; interpretation flagged for counsel |
| 2026-10-19 | FCRA 611(a)(1): 30 days from CRA receipt; +up to 15 days only if consumer supplies info during the 30 days; no extension if found inaccurate/unverifiable; 611(a)(2): CRA notifies furnisher within 5 business days | https://www.law.cornell.edu/uscode/text/15/1681i | market-research | A-grade. Primer's "30 extendable to 45" confirmed with condition. e-OSCAR response due dates not verified (U6) |
| 2026-10-19 | 12 CFR 1022.43(a)-(f): direct dispute scope, exceptions (ID info, inquiries, employers, alerts, other furnishers' info, credit repair organization disputes), address and notice-content conditions, duties, same 1681i(a)(1) timeline, frivolous notice within 5 business days | https://www.ecfr.gov/current/title-12/chapter-X/part-1022/subpart-E/section-1022.43 | market-research | A-grade; eCFR current to 2026-10-15; section unchanged since 2017 |
| 2026-10-19 | 12 CFR 1022.42: written reasonable accuracy/integrity policies, consider Appendix E, periodic review | https://www.ecfr.gov/current/title-12/chapter-X/part-1022/subpart-E/section-1022.42 | market-research | A-grade; unchanged since 2017 |
| 2026-10-19 | CFPB withdrew Circular 2022-07 (reasonable investigation of disputes), Bulletins 2013-09 and 2014-01, name-only matching guidance on 2025-05-12; 2016 furnisher P&P bulletin remains | https://morganlewis.com/topics/cfpb-guidance-tracker-rescinded-and-remaining | market-research | B-grade (law-firm tracker); confirm against Federal Register withdrawal notice |
| 2026-10-19 | CFPB Apr 2025 priorities memo: 50% fewer exams, shift to large banks/depositories, FCRA/Reg V furnishing still a priority; ~70 exams expected 2026 | https://www.hklaw.com/en/insights/publications/2025/04/cfpb-announces-new-supervision-and-enforcement-priorities ; https://www.pwc.com/us/en/industries/financial-services/library/our-take/cfpb-agenda-credit-risk-supervision-jul-24-2026.html | market-research | B-grade; fluid, re-check quarterly |
| 2026-10-19 | Roberts v. Carter-Young (4th Cir. Mar 2025): "objectively and readily verifiable" standard replaces legal/factual distinction for 1681s-2(b) | https://www.consumerfinancialserviceslawmonitor.com/2025/03/fourth-circuit-issues-ruling-on-furnishers-duty-to-investigate-legal-disputes-under-fcra/ | market-research | B-grade; read opinion before citing in pitch; counsel |
| 2026-10-19 | CFPB Spring 2024 Supervisory Highlights furnisher findings (DOFD errors, failure to notify CRAs of direct disputes, unreasonable direct-dispute investigations, auto-deletion, ID theft) | https://www.cooley.com/news/insight/2024/2024-04-12-cfpbs-spring-supervisory-highlights-report-reinforces-focus-on-consumer-reporting-furnisher-activities | market-research | B-grade; primary (CFPB report / FR 2024-09712) not fetched |
| 2026-10-19 | 15 USC 1681p: FCRA actions must be brought by the earlier of 2 years after discovery of the violation or 5 years after it occurs | https://www.law.cornell.edu/uscode/text/15/1681p | developer | A-grade (LII copy of USC). Supports the PRD R-23 7-year placeholder exceeding the limit; resolves U19 text; counsel sets retention |
| 2026-10-19 | 5 USC 6103(a): 11 legal public holidays (incl. Juneteenth); 6103(b): a Saturday holiday is observed on the preceding Friday for Mon-Fri workers | https://www.law.cornell.edu/uscode/text/5/6103 | developer | A-grade for the federal holiday list only. **Not verified** that CRAs, e-OSCAR or furnishers use this calendar for due dates (U21); Sunday observance rule not stated in 6103(b) |
| 2026-10-20 | SSA SSN randomization (eff. 2011-06-25) excludes area numbers 000, 666 and 900-999, and never assigns group 00 or serial 0000 | https://www.ssa.gov/employer/randomizationfaqs.html | developer | A-grade. Used only to make synthetic SSN-shaped values non-assignable (ADR-009); not a regulatory requirement |
| 2026-10-20 | Anthropic API: ZDR enabled per organisation via sales; feature eligibility (Messages API yes; Batch, Files API, code execution no); named Covered Models need 30-day retention; T&S-flagged data may be retained up to 2 years even under ZDR | https://platform.claude.com/docs/en/manage-claude/api-and-data-retention | developer | A-grade (provider's own docs, undated page, read 2026-10-20). Commercial terms not read; our org's ZDR status unverified (ADR-006, U25) |
