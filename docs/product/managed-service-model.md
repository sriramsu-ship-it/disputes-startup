# Managed-Service Model Memo: "We run your disputes for you"

**Date:** 2026-11-07  **Owner:** product-manager  **Status:** Pivot **DECIDED by Sriram (2026-11-07)**. Everything below that is not that decision is a **recommendation or a hypothesis**. Pricing, legal and hiring items are Sriram's to decide (§12).
**Read with:** PRD v1.2 (`prd-mvp-v0.md`), `icp-and-wedge-memo.md` (ICP), `discovery-plan.md`, `docs/UNKNOWNS.md` (U37-U48 are new), `docs/engineering/platform-architecture.md`, ADR-008 revision, ADR-011.
**Inputs:** `docs/research/wedge-segments-and-buyers.md` (WSB), `competitive-landscape.md` (CL), `regulatory-and-enforcement-landscape.md` (REG), plus web checks made today (sources in §14).
Labels: **[F]** fact with grade (A primary, B reputable secondary, C weak), **[A]** assumption with a test, **[O]** opinion. "Counsel" = unverified legal reading; FCRA counsel must review before any customer-facing use. **Not legal advice.**

**Decision this memo answers:** what the managed-service pivot changes in the product, buyer, offer, operating model, obligations and plan, and what would make us reverse it. **Evidence available:** desk research only (B/C on market, A on statute and guidance); **zero customer, analyst or BPO conversations.**

## Bottom line
1. **The core loop and every safety floor stay exactly as they are.** What changes is who sits in the review seat (our analyst, not the client's specialist), who pays (for an outcome per dispute, not a tool), and what we must prove (that a trained generalist on our platform is as accurate as an experienced specialist, and that we are a vendor a furnisher's vendor-risk team will approve).
2. **The furnisher keeps its FCRA duties; we take on service-provider exposure.** The ACDV duties in FCRA 623(b) attach to the furnisher [F, A, REG S1], and the e-OSCAR addendum template keeps the furnisher liable when a service provider acts for it [F, A, primer log]. But as a provider of a material service to a covered person we fall within the CFPB's "service provider" definition and its supervision and enforcement reach [F, A, CFPB Bulletin 2016-02]; bank clients' regulators can examine services we perform for a bank as if the bank performed them [F, A, 12 USC 1867(c)]; and clients must contractually bind us to GLBA safeguards [F, A, 16 CFR 314.4(f)]. **Vendor risk becomes the main sales gate, not a blocker at the edge.**
3. **The unit economics are unproven and could be negative.** If our analysts are paid like today's in-house specialists ($23-31/hr [F, A, WSB S15]) and the platform only delivers the PRD's 40% time saving, our labour cost per dispute lands inside the client's own assumed $6-15 [A, U13], before QA, supervision, compliance overhead and onboarding. The model only works if the platform cuts analyst minutes much further, or buyers pay a premium for defensibility (U17, now sharper), or both. The measurement that settles this is **analyst minutes per dispute at the accuracy gate** (§4, §5).
4. **ICP: keep nonbank lenders as the first segment, but move the volume band down and gate on per-client onboarding cost.** The service model makes smaller furnishers worth serving (we earn on the labour we replace, not on a tool fee), which partly reconciles with Sriram's "smaller furnishers that find disputes a burden" hypothesis. Credit unions and community banks come later and through a channel, because both bring heavier vendor-oversight duties or an incumbent outsourcer (TriVerity [F, B, CL]). Debt buyers are out for now (§10).
5. **The pivot's biggest new risk is that we are deciding on two untested hypotheses at once** (smaller furnishers will hand over e-OSCAR work to a startup; generalists reach expert accuracy fast). Recommendation [O]: pull the service-buyer half of Phase 2 discovery forward to run **in parallel** with Stages 1-3, because the build no longer needs Sriram's labelling hours for those stages and the pivot's kill criteria (§11) can only be tested by talking to buyers.

**Confidence:** low-medium overall. High that the safety design carries over unchanged; medium on the service-provider obligations (A-grade sources, but how they apply to us is a counsel question); low on buyer, price and analyst productivity (no evidence yet).

## 1. What changes and what does not
| Area | Before (PRD v1.1, software) | After (v1.2, managed service) | Evidence / status |
|---|---|---|---|
| What we sell | Software to the furnisher's dispute team | Dispute operations as a service, priced per dispute; software later | DECIDED, Sriram 2026-11-07 |
| Who reviews and approves | Client's specialist and supervisor | **Our** analysts (SPECIALIST) and supervisors (SUPERVISOR) | ADR-011, domain `Role` |
| Core loop, R-01 to R-36, Appendix B floors B1-B7 | As written | **Unchanged.** 100% human approval, no auto-submit, system never proposes DELETE, second approval for DELETE and HIGH suspicious content | DECIDED 2026-10-19; not reopened |
| Tenancy | Single tenant, non-goal | Multi-tenant, one tenant per client; app-scoped now; RLS, per-tenant keys and an independent isolation test before real data | ADR-008 revision (A, internal) |
| Surfaces | One reviewer UI | `/ops` analyst workbench; `/client` read-only portal | ADR-011 |
| Primary metric | Specialist minutes saved (client's ROI) | **Analyst accuracy at the gate, and analyst minutes per dispute** (our margin and the client's quality proof) | §4 |
| Liability | Tool vendor; client decides | Client still holds the FCRA duty; we hold contract, service-provider and negligence exposure | §7; counsel |
| e-OSCAR | Client submits; we coexist with its UI | We would operate in e-OSCAR **as the client's authorized agent** | Addendum template (A); U2, U42 |
| Evidence access | Client's own staff read their own systems | Our analysts need access to each client's system of record | U9 becomes U44 |
| Hiring | None until the §12 evidence bar | A service needs analysts before a live pilot. Still Sriram's decision; the bar is restated in PRD §12 | Sriram decides |
| Competitors | PMG, Bloom (software); BPOs as a possible channel | **BPOs and CUSO outsourcers become direct competitors** (HCLTech, TriVerity) [F, B/C, CL]; PMG and Bloom become possible platform alternatives a client could buy instead | CL |
| Phase 1 | Synthetic, no interviews | Still synthetic. Stages 1-3 APPROVED 2026-11-07 and built in parallel; Stage 4 needs approval | DECISIONS 2026-11-07 |

## 2. Buyer and user map (service model; hypothesis, all untested)
| Role | Who (smaller furnisher) | What they need to believe | What could stop the deal |
|---|---|---|---|
| **Economic buyer** | COO, head of servicing or operations; at a small lender possibly the CEO or CFO [A] | Total cost per dispute is at or below what they spend now (in-house staff, BPO or e-OSCAR overtime), with fewer late responses | No budget line for outsourcing; disputes seen as a minor cost |
| **Champion** | Whoever owns credit bureau disputes today: a disputes manager, or a servicing or compliance lead doing it part time [A] | We take a recurring, deadline-driven burden off them and hand back a record they can defend | Fear of losing control of a regulated process |
| **Compliance / FCRA officer** (blocker, can become champion) | CCO or compliance manager | The furnisher's 623(b) duty is met; every decision has a reason, evidence and an approver; ID theft and policy calls come back to them | "We can't outsource judgement on our accounts"; wants to approve DELETEs |
| **Third-party / vendor risk management** (blocker; **now the main gate**) | TPRM or procurement; at a bank, the vendor-management program the regulators expect [F, A, Interagency TPRM guidance 2023] | Due diligence package: security controls, SOC 2 report or plan, insurance, BCP, subcontractor (LLM provider) disclosure, data location, background checks, right to audit, regulator access | No SOC 2; a single-founder startup; LLM subprocessor; offshore staff (if any) |
| **InfoSec** (blocker) | CISO or IT lead | MFA, encryption at rest and in transit, tenant isolation, access logging, breach notification terms; GLBA safeguards passed down by contract [F, A, 16 CFR 314.4(f)] | Our analysts reaching into their core systems |
| **e-OSCAR administrator** (blocker) | Client's e-OSCAR admin | We act as their authorized agent under the addendum; automation tools notified to OLDE per the ToU [F, A, primer log] | Unwilling to sign the addendum; OLDE requirements for agents (U42) |
| **Sponsor bank** (fintech only; possible blocker) | Bank partner's TPRM | A fintech's outsourcing of a consumer-facing compliance process may need the bank's sign-off [A, U16] | Bank-grade diligence on a startup |
| **Users** | **Our analysts and supervisors** (`/ops`); client viewers (`/client`) | Analysts: a workbench that makes the right answer the easy one. Client viewers: status, SLA, outcomes and exports without asking us | n/a |

## 3. The service offer (proposed; terms are Sriram's decisions with counsel)
**Scope we take over (MVP of the service):**
1. Receive each in-scope ACDV for the client (initially payment history, per the DECIDED wedge), within an agreed intake path (§8, U42).
2. Investigate against the client's records, draft a cited response, and have our analyst approve it under the PRD controls (R-10 to R-21).
3. Submit the response on the client's behalf **only once** the e-OSCAR agent arrangement, counsel review and the pilot gates are in place. Until then we prepare the package and the client submits (shadow mode, §7).
4. Keep the hash-chained audit record and provide per-case exports (R-21, R-22) and a client portal (R-40, R-41).

**What the client still owns (legally and operationally):**
- **The FCRA furnisher duties themselves** (623(b) investigation, reporting, correction) [F, A, REG S1]; the e-OSCAR addendum keeps the furnisher liable for its agent [F, A]; supervised entities remain responsible when they use service providers [F, A, CFPB Bulletin 2016-02; Interagency TPRM 2023]. Counsel: how far our contract can shift cost of errors back to us.
- Its **written accuracy and integrity policies** under 12 CFR 1022.42 [F, A, REG S4]. We operate to them; we do not write them (we can supply a draft procedure for their review, a later offer).
- **Account records and corrections in its own systems**, Metro 2 reporting and AUDs (out of scope, as in PRD §10).
- **Decisions we hand back** (below), and its own consumer communications.

**Handoffs and escalations to the client (proposed list):**
| Trigger | What we do | Why |
|---|---|---|
| ID_FRAUD_SUSPECTED (R-07) | No draft; hand to the client at once with the deadline and extracted text | Identity theft follows separate rules (605B; 623(a)(6) furnisher duties), out of scope; high consumer harm. Counsel |
| EVIDENCE_MISSING where the client's records are incomplete | Request the record through the agreed channel; if not received by a cut-off, hand back | We cannot verify what we cannot see; 623(b)(1)(E) requires modify/delete/block if unverifiable [F, A] |
| Any proposed DELETE | Second approval by our supervisor (R-19), **plus client pre-approval during the pilot** (recommended [O], Sriram decides) | Deleting a tradeline is the client's business and credit-risk call |
| Policy questions (hardship, deferral programmes, settlements) | Hand back with our analysis | Client-specific policy; EVIDENCE_CONFLICT cases |
| Litigation, attorney letters, regulator complaints | Hand back immediately | Client's counsel owns these |
| BREACHED or AT_RISK with a client dependency | Escalate to the named client contact | Deadline is the client's legal exposure |

**SLAs (placeholders; numbers are commercial decisions for Sriram):** respond to every in-scope ACDV no later than **N business days before the CRA due date** (R-43; today's internal target default is 3 business days, R-05); handback within **H business hours** of an escalation trigger; QA defect rate at or below the pilot gate (§4); portal data no more than **M minutes** stale. Remedies (service credits) are a contract decision.

**Audit package (per case and per month):** the R-22 per-case export; a monthly client report (volumes, outcomes, SLA attainment, escalations, QA results); a description of our controls (training, QA sampling, access control, change management for prompts, models and rules with eval results). The monthly report and controls description are new deliverables (R-40, R-45).

## 4. Analyst role, training and QA model
**Role (proposed):** "Dispute analyst". No licence is required for this work as far as we know; Sriram's positioning statement says so and no source found says otherwise [A; counsel to confirm for any state or segment, e.g. debt buyers]. Works in `/ops` on assigned tenants only (R-38). Approves, edits or escalates; never auto-submits.

**How a generalist becomes accurate (design, untested):**
1. **The platform carries the expertise.** Deterministic rules decide the outcome (R-10); the analyst checks evidence, claims and quotes, and resolves escalations by reason code. The analyst cannot produce VERIFY unless the rules allow it.
2. **Structured training (proposed):** FCRA dispute basics and what the client owns; the client's 1022.42 policies; the escalation list; a graded practice set drawn from the synthetic generator (T1/T3-style cases, never the frozen eval sets, R-34) with feedback against gold labels.
3. **Certification before live work:** a blind test on synthetic cases with a pass bar (below). Pass per client: a short client-policy module.
4. **QA:** 100% second review of each new analyst's work until certified; then a stratified sample (proposed 10%, plus 100% of DELETE, HIGH suspicious content, MODIFY in the first weeks) re-worked blind by a supervisor. Defects are coded (outcome wrong, claim missed, wrong reason code, handback missed, narrative defect).
5. **Feedback loop:** each defect becomes a training case and, where it reveals a gap, a generator or red-team regression case (Appendix B "On a failure").

**The metric that proves the thesis (proposed; R-45):**
- **Critical error rate per analyst** = QA-reviewed cases where the analyst's final outcome differs from the supervisor's blind outcome, or an escalation or handback was missed, divided by QA-reviewed cases. **Gate [O]:** 0 critical errors in the analyst's last 300 QA-reviewed cases (supports ≤1.0% at a one-sided 95% upper bound, the same arithmetic as the pilot line in Appendix B). 0 in 200 supports only ≤1.5%; 0 in 100 only ≤3%.
- **Time to proficiency** = working hours from start until the analyst meets the gate.
- **Productivity at the gate** = median active minutes per completed in-scope dispute (R-24), and disputes per active hour, for analysts who meet the gate.
- **Expert equivalence (Phase 2):** the same blind synthetic set worked by trained analysts and by at least 2 experienced dispute practitioners; report agreement with gold and between groups. This is the test of "$15-an-hour expert"; it needs outside people and is Phase 2.
- Guardrails: override rate and review-time alerts (PRD §4) per analyst, so certified analysts do not rubber-stamp.

## 5. Unit economics hypothesis per dispute (ASSUMPTION-GRADE; nothing here is validated)
**Formula (per completed in-scope dispute):**
`cost = (analyst minutes × analyst loaded $/min) + (QA share × supervisor minutes per QA case × supervisor loaded $/min) + (escalation share × supervisor minutes per escalation × $/min) + LLM cost (R-36) + infrastructure + allocated fixed costs (compliance, SOC 2, insurance, client onboarding, management) ÷ monthly disputes`
`price` must exceed `cost`, and must be at or below the client's current all-in cost per dispute (in-house or BPO), unless the client pays for defensibility.

**Inputs and what we know about each:**
| Input | What we have | Grade | How to get it |
|---|---|---|---|
| Analyst wage | Bank dispute specialists $23.25-30.75/hr (TD), $37-60K/yr (FNBO) | F, A (job postings, WSB S15-S16) | Market our own job ad; Sriram decides pay |
| Loaded multiplier | WSB used $35-45/hr loaded | A (assumption) | Payroll and benefits quotes |
| Analyst minutes per dispute **with** the platform | None. PRD G2 target is a 40% cut from an assumed 10-20 manual minutes; FTI cites ~10 min manual | A; FTI C | Phase 2 analyst trial on synthetic cases; pilot timing (R-24) |
| QA share and supervisor minutes | None (proposed 10% sample after certification) | A | Pilot |
| Escalation and handback share | None; B12 caps over-escalation at 20% on synthetic data only | A | Pilot; U45 |
| LLM cost per case | Measured per case by R-36; no figure yet (offline backend) | n/a | Stage 4 eval report (B17) |
| Fixed costs (SOC 2, insurance, counsel, onboarding per client) | None | n/a | Quotes (U43, U46, U47) |
| Client's current cost per dispute | Assumed $6-15 | A (U13) | Discovery Q3 |
| BPO price per dispute or per FTE | Not disclosed by any vendor we found | n/a (CL) | Discovery; U38 |
| e-OSCAR fees | ACA members averaged ~$10.7K/yr (2019); onboarding plus tiered API fees | B (WSB S14); A (fee structure) | Client keeps paying; confirm who pays (U42) |

**Worked illustration, labelled as such [A]:** at $35-45/hr loaded and the G2 target (6-12 active minutes, a 40% cut from 10-20), analyst labour alone is about **$3.50-9.00 per dispute**. That overlaps the client's own assumed $6-15 before QA, supervision, LLM, compliance and onboarding are added. **Reading [O]:** at specialist-level wages, a 40% productivity gain does not leave a margin at a price that undercuts in-house labour. The service needs one or more of: (a) a much larger cut in analyst minutes than 40%; (b) lower-cost generalist analysts made accurate by the platform (the actual RFS thesis, and the one the accuracy gate must prove); (c) a price premium for SLA certainty and defensibility (U17); (d) clients whose current cost is above the assumed range (part-time managers, overtime, BPO minimums). Each is testable (§7, U38, U39).

**Pricing unit (decision for Sriram):** per completed dispute was decided as the direction. Open: a monthly minimum (the WSB analysis already showed small furnishers are not worth serving without a floor [A]); whether escalated or handed-back cases are billed; onboarding fee. **No price may be quoted before the PRD §12 pricing evidence bar** (unchanged).

## 6. Service-provider obligations and risks
Every row: source, grade, and whether counsel must confirm. **None of this is legal advice.**
| Topic | What the source says | Source, date accessed, grade | What it means for us [O] | Counsel |
|---|---|---|---|---|
| Who holds the FCRA dispute duty | 623(b) duties attach to the furnisher on notice from a CRA | 15 USC 1681s-2(b), LII, 2026-10-19, **A** (REG S1) | The client cannot outsource the duty itself; we perform it for them | Yes: whether we could face direct FCRA claims as agent |
| e-OSCAR agent | Addendum template lets a furnisher authorise a third-party provider to use e-OSCAR and the API on its behalf; furnisher stays liable. ToU: no third-party use except an authorised agent; automation tools including AI permitted with notice of the Operator ID; OLDE may suspend | e-OSCAR addendum and ToU (eff. 2023-06-23), primer log 2026-10-19, **A** (template unsigned; ToU may be superseded) | A path exists, but every client signs an addendum, and OLDE's agent requirements are not public (U2, U42) | Yes |
| CFPB reach over service providers | "Service provider" = a person that provides a material service to a covered person in connection with offering a consumer financial product; the CFPB has supervisory and enforcement authority over supervised service providers, including on-site exams (citing 12 USC 5481(26), 5514(e), 5515(d), 5516(e), 5531, 5536); using a provider "does not absolve" the supervised entity; responsibility may fall on both | CFPB Compliance Bulletin and Policy Guidance 2016-02, Service Providers, files.consumerfinance.gov, accessed 2026-11-07, **A**; listed as "Active - Not Withdrawn" by Morgan Lewis tracker, accessed 2026-11-07, **B** | Assume we are a CFPB "service provider" to each client and can be examined or face UDAAP enforcement. The withdrawn May 2025 dispute guidance does not remove this | Yes: whether and when supervision applies to us |
| Bank regulators' reach | Services performed for a depository institution by contract "shall be subject to regulation and examination ... as if such services were being performed by the depository institution itself"; the bank must notify its regulator within 30 days | 12 USC 1867(c), uscode.house.gov, accessed 2026-11-07, **A** | Bank clients bring OCC/FDIC/Fed examination of our service | Yes |
| Bank third-party risk expectations | Final interagency guidance (Fed, FDIC, OCC, June 2023): use of third parties does not diminish the bank's responsibilities; life cycle of planning, due diligence, contract negotiation, ongoing monitoring, termination; contract terms incl. performance measures, right to audit and remediate, regulator information access, business continuity, subcontractor notice, indemnification and liability limits | 88 FR (2023-06-09), govinfo, accessed 2026-11-07, **A** | Expect full bank-style diligence and contract terms from bank clients; a heavier sale than fintech | Yes |
| Credit unions | NCUA states it has no direct statutory authority to examine CUSOs or vendors (authority expired 2001) | NCUA "Third-Party Vendor Authority", Mar 2022, accessed 2026-11-07, **A, dated** (status may have changed; not re-checked) | Less regulator reach to us, but CUs still run vendor diligence; incumbent CUSO outsourcing exists (TriVerity, CL, B) | No (market note); re-check status |
| GLBA safeguards (nonbank clients) | A financial institution must oversee service providers: select providers capable of appropriate safeguards, require them by contract to implement and maintain safeguards, and periodically assess them. The rule also requires encryption of customer information in transit and at rest, MFA for anyone accessing information systems, and FTC notice within 30 days of discovering a notification event affecting ≥500 consumers | 16 CFR 314.4(f), (c)(3), (c)(5), (j), LII, accessed 2026-11-07, **A** | Nonbank clients must contractually impose these on us; our controls should meet 314.4 regardless. Whether **we** are ourselves a "financial institution" under the rule is unverified | Yes |
| GLBA safeguards (bank clients) | Banks follow the interagency information security guidelines | **Unverified** (not checked today) | Same practical outcome via contract | Yes |
| SOC 2 | A market expectation in vendor diligence, not a legal requirement | Vendor and practitioner blogs, accessed 2026-11-07, **C** | Expect "SOC 2 Type II or a dated plan" questions; Type I before a pilot is a reasonable first target [O]; cost and time unknown (U46) | No |
| FCRA employment screening of analysts | Clients may require background checks on staff who see consumer data | **Unverified, assumption** | Background checks are a likely contract term; background checks are themselves FCRA-regulated | Yes |
| State licensing | Some states license debt collection or loan servicing activity; whether running a creditor's disputes requires any licence is unknown | **Unverified, counsel** | A reason to exclude debt buyers first (§10) | Yes |
| Liability and contracts | Indemnities, liability caps, service credits, data ownership, return or destruction at exit, subprocessor list, audit rights, regulator access | Interagency TPRM 2023 contract list (**A**) for what banks expect; our positions are **decisions** | Draft an MSA, DPA and SLA schedule with counsel before any real data | Yes |
| Insurance | E&O / professional liability and cyber cover are commonly asked for in vendor diligence | **Unverified, assumption** | Get quotes (U43) | No (broker) |
| AI drafting, human analyst approves | Liability allocation when an AI drafts and a human submits | REG counsel item 3, **open** | Now our analyst submits: allocation is between us and the client | Yes |

**Proposed Verification Log rows** for `docs/reference/furnisher-dispute-primer.md` (integrator to paste; product docs only in this task):
| Date | Item verified | Source URL | Verified by | Notes |
|---|---|---|---|---|
| 2026-11-07 | CFPB Bulletin 2016-02: service-provider definition (5481(26)); CFPB supervisory and enforcement authority over supervised service providers; supervised entity not absolved | https://files.consumerfinance.gov/f/documents/102016_cfpb_OfficialGuidanceServiceProviderBulletin.pdf | product-manager | A-grade; non-binding guidance; "Active - Not Withdrawn" per Morgan Lewis tracker (B); counsel |
| 2026-11-07 | 12 USC 1867(c): services performed for a depository institution subject to examination as if performed by the institution; 30-day notice | https://uscode.house.gov/us/usc/t12/s1867/ | product-manager | A-grade; counsel |
| 2026-11-07 | Interagency Guidance on Third-Party Relationships (Fed, FDIC, OCC), 88 FR, 2023-06-09: responsibility not diminished; life cycle; contract provisions | https://www.govinfo.gov/content/pkg/FR-2023-06-09/html/2023-12340.htm | product-manager | A-grade |
| 2026-11-07 | 16 CFR 314.4(f) service-provider oversight; (c)(3) encryption; (c)(5) MFA; (j) FTC notice ≥500 consumers within 30 days | https://www.law.cornell.edu/cfr/text/16/314.4 | product-manager | A-grade; applicability to us as a provider unverified; counsel |
| 2026-11-07 | NCUA lacks direct authority over CUSOs and vendors (as of Mar 2022) | https://www.ncua.gov/files/publications/regulation-supervision/third-party-vendor-authority.pdf | product-manager | A-grade but dated; re-check |

## 7. Changes to Phase 1 and Phase 2 plans, metrics and eval gates
**Phase 1 (synthetic, no interviews):** unchanged in purpose and gates. Additions:
- Stages 1-3 APPROVED 2026-11-07 and built in parallel by module (ADR-011). R-37 to R-43 (tenancy, staff assignment, CLIENT_VIEWER, portal, handoff, SLA config) map into those stages (PRD v1.2 §12). R-44 to R-46 (QA sampling, analyst metrics, per-tenant LLM isolation) are specified now; R-46 is built in Stage 2, R-44 and R-45 are **not** added to the approved stages without Sriram's approval (recommended for Stage 4 or pilot prep).
- Phase 1 exit gate adds S9 (tenancy and portal acceptance criteria) and a cross-tenant isolation test.
- **Eval floors B1-B7 and gates B8-B9 are unchanged.** No floor is relaxed because our own staff review.

**Phase 2 (now the service-buyer and analyst test):**
- Discovery re-targeted at the service buyer (`discovery-plan.md` v2): outsourcing today, BPO spend, vendor-risk process, willingness to hand over e-OSCAR work, price per dispute.
- **New: analyst trial** (proposed): 2-3 non-credentialed trainees, trained per §4, working a blind synthetic set; measures time to proficiency, critical error rate and minutes per case; plus at least 2 experienced practitioners on the same set (expert equivalence). Engaging trainees is a hiring/contracting decision for Sriram (Q16).
- Counsel engaged before any real data (unchanged), now also covering §6.
- Vendor-risk readiness: a security questionnaire answered against our actual controls; SOC 2 readiness quote (U46); insurance quotes (U43).

**Phase 3 pilot (managed-service shadow, then live):** a separate pilot PRD. Proposed shape: weeks 1-4 shadow (our analysts work real ACDVs in parallel; the client's team submits; we compare outcomes and timing); go-live gate on critical error rate (§4), SLA attainment in shadow and client sign-off; then live with client pre-approval of DELETEs. Real-data eval re-baseline per Appendix B (≥300 cases for a ≤1% claim) still applies.

## 8. Intake and access model (new operational dependencies)
- **ACDV intake:** either (a) we log in to e-OSCAR as the client's authorised agent, or (b) the client's middleware or API exports ACDVs to us and imports our responses. (b) keeps the client as submitter and may be the faster pilot path [O]. Both need U42 answered.
- **Evidence:** read-only access to the client's servicing system, a scheduled extract, or a client-run lookup on request. Each has a different SLA and security profile (U44).
- **Analyst identity on responses:** R-20 records `dfAuthorizedName`; whether our analyst or a client officer must be named is unknown (U42).

## 9. ICP reconciliation
**The conflict:** the DECIDED wedge (2026-10-19) is fintech/online lenders and independent auto at ~500-5,000 disputes/month with an in-house team of 3-15 and a named disputes manager. Sriram's service hypothesis names smaller furnishers that find disputes a burden: credit unions, community banks, BNPL, fintech lenders, auto finance, student loan servicers, debt buyers.

**What the pivot changes in the scoring [O]:**
- **Small volume becomes viable.** WSB rejected small furnishers because a tool fee at $4/dispute yields ~$10K/yr from a 2,400-dispute CU [A]. A service earns on the labour it replaces, so revenue per dispute is higher; but **per-client fixed cost** (vendor diligence, addendum, evidence access, client-policy training) sets a floor (U47).
- **A team of 3-15 is now a reason they might not buy** (they have staff and a manager). The better service target is a furnisher whose disputes are handled **part-time** or by 1-3 people, or already outsourced and unhappy.
- **Vendor-oversight burden now matters more than LLM tolerance.** Banks bring examinable service relationships (1867(c), A) and the 2023 TPRM guidance (A); fintechs may bring sponsor-bank diligence (U16).

| Segment | Fit with the service [O] | Main obstacle | Recommendation |
|---|---|---|---|
| Fintech / online lenders (incl. BNPL, where furnishing) | Lean teams; cloud-tolerant [A]; fast decisions [A] | Sponsor-bank diligence (U16); BNPL furnishing volume unknown [no source] | **First**, at the lower part of the band and below it (hypothesis: ~100-1,500/month; test) |
| Independent auto finance | High dispute pain (auto DOFD findings, B) | Unknown in-house depth | **First (co-lead)**, same test |
| Community banks | Burden plausible; many small teams | Bank exam of our service (1867(c), A); bank TPRM (A); slower procurement [A] | **Second**, after SOC 2 Type I and one reference |
| Credit unions | Burden plausible; NCUA lacks vendor authority (A, dated) | Incumbent CUSO outsourcing (TriVerity, B); low volume per CU | **Later, via a CUSO or core partner** (unchanged trigger) |
| Student loan servicers | High volume (C/B) | Federal servicing rules and investor requirements [A]; complex disputes | **Later** |
| Debt buyers / collectors | High volume but 77% of disputes "not generated by an individual" (B, 2019); low value | Possible state licensing questions (unverified); reputational risk | **Not now** |

**Recommended restatement (PROPOSED; Sriram decides):** first segment = **US nonbank consumer lenders (fintech/online including BNPL, and independent auto finance) whose credit bureau disputes are handled part-time or by a small team (about 1-3 FTE), or already outsourced**, with volume high enough to cover per-client onboarding (floor set once U47 is known). Channel ACDV and category payment history unchanged. Community banks second; CUs via channel. This **replaces "500-5,000/month with a 3-15 person team"** only after Sriram decides; until then the ICP memo stands and the discovery plan tests both bands.

## 10. Risks and pre-mortem (pivot-specific; the PRD §11 risks still apply)
"It is November 2027 and the managed service failed. Why?"
| # | Failure reason | Mitigation / test |
|---|---|---|
| 1 | **Smaller furnishers would not let a startup run a regulated process.** Vendor risk or the compliance officer said no, or the sponsor bank did | Discovery asks for the vendor-risk checklist and the last outsourcing approval (Q15-Q17); SOC 2 Type I plan and insurance before the first pilot ask; shadow mode first so the client keeps submitting |
| 2 | **Margins never appeared.** Analysts needed nearly as many minutes as in-house staff; QA and handbacks ate the rest | Measure minutes and critical error rate in the Phase 2 analyst trial before any price is set; kill criterion K3 (§11) |
| 3 | **A trained generalist made a harmful error** (wrongful verify, missed ID theft) and we, not just the client, were named | Platform floors B1-B7 unchanged; certification and QA gate (§4); client pre-approval of DELETE in the pilot; ID theft always handed back; E&O cover; counsel on contract allocation |
| 4 | **We became a BPO.** Revenue scaled only with headcount; the platform did not compound | Track disputes per analyst-hour by month; target the software expansion once the platform is proven in our own operations |
| 5 | **Onboarding each client cost more than it earned.** Each client's systems, policies and e-OSCAR set-up were bespoke | Measure onboarding hours per client (U47); a minimum monthly fee (Sriram decides); standard extract formats; start with clients whose systems we can read by extract |
| 6 | **Sole-founder bandwidth**: Sriram is labeller, reviewer, seller, supervisor and employer | Decision on first operations hire is part of the pilot gate; until then, shadow mode only |

## 11. Kill criteria for the pivot itself (PROPOSED; Sriram decides; tested in Phase 2)
Revert to the software model (or re-plan with Sriram) if any of these holds:
- **K1 Will not outsource:** in service-buyer discovery, fewer than 3 of 10 target furnishers say they would consider handing ACDV handling to a third party, **or** 5 or more say their vendor-risk or compliance function would not approve a startup service provider before it has SOC 2 Type II.
- **K2 No e-OSCAR agent path:** no furnisher will sign the e-OSCAR third-party addendum or export ACDVs to us within 90 days of the start of Phase 2 discovery (also triggers the existing Reg V fallback analysis).
- **K3 Analysts do not reach the gate:** in the Phase 2 analyst trial, no trainee reaches the critical-error gate on the blind synthetic set within the time-to-proficiency budget Sriram sets in advance (Q16), **or** median minutes per case at the gate leave no margin at the highest price at least 3 firms call acceptable.
- **K4 Price below cost:** fewer than 3 firms' acceptable price per dispute is above our modelled cost per dispute at the measured minutes.
- **K5 Liability unacceptable:** counsel advises that the service-provider exposure cannot be bounded by contract and insurance at a cost the price can carry.
Thresholds are opinions to be confirmed by Sriram before discovery starts, so they are not adjusted after the fact.

## 12. Decisions needed from Sriram
| # | Decision | PM recommendation [O] | Needed by |
|---|---|---|---|
| D1 | ICP restatement (§9) | Adopt the lower-volume nonbank band as the hypothesis to test; keep both bands in discovery | Before Phase 2 discovery |
| D2 | Pull service-buyer discovery forward to run in parallel with Stages 1-3 (amends "Phase 1 has no interviews") | Yes [O]: the pivot rests on untested buyer behaviour; the build does not need your labelling hours until Stage 4 | Now |
| D3 | Pivot kill criteria K1-K5 and their thresholds | Confirm before the first call | Before Phase 2 discovery |
| D4 | Pricing structure to test: per dispute only vs per dispute plus monthly minimum, onboarding fee, billing of handbacks | Test per dispute plus a monthly minimum alongside per-dispute only; no price quoted before the §12 bar | Before Phase 2 pricing questions |
| D5 | Client pre-approval of DELETE outcomes during the pilot | Yes, with counsel | Pilot PRD |
| D6 | Analyst model: employees or contractors; onshore only or not; pay band | Onshore employees for the pilot [O] (vendor-risk friction is lower); pay is your call | Before the analyst trial |
| D7 | Analyst trial in Phase 2 (engaging 2-3 trainees and 2 practitioners) and the time-to-proficiency budget for K3 | Yes; set the budget in advance | Phase 2 start |
| D8 | Counsel scope now covers service-provider status, the e-OSCAR addendum as agent, MSA/DPA/SLA, liability caps, state licensing | Engage before any real data (unchanged), scope expanded | Before Phase 3 |
| D9 | SOC 2 path and timing; insurance (E&O, cyber) | Get quotes in Phase 2; Type I before the first live pilot | Phase 2 |
| D10 | Add R-44 (QA sampling) and R-45 (analyst metrics) to Stage 4 scope | Yes, at the Stage 4 approval | Stage 4 gate |

## 13. Self-review
- **Wedge:** one channel and category unchanged; segment restatement proposed, not imposed; segments not served are listed with reasons (§9).
- **Evidence:** every regulatory row has a source, access date and grade or "unverified, counsel". No new statistics: every number is from `docs/research` with its grade, from a primary source checked today, or labelled as an illustration of existing assumptions. No customers, quotes or prices invented.
- **Buildability:** new requirements are R-37 to R-46 in PRD v1.2 with acceptance criteria S9; the one place a developer would need to ask (how a client handoff maps to the state machine) is answered as an attribute plus a developer check (PRD §14).
- **Pre-mortem, success gate, kill criteria:** §10, §4 gate, §11; decisions §12.
- **Compliance:** FCRA duties stay with the client; all service-provider readings flagged for counsel.
- **Would a head of dispute operations recognise this?** The handoff list and SLA are recognisable; whether they would buy it is exactly what Phase 2 must answer.
- **Pushback recorded:** the unit economics may not work at specialist wages (§5); "Phase 1 has no interviews" now carries a higher cost (D2).

## 14. Sources checked today (accessed 2026-11-07)
- YC Winter 2027 RFS summary, "The $15-an-Hour Expert" attributed to Brad Flora, examples include benefits, tax preparation, insurance claims, medical billing, immigration paperwork: https://beinsure.com/news/y-combinators-winter-2027-startup-priorities/ (**B/C**, secondary summary; the YC page itself was not read)
- CFPB Compliance Bulletin and Policy Guidance 2016-02, Service Providers: https://files.consumerfinance.gov/f/documents/102016_cfpb_OfficialGuidanceServiceProviderBulletin.pdf (**A**); page: https://www.consumerfinance.gov/policy-compliance/guidance/supervisory-guidance/compliance-bulletin-and-policy-guidance-2016-02-service-providers/ (**A**, last modified 2023-08-08, not marked withdrawn)
- Morgan Lewis CFPB Guidance Tracker (2016-02 "Active - Not Withdrawn"): https://www.morganlewis.com/topics/cfpb-guidance-tracker-rescinded-and-remaining (**B**)
- 12 USC 1867: https://uscode.house.gov/us/usc/t12/s1867/ (**A**)
- Interagency Guidance on Third-Party Relationships, 88 FR, 2023-06-09: https://www.govinfo.gov/content/pkg/FR-2023-06-09/html/2023-12340.htm (**A**)
- 16 CFR 314.4: https://www.law.cornell.edu/cfr/text/16/314.4 (**A**)
- NCUA, Third-Party Vendor Authority (Mar 2022): https://www.ncua.gov/files/publications/regulation-supervision/third-party-vendor-authority.pdf (**A**, dated)
- SOC 2 as a vendor-diligence expectation: e.g. https://blog.getagency.com/articles/what-enterprise-banks-expect-fintech-soc-2 (**C**)

---

## For the integrator: proposed DECISIONS.md rows (paste as-is)
| Date | Decision | Why | Decided by |
|---|---|---|---|
| 2026-11-07 | **PROPOSED:** PRD v1.2 adopted: managed-service framing; multi-tenancy supersedes the single-tenant non-goal; new requirements R-37 to R-46 (tenancy, staff assignment, CLIENT_VIEWER, client portal, client handoff, per-tenant SLA, QA sampling, analyst metrics, per-tenant LLM isolation); R-37 to R-43 and R-46 map to the approved Stages 1-3; R-44 and R-45 proposed for Stage 4. No safety requirement or eval floor changed; no R-ID renumbered | Records what the 2026-11-07 approval covers and keeps scope committed stage by stage | product-manager (recommends); Sriram confirms |
| 2026-11-07 | **PROPOSED:** ICP restatement for the service model: nonbank consumer lenders (fintech/online incl. BNPL, independent auto) whose disputes are handled part-time or by ~1-3 FTE or already outsourced; community banks second; CUs via channel; debt buyers and student loan servicers not now. ACDV and payment history unchanged | Service revenue makes smaller volumes viable; per-client onboarding cost and vendor oversight set the floor (managed-service-model.md §9) | product-manager (recommends); Sriram decides |
| 2026-11-07 | **PROPOSED:** Pivot kill criteria K1-K5 (managed-service-model.md §11), thresholds fixed before discovery | Prevents moving the goalposts after the calls | product-manager (recommends); Sriram decides |
| 2026-11-07 | **PROPOSED:** Run service-buyer discovery in parallel with Stages 1-3 (amends "Phase 1 has no interviews") | The pivot rests on untested buyer behaviour; Stages 1-3 do not need Sriram's labelling hours | product-manager (recommends); Sriram decides |
| 2026-11-07 | **PROPOSED:** Analyst accuracy gate = 0 critical errors in the last 300 QA-reviewed cases (≤1.0% at 95%), plus time to proficiency and minutes per dispute at the gate as the "$15-an-hour expert" proof metrics | The thesis is accuracy by generalists; 300 is the smallest n that supports ≤1% | product-manager (recommends); Sriram decides |

## For the integrator: proposed HANDOFFS.md entry (paste as-is)
```
## 2026-11-07 | product-manager -> Sriram, developer, market-research | PRD v1.2 and managed-service model memo
- Produced: docs/product/managed-service-model.md (new); docs/product/prd-mvp-v0.md v1.2; docs/product/discovery-plan.md v2 (service buyer); docs/UNKNOWNS.md U37-U48.
- Need back:
  - Sriram: decisions D1-D10 in managed-service-model.md §12 (ICP restatement, pulling discovery forward, kill criteria, pricing structure to test, DELETE pre-approval, analyst model, analyst trial, counsel scope, SOC 2/insurance, Stage 4 scope).
  - developer (web, platform-core): check R-37 to R-43 and R-46 against the module plan; confirm how R-42 client handoff maps to the state machine (proposed as a case attribute, not a new state) and whether R-43 per-tenant config fits ADR-011; flag anything unrealistic rather than descoping.
  - market-research: desk check of BPO/CUSO dispute-outsourcing pricing signals (U38), BNPL furnishing volume, and whether OLDE publishes agent requirements (U42); log sources.
  - integrator: paste the proposed DECISIONS rows and the five proposed Verification Log rows (memo §6) into docs/reference/furnisher-dispute-primer.md.
- Open questions: none blocking the synthetic build. The pivot's commercial premise is untested until service-buyer discovery runs.
- Status: OPEN
```
