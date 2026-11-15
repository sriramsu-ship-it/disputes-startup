# Prospect Demo Script (Level 1): 20-minute talk track for Sriram

**Date:** 2026-11-14  **Owner:** product-manager  **For:** Sriram only. **DRAFT. No agent contacts anyone; Sriram runs every session and sends every message.**
**Read with:** `level1-demo-brief.md` (what we may and may not claim, §5; what to learn, §8), `discovery-plan.md` v2 (question numbers Qn), PRD v1.3.
Everything in the demo is synthetic. Nothing below is a statistic, a customer or a quote; the bracketed questions are the ones to ask.

**Local first (2026-11-15):** the demo runs on your laptop (`docs/engineering/runbook-local-demo.md`) and you drive it over a screen share. Prospects do not log in. Logins below are the local ones: `u-client-0` (client portal), `u-specialist-1` (analyst), `u-supervisor-1` and `u-supervisor-2` (supervisors). Password and on-screen MFA code: see the runbook.

## Before the session
1. **Morning of the call:** `scripts/demo.sh reset`, so G8 is AT_RISK and every date is fresh (brief LC-03).
2. **30 minutes ahead:** `scripts/demo.sh start` (or `status`), run `verify` and check it passes (LC-10). Sign in once as each of the four logins.
3. Use the demo-only browser profile: no other tabs, bookmarks or autofill; notifications off; share that one window (LC-13). Never show real data.
4. Have the fallback (screenshots or recording from your dry run, LC-14) one click away.
5. Have the session record (brief §8) open in a separate place for notes.
6. "Try your own letter" stays **off** unless you have decided to use it in this session (brief L3). Default: you write the letter live from the prospect's description (brief §6.5).

## Session shape (45 minutes)
| Minutes | Segment | Source |
|---|---|---|
| 0-10 | Discovery before the demo: Q1, Q2, Q3, Q15, Q16 | discovery-plan.md |
| 10-30 | **The 20-minute demo below** | this script |
| 30-40 | Vendor risk, e-OSCAR, evidence, pricing: Q17, Q18, Q19, then Q12-Q13 if time allows (brief L8) | discovery-plan.md |
| 40-45 | Close: Q14 (shadow pilot) and next step | below |
If you only have 20-25 minutes, run the demo and ask only the questions marked **[must]**.

## The demo (20 minutes)

### 0:00-1:30 Framing (say this first, every time)
> "Before I show you anything, three things so I don't mislead you. First, everything you'll see is synthetic: made-up consumers, accounts and bureau requests. Second, it isn't connected to e-OSCAR or any bureau; responses are generated as packages and never sent. Third, the AI steps in this demo (reading the letter, finding the consumer's claims, drafting) run on a rule-based stand-in, not a large language model, so you're seeing the workflow and the controls, not final model quality. Fixed rules decide every proposed outcome, and a person approves every response."
> "The idea: we run your bureau disputes for you, ACDVs starting with payment-history disputes, with trained analysts working in this platform, and you see everything through a portal."

### 1:30-3:30 Client portal (log in as `u-client-0`)
Show: the overview (received, in progress, responded, needs your action, out of scope), the at-risk list (G8), "Needs your action" (G3), the definitions page.
> "This is your view. You see status against the bureau's due date and our internal target, what needs a decision from you, and every completed case's audit export. You can't change anything here; that's deliberate."
- **[must]** "If an outside team ran your ACDVs, who would have to approve that, and who could veto it?" (Q16; U37, K1)
- "What would you want to see here each month to trust that the work is right?" (Q21; U48)

### 3:30-5:00 Analyst queue (switch to `u-specialist-1`)
Show: the queue order (identity fraud first, then at-risk, then by target date), the clock edge on each row, the tenant label.
> "Analysts work this queue. It's ordered by risk and deadline, not by arrival."

### 5:00-7:00 G1 Clean verify
Show: the letter with the claim highlighted ("never been late"), the month-by-month comparison, the claim mapped to the cycle evidence (CONTRADICTED), the proposal VERIFIED_AS_REPORTED with its rule ID, each draft sentence's source and citation.
> "The system can only propose 'verified' when every disputed month matches your records and every claim in the letter is contradicted by cited evidence. If any claim is unresolved, it escalates instead. The analyst still has to approve."
Approve it. Show the package page, headed "NOT SENT".
- **[must]** "Walk me through the last ACDV like this you worked. Which systems did you open, and how many minutes did it take?" (Q1; U13, K3)
- **[must]** "In a pilot, would you rather we worked these as your authorised agent in e-OSCAR, or export them to us and submit our responses yourselves? Whose name would you want as the authorising person?" (Q18; U2, U42, K2)

### 7:00-8:30 G2 Modify
Show: the mismatched month, the single correction, the template sentence stating the outcome (not the AI).
> "When your records say the bureau has it wrong, it proposes a correction for that month only. The outcome wording comes from a fixed template, never from the AI."
- "How would we get this kind of evidence from you: a read-only login, a daily extract, or your team looking things up?" (Q19; U44)

### 8:30-10:30 G4 Hardship / forbearance conflict
Show: ESCALATED / EVIDENCE_CONFLICT, no outcome proposed, the forbearance note and the late month highlighted side by side. Switch to `u-supervisor-1`, take the case, and show the two choices: decide with a reason code, or hand back to the client as a POLICY_DECISION.
> "Your ledger says late; your own note says the account was in forbearance. The system won't pick a side. A supervisor decides with a recorded reason, or hands it back to you if it's a policy call."
- **[must]** "Which disputes would you insist on deciding yourselves: hardship programmes, deletes, attorney letters? Roughly what share of your volume is that?" (Q20; U45)
- "Does this look like what you actually get?" (U20)

### 10:30-12:00 G3 Identity-fraud escalation
Show: top of the supervisor queue, no draft, the handoff to the client with the bureau due date; then in the portal, under "Needs your action".
> "Identity-theft claims follow different rules, so we never draft them. They come straight back to you with the deadline."
- "How do identity-theft claims reach your fraud team today, and how fast?" (U45)

### 12:00-14:00 G5 Prompt-injection letter
Show: the HIGH suspicious-content flag and the matched text; the proposal is the same as the same letter without the injection; approve as `u-specialist-1` → AWAITING_SECOND_APPROVAL; then release it as `u-supervisor-2`. (Optional: if `u-supervisor-1` edited the case earlier, show that their second approval is rejected.)
> "This letter tries to instruct the system to delete the account. It's treated as data: the decision doesn't change, the analyst sees the flag, and a second supervisor has to release it. I'm holding both supervisor logins for the demo; in production those are two different people."
- "Have you seen letters with odd instructions or hidden text, from credit repair firms or anyone else?" (U20, U23)

### 14:00-15:00 G6 Unreadable document
Show: DOC_UNREADABLE with the attachment and its reason.
> "If an attachment can't be read, the case stops. It's never silently skipped, because the duty is to review everything the bureau sends."
- "What share of your attachments are scans or photos?" (OCR trigger, PRD §10)

### 15:00-16:00 G7 Repeat dispute
Show: the REPEAT link to the earlier case and its outcome; the case is still fully investigated.
> "A repeat is linked to the earlier case, but it gets a full investigation, not a copy of the last answer."
- "How do you handle repeat and credit-repair-driven disputes today?" (U1)

### 16:00-17:00 G8 At-risk deadline
Show: AT_RISK, the deadline ruler (today, internal target, due date), its place in the queue and in the portal's at-risk list.
> "Every case carries the bureau's due date and our internal target. As it nears the target it moves up; if a due date ever passed, it would escalate automatically."
- "When a bureau due date falls on a weekend or holiday, what does your team treat as the deadline?" (U21, U36; practice only: counsel decides the rule)

### 17:00-19:00 Audit export (back as `u-client-0`)
Download the export for G1 (or G2). Walk the first page: outcome, decision basis, each claim and its finding, evidence with hashes, who approved and when, timeline against the due date, chain verification.
> "This is designed so a compliance reviewer can see why a response was given without asking us. No examiner has reviewed it yet. What would your compliance team say is missing?"
- **[must]** "If someone challenged one of your responses today, what would you hand to counsel?" (Q6; U3, U48)

### 19:00-20:00 Wrap
> "That's the loop: intake, classify, investigate against your records, cited draft, human approval, a package, and a record you can export. What's the first thing that would stop you from trying this on real disputes in shadow mode, where we work them in parallel and your team still submits?"
- **[must]** Q14: "What would block an 8-week shadow pilot?" (K1, K2)
- "Should the portal show our internal steps, like 'escalated to a supervisor, evidence conflict', or just 'in review'?" (U54)
- "Did the stand-in model get in the way of judging this?" (U51)
- "Would you want access to try it yourself, or to show a colleague without me?" (U49; the hosting trigger, brief L9. Do not promise access; it isn't hosted yet.)

### Optional, if time and L3 allow: try your own letter (2-3 minutes)
> "Tell me what a typical tricky letter you get says, and I'll write a made-up version here. Please don't read me a real one: no real names, numbers or addresses."
Type it as `u-specialist-1` with made-up details, choose the synthetic account scenario, submit, and open the resulting case. If they paste text into the chat instead, read it **before** using it; if anything looks real, don't paste it, say why, and delete the message (brief §6.5). Say: "This shows how the stand-in reads one letter; it isn't a measure of quality."

## Hard questions: exact answers (from brief §5.1; do not improvise past these)
| Question | Answer |
|---|---|
| "How accurate is it?" | "Everything here is synthetic, and we have not measured accuracy on real disputes; that's what a shadow pilot is for. What I can show you is how it's built: it cannot propose 'verified' unless every disputed month matches your records and every claim in the letter is contradicted by cited evidence." |
| "Is it compliant?" | "It's designed around the furnisher's duties when a bureau forwards a dispute, but whether it meets your obligations is your determination with your counsel. Our design hasn't been reviewed by counsel yet." |
| "Do you have SOC 2?" | "Not today. In this demo: one-time-code sign-in, each client's data isolated from every other client's at the application level, and an append-only hash-chained log. Database-level isolation, per-client encryption keys and an independent penetration test come before any real data. What does your vendor-risk team require, and how long does approval usually take?" (Q17) |
| "Are you connected to e-OSCAR?" | "No. The demo uses our own synthetic requests. For a pilot we'd either work as your authorised agent under e-OSCAR's third-party addendum, or you'd export disputes to us and submit our responses yourself." |
| "What does it cost?" | "We're setting pricing with our first design partners. What would you compare it to: your own team's cost per dispute, or what you pay an outsourcer?" |
| "Who are your customers?" | "You're one of the first firms to see it." |
| "Who are the analysts?" | "The model is trained analysts with supervisors and QA reviewing. We'd build that team with our first design partners." |
| "Which AI model, and where does our data go?" | "In this demo, no model provider is involved; the stand-in runs inside the app. For real data, model hosting is something we'd agree with you and your vendor-risk team before anything is sent anywhere. Would a hosted model under zero-retention terms be acceptable, or would it need to run in a cloud account you control?" (Q10; U7) |
| "Do you take on our liability?" | "You keep the furnisher duty under the FCRA. How responsibility is split between us is a contract question we'd settle with counsel. What would you expect?" (U43, K5) |
| "Can we try it with our own letters?" | "Only with made-up details, never a real consumer's letter. Describe one and I'll write a made-up version right now and run it." (Only if brief L3 allows it.) |
| "Can we log in and play with it?" | "Not yet; it runs on my machine while we shape it. If that would help your team, tell me who'd use it and for what, and I'll come back to you." (Record as a hosting-trigger signal, L9; promise nothing.) |

## After the session (within 24 hours)
1. Fill in the session record (brief §8), including each K1-K5 signal.
2. Send the follow-up email (draft below) yourself, if appropriate.
3. If you used "try your own letter" with text the prospect sent, delete the source message; if the case should not remain, `scripts/demo.sh reset`.
4. Count the session toward the hosting trigger (brief L9): did the demo run without the fallback, and did they ask to try it themselves?

## Follow-up email: DRAFT (Sriram edits and sends; never sent by an agent)
**Subject:** Thank you for today

Hi [first name],

Thank you for your time today and for walking me through how [firm] handles bureau disputes. What I took away: [one or two specifics they told you, e.g. who approves outsourcing, their biggest pain].

A few reminders about what you saw, so nothing is misread:
- Everything in it is synthetic, and it isn't connected to e-OSCAR or any bureau. Nothing is ever sent.
- In this version the AI steps run on a rule-based stand-in, so it shows the workflow and the controls rather than final model quality.
- If you'd like me to run a particular kind of letter next time, a short description is all I need. Please don't send a real customer's letter or any real names, numbers or addresses.

Two things that would help me most:
1. [Their open item, e.g. "Your vendor-risk checklist for a provider that sees consumer data, or just the headings."]
2. Would it be useful to do a 30-minute session with [compliance / vendor-risk colleague] to go through the audit export and what they would need to see?

Thanks again,
Sriram

*(No price, no timeline, no compliance or accuracy claim, no attachment containing any data. If they reply with real consumer data, do not open attachments; delete and follow brief §6.4.)*
