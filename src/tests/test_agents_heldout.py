"""Hand-written held-out letters: how the OFFLINE heuristics cope with wording the generator never uses.

Written by the agents developer on 2026-11-07, not derived from generator templates. Small (n=24)
and written by the same person who wrote the heuristics, so it is a smoke check of brittleness,
not an accuracy estimate. Numbers are reported in docs/engineering/stage-notes/agents.md.
Run: cd src && python -m tests.test_agents_heldout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from disputes.agents.claims import extract_claims, map_claims  # noqa: E402
from disputes.agents.classify import classify  # noqa: E402
from disputes.agents.llm import CaseBudget, OfflineLlmClient  # noqa: E402
from disputes.config import defaults  # noqa: E402
from test_agents_helpers import cycle_ev, make_dispute, note_ev  # noqa: E402

# (letter, free_text, expected llm category set, [(claim substring, expected finding)], evidence spec)
# evidence spec: {month: dpd} plus optional notes
CASES = [
    ("I always pay on the first of the month and the October 2025 one was no exception.", "", {"PAYMENT_HISTORY"},
     [("October 2025 one was no exception", "CONTRADICTED")], {"2025-10": 33}),
    ("Your records show me 30 days behind for Feb 2026. That is wrong, my bank debited it on the 2nd.", "",
     {"PAYMENT_HISTORY"}, [("30 days behind for Feb 2026", "SUPPORTED")], {"2026-02": 0}),
    ("I was never late in 2025.", "", {"PAYMENT_HISTORY"}, [("never late in 2025", "CONTRADICTED")], {"2025-06": 45}),
    ("The December 2025 payment posted late because your website was down for three days.", "",
     {"PAYMENT_HISTORY"}, [("website was down", "NOT_ADDRESSABLE")], {"2025-12": 35}),
    ("I agreed a skip-payment with your call centre for January 2026.", "", {"PAYMENT_HISTORY"},
     [("skip-payment", "NOT_ADDRESSABLE")], {"2026-01": 40}),
    ("You granted me forbearance from May through July 2026, so the June 2026 mark should not be there.", "",
     {"PAYMENT_HISTORY"}, [("forbearance", "SUPPORTED")], {"2026-06": 40, "_note": ("FORBEARANCE", "2026-05-01", "2026-07-31")}),
    ("A copy of my bank statement for March 2026 is enclosed showing the transfer cleared on time.", "",
     {"PAYMENT_HISTORY"}, [("bank statement", "NOT_ADDRESSABLE")], {"2026-03": 31}),
    ("I owe $1,200, not the $2,950 you report.", "", {"BALANCE"}, [("$1,200", "NOT_ADDRESSABLE")], {}),
    ("The amount you show as outstanding is too high by about four hundred dollars.", "", {"BALANCE"}, [], {}),
    ("I closed this card in 2024 and it should be reported as closed by consumer.", "", {"ACCOUNT_STATUS"},
     [("closed this card", "NOT_ADDRESSABLE")], {}),
    ("This loan was paid in full last spring yet you still show it open.", "", {"ACCOUNT_STATUS"}, [], {}),
    ("My surname is spelled incorrectly on your file.", "", {"OTHER"}, [], {}),
    ("Someone applied for this card with my details after my wallet was stolen.", "", {"IDENTITY_FRAUD"},
     [("wallet was stolen", "NOT_ADDRESSABLE")], {}),
    ("I have no idea what this account is; I never signed anything with your company.", "", {"IDENTITY_FRAUD"},
     [("never signed anything", "NOT_ADDRESSABLE")], {}),
    ("My ex-partner took out this loan pretending to be me.", "", {"IDENTITY_FRAUD"}, [], {}),
    ("I reported this account to the police as fraud last year.", "", {"IDENTITY_FRAUD"}, [], {}),
    ("Paid April 2026 early. Paid May 2026 early. Both show late.", "", {"PAYMENT_HISTORY"},
     [("Paid April 2026 early", "CONTRADICTED"), ("Paid May 2026 early", "SUPPORTED")], {"2026-04": 32, "2026-05": 5}),
    ("The late mark for August 2026 is wrong and the balance of $812 is also overstated.", "",
     {"PAYMENT_HISTORY", "BALANCE"}, [("August 2026", "CONTRADICTED")], {"2026-08": 30}),
    ("", "CONSUMER CLAIMS ACCOUNT NOT HIS", {"IDENTITY_FRAUD"}, [], {}),
    ("", "CONSUMER DISPUTES DATE OF LAST PAYMENT", {"PAYMENT_HISTORY"}, [], {}),
    ("I sent 2 payments in Sept 2025 to make up for August 2025 being short.", "", {"PAYMENT_HISTORY"},
     [("2 payments", "NOT_ADDRESSABLE")], {"2025-09": 0, "2025-08": 35}),
    ("Per our call on 2026-04-10 your agent said the March 2026 late fee and mark would be waived.", "",
     {"PAYMENT_HISTORY"}, [("would be waived", "NOT_ADDRESSABLE")], {"2026-03": 38}),
    ("I was in hospital in January 2026 and paid as soon as I got home.", "", {"PAYMENT_HISTORY"},
     [("in hospital", "NOT_ADDRESSABLE")], {"2026-01": 41}),
    ("Kindly update my report; my November 2025 instalment went through on time.", "", {"PAYMENT_HISTORY"},
     [("November 2025 instalment", "CONTRADICTED")], {"2025-11": 30}),
]


def _evidence(spec):
    ev = [cycle_ev(m, dpd, "PH_R30" if dpd >= 30 else "PH_R0_CURRENT") for m, dpd in spec.items() if m != "_note"]
    if "_note" in spec:
        ev.append(note_ev(1, *spec["_note"]))
    return ev


def compute():
    cat_ok, claim_found, claim_total, finding_ok, finding_total, misses = 0, 0, 0, 0, 0, []
    for i, (text, ft, cats, claims_exp, spec) in enumerate(CASES):
        d = make_dispute(text or None, free_text=ft, codes=("PLH-PH-01",), months=())
        b = CaseBudget(OfflineLlmClient(), defaults())
        cl = classify(d, b)
        got = {c.value for c in cl.llm_categories}
        cat_ok += got == cats
        if got != cats:
            misses.append({"case": i, "kind": "category", "expected": sorted(cats), "got": sorted(got)})
        claims, _ = extract_claims(d, b)
        mapped, _ = map_claims(claims, _evidence(spec), b)
        for sub, finding in claims_exp:
            claim_total += 1
            hit = next((c for c in mapped if sub in c.quote), None)
            if hit is None:
                misses.append({"case": i, "kind": "claim_missed", "expected": sub})
                continue
            claim_found += 1
            finding_total += 1
            f = hit.finding.value if hit.finding else None
            finding_ok += f == finding
            if f != finding:
                misses.append({"case": i, "kind": "finding", "claim": sub, "expected": finding, "got": f})
    return {"cases": len(CASES), "category_set_agree": cat_ok, "claims_expected": claim_total,
            "claims_found": claim_found, "findings_scored": finding_total, "finding_agree": finding_ok,
            "misses": misses}


def test_heldout_runs_and_never_misses_fraud_by_route():
    """The only hard assertion: every hand-written fraud letter routes ESCALATE_FRAUD (via LLM
    heuristic or keyword). Everything else is reported, not gated."""
    from disputes.domain import Route
    for text, ft, cats, _, _ in CASES:
        if "IDENTITY_FRAUD" in cats:
            d = make_dispute(text or None, free_text=ft, codes=("PLH-PH-01",), months=())
            assert classify(d, CaseBudget(OfflineLlmClient(), defaults())).route == Route.ESCALATE_FRAUD, text or ft
    rep = compute()
    assert rep["cases"] == len(CASES)


if __name__ == "__main__":
    print(json.dumps(compute(), indent=1))
