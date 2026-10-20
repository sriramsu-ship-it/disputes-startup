# Founder Status Page

**For:** Sriram (sole founder)  **From:** product-manager  **Updated:** 2026-10-19 (after Sriram's decisions in chat)  **Read with:** `docs/product/prd-mvp-v0.md` v1.1
**Bottom line:** Phase 1 is a synthetic-data technical prototype with no interviews. **Stage 0 is approved and handed to the developer.** Nothing past Stage 0 starts without your written approval.

## Decided (2026-10-19, by Sriram)
| # | Decision | Note |
|---|---|---|
| 0 | Employment/IP gate **cleared** | Your own statement that employment is no issue. Recorded as stated; not verified by any agent; no legal advice given |
| - | **Sole founder** | Navneet is no longer involved. You own every decision, label and review |
| - | **Phase 1 = no interviews** | Desk analysis only. `discovery-plan.md` is deferred to Phase 2, not deleted |
| 1 | **Wedge:** fintech/online lenders (500-5,000 disputes/mo); ACDV; payment history end to end; balance classify-only; Reg V triage as fallback | Desk evidence only (B/C); untested until Phase 2 |
| 3 | **Review policy:** 100% human approval; no auto-submit; system never proposes DELETE; second supervisor approval for DELETE and HIGH suspicious content | R-17, R-19 |
| 4 | **Eval:** tiered (PRD Appendix B), T3 ≈100 cases labelled by you alone; you spot-check ≥100 generator-labelled safety cases; agreement between labellers unmeasured | Kappa gate dropped; replaced by an intra-rater re-label check (B9). Labelling ≈70-80 h [A] |
| 5 | **Build:** the developer agent builds; you review and approve in Stages 0-4 | The old 10-12 / 18-21-week figures were for human engineers and do not apply. Calendar time is **unknown** (U28) |

## Still open or deferred
| Item | Status | When it must close |
|---|---|---|
| Pricing test | Deferred to Phase 2 (needs calls). No price may be quoted or pitched before then | Before any pricing claim |
| FCRA counsel | Deferred. **Required before any real data, any pilot, and any compliance claim**; not needed for the synthetic prototype | Before Phase 3 |
| LLM hosting | PROPOSED: hosted, pinned, zero-retention model on **synthetic data only**; `LlmClient` swappable to in-VPC. ADR-006 drafts it in Stage 0 | Your call at the Stage 0 gate (PRD Q13) |
| Audit retention (7-year placeholder) | PROPOSED; counsel sets the real value (U10) | Before a pilot |
| Phase 1 exit gate and evidence bars (below) | PROPOSED | Confirm at the Stage 0 gate (PRD Q12) |
| Reg V fallback clock | PROPOSED: the 90 days start at the first Phase 2 call, since nobody is asked in Phase 1 | Confirm at the Stage 0 gate |

## What Phase 1 can and cannot prove
- **Can:** the intake → investigate → cited draft → human approval → audit record loop works on synthetic data; the rule layer cannot false-verify by construction; measured safety on generated stress sets (false-verify ≤0.5%, escalation and fraud routing ≥98%, 95% bounds); cost and latency per case; how long agent-built stages take.
- **Cannot:** willingness to pay, the real dispute mix, real-data performance, e-OSCAR access, LLM-hosting tolerance, whether practitioners or examiners value it. With one labeller and no outside realism review, the human-set results are directional only.

## Phase 1 exit gate (technical go/no-go; PRD §12)
All must hold: Stages 0-4 approved by you; Appendix B hard floors B1-B7 met on frozen sets, gates B8-B9 met, no tolerance in its no-go zone; acceptance criteria S1-S8 pass; G5 (you reconstruct "why" for 10 of 10 sampled cases from the export alone); the restore drill passes `verify`; a results note labelled "synthetic data, unvalidated realism, one labeller". **Passing authorises Phase 2 only.**

**Before any pricing claim:** Phase 2 pricing questions in ≥8 of 10 calls, ≥3 firms whose range includes the hypothesis, cost per dispute from ≥5 firms, none below $1/dispute.
**Before a pilot:** Phase 1 exit; G2-G4 met with practitioners; realism review and a practitioner relabel of 30 cases; FCRA counsel engaged; a written partner commitment with data and e-OSCAR paths; hosting accepted; reference tables verified; independent security review; a separate pilot PRD.
**Before hiring:** Phase 1 exit; ICP prove conditions met in Phase 2; ≥1 written shadow-pilot commitment; evidence that the agent build plus your review cannot meet the pilot timeline.

## What you do next
1. **Stage 0 review** when the developer hands off: read and approve or reject ADR-001 to 010 (≈8-12 h incl. the trial below [A]). Decide Q12 (exit gate, fallback clock) and Q13 (LLM hosting) at that gate.
2. **Label the 20-case Stage 0 trial set** and time yourself; the PM re-states the labelling budget from your actual minutes.
3. **Log your hours** per stage (U28, U32), so we can forecast Phase 1.
4. **Set a Phase 1 time box at the Stage 1 gate** (PM recommendation, opinion): every Phase 1 week is spent on an untested segment and price, so decide in advance when you would pull Phase 2 discovery forward.
5. Do not quote prices, describe the product as compliant, or touch real data until the bars above are met.

Total Phase 1 time asked of you: **≈105-135 hours** (≈34-53 h stage reviews + ≈70-80 h labelling) [A, PM estimate; re-forecast after Stage 1].
