"""Synthetic dispute generator v1 (Stage 2, PRD R-26 v1). ALL OUTPUT IS SYNTHETIC.

v1 sits beside v0 and does not change it: `synthgen.generator` (v0, 0.1.0) still produces the
committed Stage 0 fixtures byte-for-byte. Select v1 with `--generator-version 1.0.0`.

What v1 adds (U34): paraphrase banks per claim kind, varied letter structure, greetings,
closings, multi-format dates and low-rate typos (claim spans still code-located and exact);
>=24 injection variants on each of 5 surfaces; compositional fraud phrasings with a
no-near-duplicate selector; realistic structured and free-text SoR notes; new edge cases; a
distinct-variant report with every set; and the T2 red-team suite (`synthgen.v1.redteam`).
"""

GENERATOR_VERSION_V1 = "1.0.0"
