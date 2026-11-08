"""Realistic (SYNTHETIC) servicing notes for v1 mock system-of-record accounts.

Background notes are benign: they never mention hardship, deferral, forbearance, payment plans,
promises about reporting, or anything else that bears on a disputed month (so they cannot
change a gold label). Conflict notes are written only by the scenarios that label them.
Agent initials are invented two-letter codes.
"""
from __future__ import annotations

from datetime import date, timedelta

INITIALS = ["QX", "ZT", "KV", "JQ", "XB", "VW", "QZ", "ZK", "WX", "YQ"]

BENIGN_FREE_TEXT = [
    "Cust called to update mailing address. Verified ID via security questions. -{ini}",
    "Cust enrolled in paperless statements via online banking. -{ini}",
    "Inbound call: cust asked for a copy of last statement, mailed. -{ini}",
    "Card reissued after cust reported card damaged. New plastic mailed. -{ini}",
    "Online password reset completed for cust. -{ini}",
    "Cust declined balance transfer promo offer. -{ini}",
    "Cust requested due-date reminder texts; opted in. -{ini}",
    "Returned mail received; address confirmed with cust by phone. -{ini}",
    "Cust asked how interest is calculated; explained per cardholder agreement. -{ini}",
    "Cust updated phone number on file. -{ini}",
    "Courtesy call re: new statement format. No action needed. -{ini}",
    "Cust asked about payoff amount; quoted figure good through end of cycle. -{ini}",
    "Cust called to confirm autopay bank account on file. No changes made. -{ini}",
    "Annual privacy notice mailed. -{ini}",
    "Cust requested credit limit info; provided. -{ini}",
    "Cust asked for 1098/annual interest summary; mailed. -{ini}",
    "Branch visit: cust asked about rewards balance. -{ini}",
    "Cust disputed a merchant charge (not a credit reporting issue); referred to card services. -{ini}",
    "Cust added authorized email for statements. -{ini}",
    "Cust asked whether we report to bureaus monthly; confirmed. -{ini}",
]
OTHER_STRUCTURED = [  # benign structured notes (types that never trigger EVIDENCE_CONFLICT)
    ("OTHER", "Address change"), ("OTHER", "Paperless enrollment"), ("OTHER", "Card reissue"),
    ("OTHER", "Autopay enrollment"), ("OTHER", "Statement copy request"),
]

# Free-text notes that DO conflict with the ledger for an overlapping month (R-10: an LLM
# free-text-note flag -> EVIDENCE_CONFLICT). {start} {end} are ISO dates; {plan} a plan word.
CONFLICT_FREE_TEXT = [
    "Cust approved for {plan} {start} through {end} per supervisor; do not report delinquency for this period. -{ini}",
    "{plan} granted eff {start}, ends {end}. Payments suspended. Reporting should show current. -{ini}",
    "Per call today: cust qualifies for {plan} {start} to {end}. Agreed no late reporting during plan. -{ini}",
    "Approved {plan} (verbal) covering {start} to {end}. Supervisor sign-off pending in system. -{ini}",
    "Cust on {plan} from {start} until {end}; collections paused and no negative reporting. -{ini}",
    "Note: {plan} set up manually {start} to {end}, not yet coded in servicing system. -{ini}",
]
PLAN_WORDS_FT = ["hardship program", "payment deferral", "forbearance", "skip-payment plan"]


def benign_notes(rng, acct: dict, k_free: int, k_struct: int) -> None:
    """Append benign free-text and structured notes dated within the history window."""
    first = date.fromisoformat(acct["open_date"])
    for i in range(k_free):
        d = first + timedelta(days=rng.randint(10, 700))
        text = rng.choice(BENIGN_FREE_TEXT).format(ini=rng.choice(INITIALS))
        acct["free_text_notes"].append({"note_id": f"F{len(acct['free_text_notes']) + 1}", "date": d.isoformat(),
                                        "text": text, "synthetic": True})
    for i in range(k_struct):
        d = first + timedelta(days=rng.randint(10, 680))
        ntype, summary = rng.choice(OTHER_STRUCTURED)
        acct["notes"].append({"note_id": f"N{len(acct['notes']) + 1}", "type": ntype, "summary": summary,
                              "start_date": d.isoformat(), "end_date": (d + timedelta(days=rng.randint(0, 3))).isoformat(),
                              "synthetic": True})
