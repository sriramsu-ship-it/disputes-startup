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
- Status: OPEN

## 2026-10-19 | founders -> product-manager | Kickoff: draft the problem brief
- Produced: `CLAUDE.md`
- Need back: problem brief and a first-cut ICP hypothesis, to be pressure-tested against research when it lands.
- Open questions: none
- Status: OPEN

## 2026-10-19 | developer -> product-manager | Feasibility note: MVP core loop
- Produced: `docs/engineering/feasibility-core-loop.md`, `docs/engineering/STATUS.md`; updated `docs/UNKNOWNS.md` (U2 partly resolved; added U6-U10)
- Need back: answers to the 9 questions in section 9 of the note, mainly the first channel (ACDV vs Reg V direct) and dispute category, the pilot deployment model and LLM hosting constraint, the review policy, Metro 2 in or out, and the eval go/no-go thresholds. These are inputs to the PRD and to ADRs 001-010.
- Open questions: (1) Which channel and single dispute category go first? (2) Our SaaS or the customer's cloud for the pilot? (3) Is a hosted LLM with zero retention acceptable? (4) Is 100% human review in the MVP? (5) Metro 2/AUD in or out? (6) Eval thresholds? (7) Audit retention period and export format? (8) Can a design partner sponsor e-OSCAR Stage access and share the middleware-vendor requirements? (9) Who verifies deadlines and code lists with counsel?
- Status: OPEN
