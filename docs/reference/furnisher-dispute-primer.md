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
