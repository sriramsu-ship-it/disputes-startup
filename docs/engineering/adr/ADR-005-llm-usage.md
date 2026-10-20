# ADR-005: LLM usage — structured outputs, code-located quotes, template-built drafts, outcome never from the model

**Date:** 2026-10-20  **Status:** Proposed (built in Stage 2)  **Author:** developer

## Context
The LLM does classification (R-06), claim extraction and mapping (R-11), and cited narrative sentences (R-12). False-verify is the main consumer harm (N3). R-13 requires a deterministic validator; R-15 bounds time and calls; R-30 pins the model. REV §2 showed models are unreliable at character offsets and that "which sentence is factual" cannot be decided without an LLM judge.

## Decision
1. **No tools, no actions.** The model only returns JSON validated against a schema per step (`classify`, `extract_claims`, `map_claims`, `draft_sentences`). Invalid JSON → one retry → escalate.
2. **Outcome and corrected values never come from the model.** R-10 rules decide; templates render them.
3. **Quotes, not offsets.** The model returns verbatim quotes; code locates spans (exact, then whitespace/quote-normalised). Unlocatable → QUOTE_UNLOCATED.
4. **Drafts = sentence objects.** Every LLM sentence must cite ≥1 known evidence ID; non-cited text comes only from a versioned template library; outcome words in LLM sentences are rejected (R-13).
5. **Confidence is logged, never gating** (R-06). Disagreement between the code map and the LLM, or UNCERTAIN, escalates. Any IDENTITY_FRAUD signal routes out.
6. **Max 4 calls per case**, 60s timeout, 1 retry, 90s budget (R-15). Every call logs model ID, prompt-template hash, input hashes, output, tokens and cost (R-21, R-36).
7. **Eval isolation (R-34):** prompts live in `src/prompts/`; CI fails if any eval-case text appears there (check built in Stage 0).

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Constrained structured steps as above** | False-verify path is rules-only; validator is deterministic; auditable per step | More calls than one prompt; draft prose is stiffer | Medium |
| One "investigate and draft" prompt | Fewer calls, fluent prose | Outcome inside free text; unverifiable; injection reaches the decision | High |
| LLM-as-judge validator | Can check support, not just citation | A model on the safety path; needs calibration we cannot do yet | Low (add later) |

## Consequences
The validator proves a citation exists and quotes match, **not that evidence supports the sentence**; that is measured by B7 (human check). Claim-extraction recall (U22) is the residual false-verify risk and is gated by B10. Prompt changes trigger the full eval (R-25).

## Compliance and security impact
Every model-driven output is reproducible from logged inputs, prompt hash and model ID. Injected text cannot change the outcome by construction (B1/B5). Model risk reviewers get a per-step contract and metrics rather than a single opaque prompt.

## Revisit trigger
B10 claim recall below 90%, B15 validator rejections above 10%, or calibrated human-vs-judge agreement that would justify an LLM judge.
