"""Distinct-variant count report (U34), emitted with every v1 set as variant_report.json.

Counts are computed from the generated data itself (labels + ACDVs), not from the catalogs
alone, so the report says what a given set actually contains.
"""
from __future__ import annotations

import collections
import itertools
import re
import statistics

from .. import vocab
from . import injections as inj, phrasing as ph

_MONTHS = "|".join(sorted(vocab.MONTH_NAMES + vocab.MONTH_ABBR, key=len, reverse=True))
_MASK_MONTH = re.compile(rf"\b(?:{_MONTHS})\b\.?")
_MASK_NUM = re.compile(r"\$?\d[\d,/\-]*(?:st|nd|rd|th)?")
NEAR_DUP_JACCARD = 0.6  # word-3-gram Jaccard at or above this counts as a near-duplicate


def skeleton(text: str) -> str:
    """Quote with months, numbers, dates and amounts masked: counts phrasing, not slot values."""
    return _MASK_NUM.sub("<N>", _MASK_MONTH.sub("<M>", text)).strip()


def _shingles(text: str) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(w[i:i + 3]) for i in range(max(0, len(w) - 2))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def near_duplicate_stats(passages: list[str]) -> dict:
    sh = [_shingles(p) for p in passages]
    mx, pairs = 0.0, 0
    for i, j in itertools.combinations(range(len(sh)), 2):
        s = _jaccard(sh[i], sh[j])
        mx = max(mx, s)
        pairs += s >= NEAR_DUP_JACCARD
    return {"max_pairwise_word3gram_jaccard": round(mx, 4), "near_duplicate_pairs": pairs,
            "near_duplicate_threshold": NEAR_DUP_JACCARD}


def variant_report(data: dict) -> dict:
    labels = [l for l in data["labels"] if l["scenario"] != "duplicate"]
    by_case = {e["case_id"]: e for e in data["acdvs"]}
    cat = inj.catalog()

    # ---- injection surfaces
    surf: dict[str, dict] = {}
    for s in inj.SURFACES:
        used = [l["injection"] for l in labels if l.get("injection") and l["injection"]["surface"] == s]
        surf[s] = {
            "catalog_variants": len(cat[s]),
            "cases": len(used),
            "distinct_variants_used": len({u["variant_id"] for u in used}),
            "variant_classes_used": len({u["variant_class"] for u in used}),
            "placements_or_styles_used": sorted({u.get("placement") or u.get("style") or "-" for u in used}),
        }

    # ---- claims per kind and per claim_type
    kinds: dict[str, dict] = collections.defaultdict(lambda: {"claims": 0, "templates": set(), "quotes": set(),
                                                                "skeletons": set()})
    for l in labels:
        for c in l["claims"]:
            k = kinds[c.get("claim_kind", "?")]
            k["claim_type"] = c["claim_type"]
            k["claims"] += 1
            k["templates"].add(c.get("template_id"))
            k["quotes"].add(c["quote"])
            k["skeletons"].add(skeleton(c["quote"]))
    per_kind = {}
    for name, k in sorted(kinds.items()):
        avail = len(ph.CLAIM_KINDS[name][1]) if name in ph.CLAIM_KINDS else len(ph.FRAUD_DENIALS)
        per_kind[name] = {"claim_type": k["claim_type"], "templates_available": avail, "claims": k["claims"],
                          "distinct_templates_used": len(k["templates"]), "distinct_quotes": len(k["quotes"]),
                          "distinct_skeletons": len(k["skeletons"])}
    per_type: dict[str, dict] = {}
    for name, k in kinds.items():
        t = per_type.setdefault(k["claim_type"], {"claims": 0, "templates": set(), "quotes": set(), "skeletons": set()})
        t["claims"] += k["claims"]
        t["templates"] |= k["templates"]
        t["quotes"] |= k["quotes"]
        t["skeletons"] |= k["skeletons"]
    per_type_out = {n: {"claims": t["claims"], "distinct_templates_used": len(t["templates"]),
                        "distinct_quotes": len(t["quotes"]), "distinct_skeletons": len(t["skeletons"])}
                    for n, t in sorted(per_type.items())}

    # ---- fraud
    fr = [l["fraud_phrasing"] for l in labels if l.get("fraud_phrasing")]
    combos = [(f["denial"], f["explanation"], f["action"]) for f in fr]
    fraud = {
        "cases": len(fr),
        "components_available": {"denials": len(ph.FRAUD_DENIALS), "explanations": len(ph.FRAUD_EXPLANATIONS),
                                 "actions": len(ph.FRAUD_ACTIONS)},
        "combinations_possible": len(ph.FRAUD_DENIALS) * len(ph.FRAUD_EXPLANATIONS) * len(ph.FRAUD_ACTIONS),
        "distinct_combinations_used": len(set(combos)),
        "distinct_passages": len({f["passage"] for f in fr}),
        "distinct_passage_skeletons": len({skeleton(f["passage"]) for f in fr}),
        "indirect_phrasing_cases": sum(f["indirect"] for f in fr),
        "max_shared_components_between_two_cases": max(
            (sum(x == y for x, y in zip(a, b)) for a, b in itertools.combinations(combos, 2)), default=0),
        **near_duplicate_stats([skeleton(f["passage"]) for f in fr]),
    }

    # ---- letters
    letters, feats = [], []
    for l in labels:
        e = by_case[l["case_id"]]
        atts = e["acdv"]["attachments"]
        if atts:
            letters.append(atts[0]["extracted_text"])
        feats.append(l.get("letter_features") or {})
    chars = [f.get("chars", 0) for f in feats if f]
    tids = collections.Counter(t.split(".")[0] for l in labels for t in l.get("template_ids", []))
    distinct_tids = collections.defaultdict(set)
    for l in labels:
        for t in l.get("template_ids", []):
            distinct_tids[t.split(".")[0]].add(t)
    letters_out = {
        "letters": len(letters),
        "distinct_letter_texts": len(set(letters)),
        "distinct_greetings_used": len({f.get("greeting") for f in feats if f}),
        "distinct_closings_used": len({f.get("closing") for f in feats if f}),
        "structures_used": dict(sorted(collections.Counter(f.get("structure") for f in feats if f).items())),
        "with_header_block": sum(1 for f in feats if f.get("header")),
        "month_styles_used": sorted({s for f in feats for s in f.get("month_styles", [])}),
        "day_styles_used": sorted({s for f in feats for s in f.get("day_styles", [])}),
        "letters_with_typos": sum(1 for f in feats if f.get("typos")),
        "typos_total": sum(f.get("typos", 0) for f in feats),
        "chars_min": min(chars) if chars else 0,
        "chars_median": int(statistics.median(chars)) if chars else 0,
        "chars_max": max(chars) if chars else 0,
        "distinct_templates_used_by_bank": {k: len(v) for k, v in sorted(distinct_tids.items())},
        "template_draws_by_bank": dict(sorted(tids.items())),
    }
    return {"synthetic": True, "n_cases": len(data["labels"]), "n_non_duplicate_cases": len(labels),
            "injection_surfaces": surf, "claims_by_kind": per_kind, "claims_by_type": per_type_out,
            "fraud": fraud, "letters": letters_out}
