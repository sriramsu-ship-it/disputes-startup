---
description: Run the market-research, product-manager, and developer agents in sequence on a goal, with handoffs and founder checkpoints
argument-hint: <goal, e.g. "decide the ICP and define the MVP for the furnisher dispute platform">
---

Goal: $ARGUMENTS

Run the team on this goal. Read `CLAUDE.md`, `docs/HANDOFFS.md`, `docs/UNKNOWNS.md`, and `docs/DECISIONS.md` first, then work through the steps below, delegating each to the named subagent. Pass each agent the goal, the paths of the files it should read, and the file it should produce. Do not do their work yourself.

1. **market-research**: gather the evidence the goal depends on. Produce a report in `docs/research/` using the template, with evidence grades, disconfirming evidence, and a handoff to `product-manager`.
2. **product-manager**: using that research, make the decision or draft the artifact the goal calls for (ICP memo, PRD, MVP scope, pilot plan). Save to `docs/product/`. Run the pre-mortem. Hand off to `developer` for feasibility.
3. **developer**: review the PM's draft for feasibility, risks, effort range, and options for anything costly. Save to `docs/engineering/`. If the goal includes building, build only from an approved PRD, with tests and an eval baseline, and update `docs/engineering/STATUS.md`.
4. **product-manager**: incorporate the developer's feedback, finalize the artifact, log decisions in `docs/DECISIONS.md`, and update `docs/UNKNOWNS.md`.

Checkpoints: stop and ask the founders before anything involving pricing, legal exposure, customer commitments, hiring, or fundraising, and whenever the evidence is too weak (grade C) to support the decision.

When finished, reply with: the recommendation in 2-3 sentences, confidence and what would change it, the file paths produced, decisions needed from the founders, and the next step. Do not recap the process.
