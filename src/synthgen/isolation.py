"""R-34 convention: eval-case text must never enter the prompt library.

Convention: prompt templates and few-shot examples live under src/prompts/.
Every generated case's free text, attachment text and claim quotes are hashed
(normalised sentences of >= 25 chars). CI fails if any such hash appears in any
file under src/prompts/. Stage 0 has no prompts yet, so the check runs on an
empty library and on a deliberately contaminated temp library in the tests.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

MIN_LEN = 25
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("​", "")).strip().lower()


def fragments(text: str) -> set[str]:
    out = set()
    for part in _SPLIT.split(text or ""):
        n = _norm(part)
        if len(n) >= MIN_LEN:
            out.add(hashlib.sha256(n.encode("utf-8")).hexdigest())
    return out


def eval_hashes(acdvs: list[dict], labels: list[dict]) -> set[str]:
    hs: set[str] = set()
    for e in acdvs:
        a = e["acdv"]
        hs |= fragments(a.get("free_text", ""))
        for att in a.get("attachments", []):
            hs |= fragments(att.get("extracted_text", ""))
    for l in labels:
        for c in l.get("claims", []):
            hs |= fragments(c["quote"])
    return hs


def contaminated_files(prompt_dir: Path, hashes: set[str]) -> list[str]:
    bad = []
    if not prompt_dir.exists():
        return bad
    for p in sorted(prompt_dir.rglob("*")):
        if p.is_file() and fragments(p.read_text(encoding="utf-8", errors="ignore")) & hashes:
            bad.append(str(p))
    return bad
