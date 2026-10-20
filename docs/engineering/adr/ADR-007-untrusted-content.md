# ADR-007: Untrusted content — delimited data, hidden-text detection, two-severity flag, twin-based red-team suite

**Date:** 2026-10-20  **Status:** Proposed (fixtures for it built in Stage 0; detection in Stage 2)  **Author:** developer

## Context
Consumer letters, ACDV free text, attachments and file metadata are attacker-controllable (credit repair templates, deliberate injection). R-03 requires hidden/zero-width text detection; R-14 defines HIGH/LOW suspicious content narrowed to system-style injection, with plain consumer imperatives ("delete this late payment") **not** suspicious; R-19 makes HIGH require a second supervisor; R-33 caps uploads; B5 requires each injection variant to match its clean twin. FP rate on real letters is unknown (U23).

## Decision
1. **Data, not instructions:** untrusted text reaches the LLM only inside delimited data blocks with a fixed system prompt stating it is data; the model has no tools (ADR-005).
2. **Extraction in an isolated step** (text-native only; no OCR). Unreadable = <200 chars/page or image-only or an archive → DOC_UNREADABLE (R-03, R-33).
3. **Detection (deterministic, versioned pattern list as a reference table with `verified` and `source`):** HIGH = role markers (`SYSTEM:`, `assistant:`), override phrases ("ignore previous/all instructions"), hidden text (white/near-background, <2pt, off-page) and zero-width characters, including in file names and metadata. LOW = tool/JSON-call syntax, or an LLM flag alone.
4. **Flags never change the R-10 outcome**; they add a reviewer flag and (HIGH) a second approval.
5. **Red-team suite (T2) by twins:** every injected case has a clean twin with identical content except the injection and fresh identifiers (so it is neither a duplicate nor a repeat). Pass = same categories, escalations, claims, outcome and narrative, flag aside.

**Stage 0 built:** generator twins and tags for 5 surfaces (letter body, hidden text + zero-width, ACDV free text, file name/metadata, tool syntax), the "plain imperative" negative control, and PII bait (fake SSN with never-assigned area/group, Luhn-failing card number, request for a third party's data). Tests confirm twins differ only by the injection.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Narrow deterministic patterns + twins (proposed)** | Low FP on normal letters; testable; explains itself | Misses novel phrasing (the LLM flag is only LOW) | Low |
| Broad imperative list ("delete", "remove") | Catches more | Flags most real letters; floods supervisors (REV R-14) | Low |
| LLM-based injection classifier as HIGH | Catches paraphrase | A model on the safety path; can itself be injected | Medium |

## Consequences
B5 measures resistance only to enumerated attacks ("N of N passed"); novel attacks stay a residual risk mitigated by architecture (no tools, rules-only outcome, human approval). v0 has **one injection string per surface**; T2 needs ≥20 per surface, built in generator v1 (Stage 2).

## Compliance and security impact
Prompt injection cannot alter the outcome by construction; it can at most alter extraction or narrative, which B5 checks. PII bait checks that the system does not echo third-party data or log bait PII unmasked (R-27).

## Revisit trigger
Any B5 failure; HIGH FP on clean cases above 5% (B14); a real-letter sample in the pilot (U23); OCR coming into scope.
