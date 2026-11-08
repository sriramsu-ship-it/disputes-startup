# Prompt library (Stage 2, agents module)
One template per LLM step (ADR-005): `classify.md` (R-06), `extract_claims.md` (R-11),
`map_claims.md` (R-11), `draft.md` (R-12). `_rules.md` holds the shared system rules and is
substituted for `{{RULES}}`; `{{DATA}}` becomes one delimited `<untrusted_data>` block per input
(ADR-007, R-14; see `disputes.agents.llm.render_prompt`). Output schemas: `disputes/agents/schemas.py`.

The prompt hash logged with every call (R-21, R-30) is the sha256 of the expanded template
(template file with `_rules.md` substituted, comments kept). Any edit here changes the hash and
triggers the full eval (R-25).

R-34: no text from any generated eval case (T1, T2, T3, the Stage 0 trial) may appear here.
`src/tests/test_isolation.py` fails if one does. Few-shot examples are written by hand; never
paste from `src/data/` or generator output.
