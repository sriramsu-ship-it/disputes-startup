# Regulatory and Enforcement Landscape

**Date:** 2026-10-19  **Author:** market-research  **Question:** What do the law and current enforcement require of furnishers on disputes, and which channel (ACDV or direct) is the better first wedge?
**Decision this informs:** the first channel and dispute category, the audit-record design (U3, U10), and the urgency story in the pitch. **This is not legal advice; every interpretation below is flagged for counsel.**

## Bottom line
**Start with ACDV (indirect) disputes on account-status, balance, and payment-history categories.** ACDVs are where furnishers face **private FCRA liability** (§1681s-2(b)), where courts keep raising the "reasonable investigation" bar, and where volume and structure are highest. Direct disputes (Reg V §1022.43) are **not privately enforceable** (§1681s-2(c)-(d)), so they matter mainly when a regulator examines. The CFPB has **retrenched** (about 70 exams expected in 2026 versus about 600 a year in 2020-24, and its dispute-investigation guidance was withdrawn in May 2025). However, the **statute and Reg V are unchanged**, FCRA/Reg V furnishing is still a named CFPB priority, and litigation risk on the ACDV side is unaffected. So **lead the urgency story with litigation and accuracy, not with the CFPB.**

**Confidence:** High on the statutory text (A). Medium on the enforcement posture, which is fluid (the confirmation of a new director is pending, and larger-participant rules are being proposed).
**What would change this answer:** a statutory amendment or a CFPB rule narrowing §1022.43; a Supreme Court ruling on the "objectively and readily verifiable" standard; a revival of CFPB furnishing enforcement under a new director.

## Key findings
1. **ACDV duties (§1681s-2(b)(1)):** investigate; review **all relevant information the CRA provides**; report results to the CRA; if the information is inaccurate or incomplete, notify all nationwide CRAs it furnished to; and modify, delete, or permanently block the item if it is inaccurate, incomplete, **or cannot be verified**. Evidence: A. [S1]
2. **ACDV timing:** the furnisher must finish before the CRA's §1681i(a)(1) period expires (§1681s-2(b)(2)). That period is **30 days** from the CRA receiving the dispute, **extendable by up to 15 days** only if the consumer sends more information during the 30 days. The CRA must notify the furnisher within **5 business days**. The furnisher's working window is therefore shorter than 30 days, and e-OSCAR response due dates set the operational deadline (not verified; U6). Evidence: A. [S1][S2]
3. **Direct disputes (§1022.43):** these cover liability, account terms, and payment performance. They exclude identifying info, inquiries, employers, fraud and active-duty alerts, and info from other furnishers, **and disputes the furnisher reasonably believes come from a credit repair organization**. Investigating is required only if the dispute is sent to the specified address and contains the required notice contents. Duties: reasonably investigate, review all relevant consumer-provided info, report results to the consumer within the same §1681i(a)(1) period, and promptly correct with every CRA. A frivolous/irrelevant determination requires notice **within 5 business days** with reasons. eCFR is current as of 2026-10-15, and the section has been unchanged since 2017. Evidence: A. [S3]
4. **§1022.42** requires written, reasonable policies and procedures for accuracy and integrity, sized to the furnisher, considering Appendix E, and periodically reviewed. It is unchanged since 2017. Evidence: A. [S4]
5. **No private right of action for §623(a) / Reg V direct-dispute duties**: §1681s-2(c)-(d) channel enforcement to agencies and officials. ACDV duties under (b) **are** privately actionable through §§1681n/1681o. Evidence: A. [S1]. **Counsel to confirm.**
6. **Courts are expanding what must be investigated.** In *Roberts v. Carter-Young* (4th Cir., Mar 2025), the court rejected the legal-versus-factual distinction: a dispute is actionable if the information is "objectively and readily verifiable," joining *Sessa* (2d Cir. 2023) and *Holden* (11th Cir. 2024). A collector that only confirmed with its client was at risk. Evidence: B. [S5] Older line: *Johnson v. MBNA* (4th Cir.), which held that a data match alone is not a reasonable investigation. Evidence: B (via NCLC [S11]).
7. **CFPB supervisory themes (Spring 2024):** furnishers failed to promptly correct known errors (DOFD left wrong for months); auto lenders misreported DOFD; furnishers failed to notify CRAs of direct disputes; **direct-dispute investigations were unreasonable** (demanding more info than Reg V requires); collectors **auto-deleted** instead of investigating; and furnishers kept reporting after identity-theft reports. Evidence: B (law-firm summary of the CFPB report). [S9]
8. **Enforcement:** TD Bank (Sep 2024) paid a $20M penalty plus $7.76M in redress for inaccurate furnishing and for failing to reasonably investigate within 30 days. Honda Finance (Jan 2025) paid about $10.3M in redress plus a $2.5M penalty. After Jan 2025, the CFPB dismissed six credit-reporting matters; the *Experian* case continues. Evidence: B. [S10][S8]
9. **Posture change:** the CFPB withdrew **Circular 2022-07 (reasonable investigation of disputes), Bulletins 2013-09 and 2014-01 (furnisher investigations)**, and the name-only-matching guidance on 2025-05-12. The 2016 furnisher policies-and-procedures bulletin and the "facially false data" item remain. The April 2025 memo cuts exams 50%, shifts supervision back to large banks and depositories, defers to states, and keeps "FCRA/Reg V data furnishing" as a priority. Vought expects about 70 exams in 2026. A Consumer Reporting larger-participant proposal is expected in Aug-Sep 2026. Goodwin expects no new CFPB credit-reporting enforcement "beyond data furnishing violations." Evidence: B. [S6][S7][S8][S28]

## ACDV vs direct: what it means for the wedge (opinion)
| Factor | ACDV (indirect) | Direct (Reg V) |
|---|---|---|
| Private litigation exposure | **Yes** (§1681s-2(b)) | No (§1681s-2(c)) |
| Regulator exposure | Yes | Yes (an SH 2024 finding) |
| Input structure | Structured codes plus images through e-OSCAR | Letters, email, and scans (messy) |
| Integration dependency | e-OSCAR via the furnisher (U2) | None |
| Tooling today | e-OSCAR UI (86%) | Spreadsheets (77%) [S13] |
| CRO-sourced disputes | Must be investigated if forwarded by the CRA (counsel to confirm) | **Can be excluded** under §1022.43(b)(2) |
| Timeline | §1681i 30 (+15) days minus the CRA's forwarding time | Same §1681i(a)(1) period; 5 business days for a frivolous notice |

**Recommendation:** ACDV first, because liability, volume, and structure all point there and the input is easier to evaluate. Design the canonical model so direct disputes come second. A **"direct-dispute triage" feature** (CRO detection, sufficiency check, 5-day frivolous notice) is a cheap, high-value follow-on that needs no e-OSCAR access, and it is the **fallback first wedge if a design partner cannot sponsor e-OSCAR access.** First category: **account status / balance / payment history**, where the ACDV can be verified against the furnisher's own system of record. That fits the "objectively and readily verifiable" standard and avoids identity-theft (§605B) complexity.

## Disconfirming evidence
- **Regulatory retrenchment reduces urgency: confirmed for the CFPB.** Exams are down about 88% from the 2020-24 average, and the dispute guidance was withdrawn. The offsets are private litigation, state activity (16 states with medical-debt laws [S8]), bank prudential examiners (not researched), and the fact that the duties are statutory.
- **Rules changing under us:** §§1022.42 and 1022.43 are unchanged since 2017 per eCFR (current to Oct 2026). No pending amendment was found.

## Assumptions (each with a way to test it)
| Assumption | Test | Cost |
|---|---|---|
| Litigation fear motivates buyers more than the CFPB does | Ask "what made you last change dispute process?" in discovery | Free |
| CRAs set furnisher due dates well inside 30 days | e-OSCAR developer guide via a design partner (U6) | Partner |
| OCC/FDIC/NCUA examiners still review furnisher disputes at banks | Search OCC/FDIC exam manuals; counsel | 2 hours |

## For counsel (flagged)
1. Whether the CRO exclusion in §1022.43(b)(2) has any ACDV analogue.
2. Whether withdrawn CFPB guidance still informs the "reasonable investigation" standard in practice (courts and states).
3. Liability allocation when an AI drafts and a human submits (ties to the e-OSCAR ToU automation notice).
4. Retention period for investigation records (U10).

## Sources (accessed 2026-10-19)
- S1 15 U.S.C. §1681s-2 (Cornell LII). https://www.law.cornell.edu/uscode/text/15/1681s-2
- S2 15 U.S.C. §1681i (Cornell LII). https://www.law.cornell.edu/uscode/text/15/1681i
- S3 12 CFR 1022.43 (eCFR, current to 2026-10-15). https://www.ecfr.gov/current/title-12/chapter-X/part-1022/subpart-E/section-1022.43
- S4 12 CFR 1022.42 (eCFR). https://www.ecfr.gov/current/title-12/chapter-X/part-1022/subpart-E/section-1022.42
- S5 Consumer Financial Services Law Monitor, *Roberts v. Carter-Young*, Mar 2025. https://www.consumerfinancialserviceslawmonitor.com/2025/03/fourth-circuit-issues-ruling-on-furnishers-duty-to-investigate-legal-disputes-under-fcra/
- S6 Holland & Knight, Apr 2025. https://www.hklaw.com/en/insights/publications/2025/04/cfpb-announces-new-supervision-and-enforcement-priorities
- S7 PwC, 2026-07-24. https://www.pwc.com/us/en/industries/financial-services/library/our-take/cfpb-agenda-credit-risk-supervision-jul-24-2026.html
- S8 Goodwin, Mar 2026. https://www.goodwinlaw.com/en/insights/publications/2026/03/insights-finance-cfs-yir-credit-reporting
- S9 Cooley, 2024-04-12. https://www.cooley.com/news/insight/2024/2024-04-12-cfpbs-spring-supervisory-highlights-report-reinforces-focus-on-consumer-reporting-furnisher-activities
- S10 Goodwin, TD Bank order, Sep 2024. https://www.goodwinlaw.com/en/insights/blogs/2024/09/cfpb-enters-consent-order-and-stipulation-with-national-bank-to-resolve-allegations-of-inaccurate-fu
- S11 NCLC, "Automated Injustice," 2009. https://www.nclc.org/wp-content/uploads/2022/10/report-automated_injustice.pdf
- S13 PMG/CDIA survey, 2025. https://pmg.net/wp-content/uploads/PMG-FF-Dispute-Mgmt-02-10-25.pdf
- S28 Morgan Lewis, CFPB Guidance Tracker. https://morganlewis.com/topics/cfpb-guidance-tracker-rescinded-and-remaining
