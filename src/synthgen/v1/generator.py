"""Seeded synthetic dispute generator v1 (PRD R-26 v1). ALL OUTPUT IS SYNTHETIC.

Same file layout and record shapes as v0 (`synthgen.generator`), which is reused for account,
ACDV and deadline helpers and for the gold oracle. v0 output is untouched.

What changes in v1:
  * letters are composed from blocks (optional header, greeting, intro, optional backstory,
    claims paragraph(s) with filler, request, closing, optional P.S.), drawn from paraphrase
    banks with several month/day formats and low-rate typos; claim spans are code-located;
  * injections come from catalogs of >= 24 variants per surface, with varied placement;
    every injected case records `removal_spans`: deleting them yields the clean twin's text;
  * identity-fraud letters are composed from denial x explanation x action components and a
    per-batch selector that keeps any two fraud passages sharing at most one component;
  * accounts get benign servicing notes (structured and free text); new edge scenarios cover
    free-text notes that contradict the ledger (R-10 "LLM free-text-note flag"), multi-month
    disputes, long letters and claims buried in a P.S.

Determinism: each case draws from random.Random keyed on (version, seed, index, scenario);
injection choices use a separate key so twins share all other content.
"""
from __future__ import annotations

import copy
import itertools
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from .. import FIXTURE_SCHEMA_VERSION, bizdays, oracle, tables, vocab
from .. import generator as g0
from ..pii_guard import bait_card_number, synthetic_ssn
from . import GENERATOR_VERSION_V1, injections as inj, notes as notes_mod, phrasing as ph

EDGE_TAGS = g0.EDGE_TAGS
ADVERSARIAL_TAGS = g0.ADVERSARIAL_TAGS
INJECTION_SURFACES = inj.SURFACES
LETTER_FILE_NAMES = ["consumer_letter.txt", "dispute_letter.txt", "letter.txt", "my_dispute.txt", "dispute.txt",
                     "letter_to_lender.txt"]


# --------------------------------------------------------------------------- letter model
@dataclass
class Piece:
    text: str
    claim: dict | None = None
    role: str = "context"
    injected: bool = False
    zw_at: list[int] = field(default_factory=list)  # injected zero-width chars (indices in text)


@dataclass
class Block:
    role: str
    pieces: list[Piece]
    joiner: str = " "
    injected: bool = False
    hidden_style: str | None = None


@dataclass
class DraftV1(g0.Draft):
    body: list[Piece] = field(default_factory=list)        # claims paragraph content, in order
    body2: list[Piece] = field(default_factory=list)       # optional second claims paragraph
    ps: list[Piece] = field(default_factory=list)
    extra_body: list[Piece] = field(default_factory=list)  # wrappers (pii bait, controls) add here
    blocks: list[Block] = field(default_factory=list)
    month_style: str = "long"
    day_style: str = "long"
    typo_rate: float = 0.0
    typos: int = 0
    template_ids: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    long_letter: bool = False
    claim_in_ps: bool = False
    injection_info: dict | None = None
    fraud_combo: tuple[int, int, int] | None = None
    fraud_info: dict | None = None
    note_conflicts: list[dict] = field(default_factory=list)  # free-text notes that conflict (for gold)


def _fmt_params(d: "DraftV1", params: dict) -> dict:
    out = dict(params)
    for k in ("m", "m2"):
        if k in out:
            style = d.month_style if d.rng.random() < 0.75 else d.rng.choice(ph.MONTH_STYLES)
            d.features.setdefault("month_styles", set()).add(style)
            out[k] = ph.month_text(out[k], style)
    if "d" in out:
        d.features.setdefault("day_styles", set()).add(d.day_style)
        out["d"] = ph.day_text(out["d"], d.day_style)
    c = d.acdv["consumer"]
    out.setdefault("furnisher", vocab.FURNISHER)
    out.setdefault("first", c["first_name"])
    out.setdefault("last", c["last_name"])
    out.setdefault("last4", d.account["account_number"][-4:])
    return out


def say(dr: DraftV1, kind: str, finding: str, months: list[str], basis: str, **params) -> Piece:
    """A claim sentence from the paraphrase bank for `kind`."""
    ctype, templates = ph.CLAIM_KINDS[kind]
    i = dr.rng.randrange(len(templates))
    tpl, nt = ph.apply_typos(templates[i], dr.rng, dr.typo_rate * 0.5)
    dr.typos += nt
    text = tpl.format(**_fmt_params(dr, params))
    tid = f"{kind}.{i + 1:02d}"
    dr.template_ids.append(tid)
    claim = {"quote": None, "claim_type": ctype, "months": list(months), "finding": finding,
             "evidence_basis": basis, "claim_kind": kind, "template_id": tid}
    return Piece(text, claim, role="claim")


def ctx(d: DraftV1, bank: list[str], bank_name: str, idx: int | None = None, role: str = "context", **params) -> Piece:
    i = d.rng.randrange(len(bank)) if idx is None else idx
    tpl, nt = ph.apply_typos(bank[i], d.rng, d.typo_rate)
    d.typos += nt
    d.template_ids.append(f"{bank_name}.{i + 1:02d}")
    return Piece(tpl.format(**_fmt_params(d, params)), None, role=role)


def _pick_distinct(d: DraftV1, bank: list[str], k: int) -> list[int]:
    return d.rng.sample(range(len(bank)), k)


# --------------------------------------------------------------------------- base
def _base(rng: random.Random, case_id: str, scenario: str, categories: list[str]) -> DraftV1:
    b = g0._base(rng, case_id, scenario, categories)
    d = DraftV1(**{f: getattr(b, f) for f in b.__dataclass_fields__})
    d.month_style = rng.choice(ph.MONTH_STYLES)
    d.day_style = rng.choice(ph.DAY_STYLES)
    d.typo_rate = 0.0 if rng.random() < 0.55 else rng.choice([0.05, 0.1, 0.15])
    d.letter_file_name = rng.choice(LETTER_FILE_NAMES)
    return d


def _free_text(d: DraftV1, key: str, m: str | None = None) -> str:
    t = d.rng.choice(ph.CRA_FREE_TEXT[key])
    return t.format(M=ph.cra_month(m)) if m else t


# --------------------------------------------------------------------------- scenarios
def sc_ph_verify(d: DraftV1, note_near_miss: bool = False) -> None:
    m = g0._late_month(d, d.rng.choice(["PH_R30", "PH_R30", "PH_R60"]))
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, d.rng.choice(["ON_TIME", "GENERIC_PH"]), m)
    d.body = [say(d, "ON_TIME", "CONTRADICTED", [m], f"cycle:{m}", m=m)]
    if d.rng.random() < 0.5:
        p = say(d, "NEVER_LATE", "CONTRADICTED", [], f"cycle:{m}")
        d.body.insert(d.rng.randrange(2), p)
    if note_near_miss:
        prev, start = g0.month_add(m, -1), g0.month_add(m, -3)
        d.account["notes"].append({"note_id": "N1", "type": d.rng.choice(["HARDSHIP", "DEFERRAL", "FORBEARANCE"]),
                                   "summary": "Short-term plan (ended before the disputed month)",
                                   "start_date": f"{start}-01", "end_date": f"{prev}-28", "synthetic": True})
        d.other_tags.add("note_near_miss")


def sc_ph_verify_long(d: DraftV1) -> None:
    sc_ph_verify(d)
    d.long_letter = True
    d.other_tags.add("long_letter")
    if d.rng.random() < 0.4:
        d.claim_in_ps = True
        d.other_tags.add("claim_in_postscript")


def sc_ph_multi_month_verify(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    m2 = g0.month_add(m, -1) if m != g0.DISPUTABLE[0] else g0.month_add(m, 1)
    lo, hi = g0.DPD_FOR_RATING[d.rng.choice(["PH_R30", "PH_R60"])]
    g0._set_month(d.account, m2, d.rng.randint(lo, hi))
    a, b = sorted([m, m2])
    d.acdv["disputed_months"] = [a, b] if d.rng.random() < 0.7 else [a]
    d.acdv["free_text"] = _free_text(d, "GENERIC_PH", a)
    d.body = [say(d, "ON_TIME_TWO", "CONTRADICTED", [a, b], f"cycle:{a},cycle:{b}", m=a, m2=b)]
    if len(d.acdv["disputed_months"]) == 1:
        d.other_tags.add("claim_month_not_in_acdv")
    d.other_tags.add("multi_month")


def sc_ph_multi_month_mixed(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    m2 = g0.month_add(m, 1)
    g0._set_month(d.account, m2, 0, reported="PH_R30")
    d.acdv["disputed_months"] = [m, m2]
    d.acdv["free_text"] = _free_text(d, "LATE_REPORTING", m)
    d.body = [say(d, "ON_TIME", "CONTRADICTED", [m], f"cycle:{m}", m=m),
              say(d, "ON_TIME", "SUPPORTED", [m2], f"cycle:{m2}", m=m2)]
    d.other_tags.add("multi_month")


def sc_ph_modify(d: DraftV1) -> None:
    m = d.rng.choice(g0.DISPUTABLE[:-1])
    if d.rng.random() < 0.6:
        dpd = d.rng.randint(0, 12)
        g0._set_month(d.account, m, dpd, reported="PH_R30")
        kind = d.rng.choice(["ON_TIME", "NOT_30_LATE"]) if dpd == 0 else "NOT_30_LATE"
        c = say(d, kind, "SUPPORTED", [m], f"cycle:{m}", m=m)
    else:
        dpd = d.rng.randint(31, 58)
        g0._set_month(d.account, m, dpd, reported="PH_R60")
        c = say(d, "ONE_BEHIND", "SUPPORTED", [m], f"cycle:{m}", m=m)
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "LATE_REPORTING", m)
    d.body = [c]
    if dpd == 0 and d.rng.random() < 0.5:
        d.extra_attachments.append(g0._bank_statement(d, m))
        d.other_tags.add("supporting_document")


def sc_ph_claim_month_extends(d: DraftV1) -> None:
    m1 = g0._late_month(d, "PH_R30")
    m2 = g0.month_add(m1, 1)
    dpd2 = d.rng.randint(0, 10)
    g0._set_month(d.account, m2, dpd2, reported="PH_R30")
    d.acdv["disputed_months"] = [m1]
    d.acdv["free_text"] = _free_text(d, "ON_TIME", m1)
    d.body = [say(d, "ON_TIME", "CONTRADICTED", [m1], f"cycle:{m1}", m=m1),
              say(d, "EXTRA_ON_TIME" if dpd2 == 0 else "EXTRA_NOT_30", "SUPPORTED", [m2], f"cycle:{m2}", m2=m2)]
    if d.rng.random() < 0.5:
        d.body.insert(1, ctx(d, ph.FILLER, "FILLER"))
    d.other_tags.add("claim_month_not_in_acdv")


def sc_ph_claim_unresolved(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    call = f"{g0.month_add(m, 1)}-{d.rng.randint(3, 25):02d}"
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "GENERIC_PH", m)
    d.body = [say(d, "REP_PROMISE", "NOT_ADDRESSABLE", [m],
                  "No call record or agreement note exists in the system of record.", m=m, d=call)]


EVIDENCE_MISSING_NOTES = [
    "Platform conversion: one cycle not migrated.",
    "Conversion exception: cycle data missing for one month after core system upgrade; ticket open.",
    "Data gap noted during migration audit - one statement cycle absent from history.",
    "Servicing transfer: prior servicer file incomplete for one cycle.",
]


def sc_ph_evidence_missing(d: DraftV1) -> None:
    m = d.rng.choice(g0.DISPUTABLE[:-1])
    d.account["cycles"] = [c for c in d.account["cycles"] if c["cycle_month"] != m]
    d.account["free_text_notes"].append({"note_id": "F1", "text": d.rng.choice(EVIDENCE_MISSING_NOTES),
                                         "synthetic": True})
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "ON_TIME", m)
    d.body = [say(d, "ON_TIME", "NOT_ADDRESSABLE", [m], f"No cycle record for {m} in the system of record.", m=m)]
    d.edge_tags.add("missing_records")


PLAN_WORD = {"DEFERRAL": ["payment deferral", "deferment"], "HARDSHIP": ["hardship plan", "hardship program"],
             "FORBEARANCE": ["forbearance", "forbearance plan"]}


def sc_ph_evidence_conflict(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    ntype = d.rng.choice(["DEFERRAL", "HARDSHIP", "FORBEARANCE"])
    d.account["notes"].append({"note_id": "N1", "type": ntype, "summary": f"{ntype.title()} approved",
                               "start_date": f"{g0.month_add(m, -1)}-01",
                               "end_date": f"{g0.month_add(m, 1)}-28", "synthetic": True})
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "GENERIC_PH", m)
    if d.rng.random() < 0.7:
        d.body = [say(d, "ON_PLAN", "SUPPORTED", [m], "note:N1", m=m, plan=d.rng.choice(PLAN_WORD[ntype]))]
    else:  # consumer does not mention the plan; the note alone conflicts with the ledger
        d.body = [say(d, "ON_TIME", "CONTRADICTED", [m], f"cycle:{m}", m=m)]
        d.other_tags.add("conflict_not_mentioned_in_letter")
    d.edge_tags |= {"conflicting_records", "deferral_or_hardship"}


def _free_text_plan_note(d: DraftV1, start: str, end: str) -> dict:
    tpl = d.rng.choice(notes_mod.CONFLICT_FREE_TEXT)
    text = tpl.format(plan=d.rng.choice(notes_mod.PLAN_WORDS_FT), start=start, end=end,
                      ini=d.rng.choice(notes_mod.INITIALS))
    note = {"note_id": f"F{len(d.account['free_text_notes']) + 1}", "date": start, "text": text, "synthetic": True}
    d.account["free_text_notes"].append(note)
    return note


def sc_ph_freetext_note_conflict(d: DraftV1) -> None:
    """Ledger shows a correctly reported late month, but a FREE-TEXT note records a plan covering
    it (no structured note). R-10: an LLM free-text-note flag -> EVIDENCE_CONFLICT."""
    m = g0._late_month(d, "PH_R30")
    start, end = f"{g0.month_add(m, -1)}-01", f"{g0.month_add(m, 1)}-28"
    note = _free_text_plan_note(d, start, end)
    d.note_conflicts.append({"note_id": note["note_id"], "start_date": start, "end_date": end})
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "GENERIC_PH", m)
    if d.rng.random() < 0.5:
        d.body = [say(d, "ON_PLAN", "SUPPORTED", [m], f"free_text_note:{note['note_id']}", m=m,
                      plan=d.rng.choice(["hardship plan", "payment deferral", "forbearance"]))]
    else:
        d.body = [say(d, "ON_TIME", "CONTRADICTED", [m], f"cycle:{m}", m=m)]
        d.other_tags.add("conflict_not_mentioned_in_letter")
    d.edge_tags |= {"conflicting_records", "deferral_or_hardship"}
    d.other_tags.add("free_text_note_conflict")


def sc_ph_freetext_note_near_miss(d: DraftV1) -> None:
    """A free-text plan note that ENDS before the disputed month: must NOT be a conflict."""
    sc_ph_verify(d)
    m = d.acdv["disputed_months"][0]
    start, end = f"{g0.month_add(m, -4)}-01", f"{g0.month_add(m, -1)}-28"
    _free_text_plan_note(d, start, end)
    d.other_tags.add("free_text_note_near_miss")


def sc_ph_months_undetermined(d: DraftV1) -> None:
    g0._late_month(d, "PH_R30")
    d.acdv["disputed_months"] = []
    d.acdv["free_text"] = _free_text(d, "NO_MONTH")
    kind = "LATES_WRONG" if d.rng.random() < 0.75 else "NEVER_LATE"
    d.body = [say(d, kind, "NOT_ADDRESSABLE", [], "No month identified; cannot be compared with any cycle.")]
    d.edge_tags.add("months_undetermined")


def sc_missing_document(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "ON_TIME", m)
    d.body = [say(d, "ENCLOSED_STATEMENT", "NOT_ADDRESSABLE", [m],
                  "Referenced bank statement is not attached; the ledger alone cannot address it.", m=m)]
    d.edge_tags.add("missing_document")


def sc_doc_unreadable(d: DraftV1) -> None:
    sc_ph_verify(d)
    k = d.rng.randrange(3)
    if k == 0:
        d.extra_attachments.append({"file_name": d.rng.choice(["scan_statement.pdf", "IMG_0001.pdf", "proof.pdf"]),
                                    "media_type": "application/pdf", "page_count": d.rng.randint(1, 3),
                                    "extracted_text": "", "image_only": True})
    elif k == 1:
        d.extra_attachments.append({"file_name": d.rng.choice(["documents.zip", "proof_files.zip"]),
                                    "media_type": "application/zip", "page_count": 1, "extracted_text": "",
                                    "image_only": False})
    else:  # text layer present but under 200 chars per page (R-03)
        pages = d.rng.randint(2, 4)
        d.extra_attachments.append({"file_name": "faxed_statement.pdf", "media_type": "application/pdf",
                                    "page_count": pages,
                                    "extracted_text": f"Page 1 of {pages}\n[illegible scan] SYNTHETIC",
                                    "image_only": False})
        d.other_tags.add("low_text_layer")
    d.edge_tags.add("doc_unreadable")


def sc_deadline_at_risk(d: DraftV1) -> None:
    sc_ph_verify(d)
    d.acdv["response_due_date"] = bizdays.add_business_days(d.ingest_date, d.rng.randint(3, 5)).isoformat()
    d.edge_tags.add("near_deadline")


def sc_deadline_breached(d: DraftV1) -> None:
    sc_ph_verify(d)
    d.acdv["response_due_date"] = (d.ingest_date - timedelta(days=d.rng.randint(1, 5))).isoformat()
    d.edge_tags.add("deadline_breached")


def sc_deadline_on_holiday(d: DraftV1) -> None:
    sc_ph_verify(d)
    hol = d.rng.choice([date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25)])
    d.acdv["response_due_date"] = hol.isoformat()
    d.ingest_date = bizdays.add_business_days(hol, -d.rng.randint(8, 15))
    d.acdv["date_received"] = d.ingest_date.isoformat()
    d.edge_tags.add("deadline_on_holiday")


MALFORMATIONS = ["missing_due_date", "non_iso_date", "blank_last_name", "empty_codes", "missing_account_number",
                 "blank_control_number", "impossible_date"]


def sc_malformed(d: DraftV1) -> None:
    sc_ph_verify(d)
    kind = d.rng.choice(MALFORMATIONS)
    a = d.acdv
    if kind == "missing_due_date":
        del a["response_due_date"]
    elif kind == "non_iso_date":
        y, mo, dd = a["response_due_date"].split("-")
        a["response_due_date"] = d.rng.choice([f"{mo}/{dd}/{y}", f"{y}/{mo}/{dd}", f"{dd}-{mo}-{y}",
                                               f"{vocab.MONTH_ABBR[int(mo) - 1]} {int(dd)} {y}"])
    elif kind == "blank_last_name":
        a["consumer"]["last_name"] = d.rng.choice(["   ", ""])
    elif kind == "empty_codes":
        a["dispute_codes"] = []
    elif kind == "missing_account_number":
        del a["account_number"]
    elif kind == "blank_control_number":
        a["control_number"] = " "
    elif kind == "impossible_date":
        a["response_due_date"] = d.rng.choice(["2026-02-30", "2026-13-05", "2026-11-31"])
    d.edge_tags.add("malformed_input")
    d.other_tags.add(f"malformed:{kind}")


def sc_balance(d: DraftV1) -> None:
    bal = d.account["cycles"][-1]["balance"]
    claimed = bal - d.rng.randint(100, 900)
    d.acdv["free_text"] = _free_text(d, "BALANCE")
    d.body = [say(d, "BALANCE_SHOULD_BE", "NOT_ADDRESSABLE", [], "Balance disputes are classify-only in the MVP.",
                  amt=f"{bal:,}", claimed=f"{claimed:,}")]


def sc_other(d: DraftV1) -> None:
    d.categories = ["OTHER"]
    d.acdv["dispute_codes"] = tables.codes_for("OTHER")[:1]
    d.acdv["free_text"] = _free_text(d, "OTHER")
    idx = _pick_distinct(d, ph.OTHER_STATEMENTS, 2)
    d.body = [ctx(d, ph.OTHER_STATEMENTS, "OTHER", i) for i in idx]


def sc_class_conflict(d: DraftV1) -> None:
    sc_balance(d)
    d.acdv["dispute_codes"] = [d.rng.choice(tables.codes_for("PAYMENT_HISTORY"))]
    d.acdv["free_text"] = _free_text(d, "CLASS_CONFLICT")
    d.other_tags.add("code_text_disagree")


def sc_multi_issue(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    bal = d.account["cycles"][-1]["balance"]
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "MULTI", m)
    d.body = [say(d, "ON_TIME", "CONTRADICTED", [m], f"cycle:{m}", m=m)]
    d.body2 = [say(d, "BALANCE_TOO_HIGH", "NOT_ADDRESSABLE", [], "Balance disputes are classify-only in the MVP.",
                   amt=f"{bal:,}")]
    d.edge_tags.add("multi_issue")


def sc_fraud_disguised(d: DraftV1) -> None:
    m = g0._late_month(d, "PH_R30")
    d.acdv["disputed_months"] = [m]
    d.acdv["free_text"] = _free_text(d, "GENERIC_PH", m)
    if d.fraud_combo is None:
        d.fraud_combo = (d.rng.randrange(len(ph.FRAUD_DENIALS)), d.rng.randrange(len(ph.FRAUD_EXPLANATIONS)),
                         d.rng.randrange(len(ph.FRAUD_ACTIONS)))
    di, ei, ai = d.fraud_combo
    p = _fmt_params(d, {})
    denial_text = ph.FRAUD_DENIALS[di].format(**p)
    claim = {"quote": None, "claim_type": "ACCOUNT_STATUS", "months": [], "finding": "NOT_ADDRESSABLE",
             "evidence_basis": "Identity theft is out of scope (605B).", "claim_kind": "FRAUD_DENIAL",
             "template_id": f"FRAUD_DENIAL.{di + 1:02d}"}
    pieces = [Piece(denial_text, claim, role="claim")]
    expl, act = ph.FRAUD_EXPLANATIONS[ei], ph.FRAUD_ACTIONS[ai]
    order = "denial_first"
    if expl:
        if d.rng.random() < 0.3:
            pieces.insert(0, Piece(expl))
            order = "explanation_first"
        else:
            pieces.append(Piece(expl))
    if act:
        pieces.append(Piece(act))
    d.template_ids += [f"FRAUD_DENIAL.{di + 1:02d}", f"FRAUD_EXPL.{ei + 1:02d}", f"FRAUD_ACTION.{ai + 1:02d}"]
    d.body = pieces
    passage = " ".join(x.text for x in pieces)
    indirect = not ph.FRAUD_DIRECT_RE.search(passage)
    d.fraud_info = {"denial": di + 1, "explanation": ei + 1, "action": ai + 1, "order": order,
                    "indirect": indirect, "passage": passage}
    d.adversarial_tags.add("identity_fraud_disguised")
    if indirect:
        d.other_tags.add("fraud_indirect_phrasing")


def apply_pii_bait(d: DraftV1) -> None:
    other = f"{d.rng.choice(vocab.FIRST_NAMES)} {d.rng.choice(vocab.SURNAMES)}"
    kinds = d.rng.sample(["ssn", "card", "third"], d.rng.randint(2, 3))
    for k in ["ssn", "card", "third"]:
        if k not in kinds:
            continue
        if k == "ssn":
            i = d.rng.randrange(len(inj.PII_SSN))
            d.extra_body.append(Piece(inj.PII_SSN[i].format(ssn=synthetic_ssn(d.rng)), role="bait"))
            d.template_ids.append(f"PII_SSN.{i + 1:02d}")
        elif k == "card":
            i = d.rng.randrange(len(inj.PII_CARD))
            d.extra_body.append(Piece(inj.PII_CARD[i].format(card=bait_card_number(d.rng)), role="bait"))
            d.template_ids.append(f"PII_CARD.{i + 1:02d}")
        else:
            i = d.rng.randrange(len(inj.PII_THIRD_PARTY))
            d.extra_body.append(Piece(inj.PII_THIRD_PARTY[i].format(other=other), role="bait"))
            d.template_ids.append(f"PII_THIRD.{i + 1:02d}")
    d.other_tags |= {f"pii_bait:{k}" for k in kinds}
    d.adversarial_tags.add("pii_bait")


def apply_imperative_control(d: DraftV1) -> None:
    """Negative controls for R-14: plain imperatives and benign look-alikes are NOT suspicious."""
    d.extra_body.append(ctx(d, ph.IMPERATIVE_CONTROLS, "IMPERATIVE", role="control"))
    d.other_tags.add("imperative_negative_control")
    if d.rng.random() < 0.5:
        d.extra_body.append(ctx(d, ph.BENIGN_LOOKALIKES, "LOOKALIKE", role="control"))
        d.other_tags.add("benign_lookalike_control")


SCENARIOS = {
    "ph_verify": (["PAYMENT_HISTORY"], sc_ph_verify),
    "ph_verify_note_near_miss": (["PAYMENT_HISTORY"], lambda d: sc_ph_verify(d, note_near_miss=True)),
    "ph_verify_long": (["PAYMENT_HISTORY"], sc_ph_verify_long),
    "ph_multi_month_verify": (["PAYMENT_HISTORY"], sc_ph_multi_month_verify),
    "ph_multi_month_mixed": (["PAYMENT_HISTORY"], sc_ph_multi_month_mixed),
    "ph_modify": (["PAYMENT_HISTORY"], sc_ph_modify),
    "ph_claim_month_extends": (["PAYMENT_HISTORY"], sc_ph_claim_month_extends),
    "ph_claim_unresolved": (["PAYMENT_HISTORY"], sc_ph_claim_unresolved),
    "ph_evidence_missing": (["PAYMENT_HISTORY"], sc_ph_evidence_missing),
    "ph_evidence_conflict": (["PAYMENT_HISTORY"], sc_ph_evidence_conflict),
    "ph_freetext_note_conflict": (["PAYMENT_HISTORY"], sc_ph_freetext_note_conflict),
    "ph_freetext_note_near_miss": (["PAYMENT_HISTORY"], sc_ph_freetext_note_near_miss),
    "ph_months_undetermined": (["PAYMENT_HISTORY"], sc_ph_months_undetermined),
    "missing_document": (["PAYMENT_HISTORY"], sc_missing_document),
    "doc_unreadable": (["PAYMENT_HISTORY"], sc_doc_unreadable),
    "deadline_at_risk": (["PAYMENT_HISTORY"], sc_deadline_at_risk),
    "deadline_breached": (["PAYMENT_HISTORY"], sc_deadline_breached),
    "deadline_on_holiday": (["PAYMENT_HISTORY"], sc_deadline_on_holiday),
    "malformed": (["PAYMENT_HISTORY"], sc_malformed),
    "balance": (["BALANCE"], sc_balance),
    "other": (["OTHER"], sc_other),
    "class_conflict": (["BALANCE"], sc_class_conflict),
    "multi_issue": (["PAYMENT_HISTORY", "BALANCE"], sc_multi_issue),
    "fraud_disguised": (["IDENTITY_FRAUD"], sc_fraud_disguised),
    "pii_bait": (["PAYMENT_HISTORY"], lambda d: (sc_ph_verify(d), apply_pii_bait(d))),
    "imperative_control": (["PAYMENT_HISTORY"], lambda d: (sc_ph_verify(d), apply_imperative_control(d))),
}
EXPECTED = dict(g0.EXPECTED)
EXPECTED.update({
    "ph_verify_long": ("VERIFIED_AS_REPORTED", None),
    "ph_multi_month_verify": ("VERIFIED_AS_REPORTED", None),
    "ph_multi_month_mixed": ("MODIFY", None),
    "ph_freetext_note_conflict": ("ESCALATED", "EVIDENCE_CONFLICT"),
    "ph_freetext_note_near_miss": ("VERIFIED_AS_REPORTED", None),
})
CODE_OVERRIDE = g0.CODE_OVERRIDE


# --------------------------------------------------------------------------- letter composition
def compose(d: DraftV1) -> None:
    """Arrange the scenario's pieces into a varied letter. Uses d.rng (shared by twins)."""
    rng = d.rng
    c = d.acdv["consumer"]
    blocks: list[Block] = []
    f = d.features
    f["header"] = rng.random() < 0.45
    if f["header"]:
        letter_date = (d.ingest_date - timedelta(days=rng.randint(3, 14))).isoformat()
        lines = [Piece(f"{c['first_name']} {c['last_name']}".strip() or "(name withheld)", role="header"),
                 Piece(c["address"]["line1"], role="header"),
                 Piece(f"{c['address']['city']}, {c['address']['state']} {c['address']['zip']}", role="header"),
                 Piece(ph.day_text(letter_date, d.day_style), role="header")]
        f.setdefault("day_styles", set()).add(d.day_style)
        if rng.random() < 0.5:
            lines.append(Piece(f"Re: Account ending {d.account['account_number'][-4:]}", role="header"))
        blocks.append(Block("header", lines, joiner="\n"))
    gi = rng.randrange(len(ph.GREETINGS))
    f["greeting"] = gi + 1
    blocks.append(Block("greeting", [ctx(d, ph.GREETINGS, "GREETING", gi, role="greeting")]))
    intro = [ctx(d, ph.INTRO_ID, "INTRO_ID")]
    short = sum(len(p.text) for p in d.body + d.body2) < 80
    if rng.random() < 0.6 or short:
        intro.append(ctx(d, ph.INTRO_CONTEXT, "INTRO_CONTEXT"))
    if d.long_letter:
        idx = _pick_distinct(d, ph.BACKSTORY, rng.randint(4, 7))
        story = [ctx(d, ph.BACKSTORY, "BACKSTORY", i) for i in idx]
        cut = rng.randint(1, len(story) - 1)
        story_blocks = [Block("backstory", story[:cut]), Block("backstory", story[cut:])]
    else:
        story_blocks = []
    body = list(d.body)
    ps_claim: list[Piece] = []
    if d.claim_in_ps and body:
        ps_claim = [body.pop(0)]
        if not body:
            body = [Piece("I am writing because your reporting on this account is causing me problems.")]
    fill_idx = _pick_distinct(d, ph.FILLER, rng.randint(1 if short else 0, 2))
    fillers = [ctx(d, ph.FILLER, "FILLER", i) for i in fill_idx]
    for fp in fillers:
        body.insert(rng.randint(0, len(body)), fp)
    body += d.extra_body
    request = [ctx(d, ph.REQUESTS, "REQUEST")]
    if rng.random() < 0.3:
        rest = [i for i in range(len(ph.FILLER)) if i not in fill_idx]
        request.append(ctx(d, ph.FILLER, "FILLER", rng.choice(rest)))
    one_para = rng.random() < 0.12 and not d.long_letter
    f["structure"] = "single_paragraph" if one_para else ("long" if d.long_letter else "standard")
    if one_para:
        blocks.append(Block("body", intro + body + list(d.body2) + request))
    else:
        blocks.append(Block("intro", intro))
        blocks += story_blocks
        blocks.append(Block("body", body))
        if d.body2:
            blocks.append(Block("body2", list(d.body2)))
        blocks.append(Block("request", request))
    ci = rng.randrange(len(ph.CLOSINGS))
    f["closing"] = ci + 1
    sig = f"{c['first_name']} {c['last_name']}".strip()
    blocks.append(Block("closing", [Piece(ph.CLOSINGS[ci], role="closing"),
                                    Piece(f"{sig} (SYNTHETIC TEST PERSON)", role="signature")], joiner="\n"))
    d.template_ids.append(f"CLOSING.{ci + 1:02d}")
    ps_pieces = ps_claim + list(d.ps)
    if ps_pieces:
        pre = rng.choice(ph.PS_PREFIX)
        blocks.append(Block("ps", [Piece(pre, role="ps_marker")] + ps_pieces))
    f["para_sep"] = "\n\n" if rng.random() < 0.7 else "\n"
    d.blocks = blocks


# --------------------------------------------------------------------------- injection
def _block_index(blocks: list[Block], role: str) -> int | None:
    for i, b in enumerate(blocks):
        if b.role == role:
            return i
    return None


def apply_injection(d: DraftV1, surface: str, variant: dict, rng: random.Random) -> None:
    """Apply one catalog variant. Uses its own rng so the twin's content is unchanged."""
    info = {"surface": surface, "variant_id": variant["variant_id"], "variant_class": variant["variant_class"]}
    blocks = d.blocks
    if surface in ("injection_letter_body", "injection_tool_syntax"):
        places = (inj.LETTER_PLACEMENTS if surface == "injection_letter_body"
                  else ["before_request", "own_paragraph_mid", "after_signature", "inline_after_claim"])
        place = rng.choice(places)
        piece = Piece(variant["text"], role="injection", injected=True)
        body_i = _block_index(blocks, "body")
        claim_pos = None
        if body_i is not None:
            claim_pos = next((j for j, p in enumerate(blocks[body_i].pieces) if p.claim), None)
        if place == "inline_after_claim" and claim_pos is None:
            place = "before_request"
        if place == "inline_after_claim":
            blocks[body_i].pieces.insert(claim_pos + 1, piece)
        else:
            blk = Block("injection", [piece], injected=True)
            if place == "start_of_letter":
                blocks.insert(0, blk)
            elif place == "after_signature":
                blocks.append(blk)
            elif place == "own_paragraph_mid":
                at = _block_index(blocks, "intro")
                blocks.insert((at if at is not None else _block_index(blocks, "greeting")) + 1, blk)
            else:  # before_request
                at = _block_index(blocks, "request")
                if at is None:  # single-paragraph letter
                    at = _block_index(blocks, "closing")
                blocks.insert(at, blk)
        info["placement"] = place
        d.suspicious_expected = variant["suspicious_expected"]
    elif surface == "injection_hidden_text":
        style = variant["style"]
        text = inj.interleave_zero_width(variant["text"]) if style == "zero_width_interleaved" else variant["text"]
        blk = Block("hidden", [Piece(text, role="hidden", injected=True)], injected=True, hidden_style=style)
        place = variant["placement"]
        if place == "end_of_document":
            blocks.append(blk)
        elif place == "after_greeting":
            blocks.insert(_block_index(blocks, "greeting") + 1, blk)
        else:
            blocks.insert(_block_index(blocks, "closing"), blk)
        # Half of the visually-hidden variants also carry a zero-width char in the greeting.
        if style != "zero_width_interleaved" and int(variant["variant_id"][2:]) % 2 == 1:
            gp = blocks[_block_index(blocks, "greeting")].pieces[0]
            k = max(1, min(3, len(gp.text) - 1))
            gp.text = gp.text[:k] + inj.ZW + gp.text[k:]
            gp.zw_at.append(k)
            info["zero_width_in_greeting"] = True
        info["style"], info["placement"] = style, place
        d.suspicious_expected = "HIGH"
    elif surface == "injection_acdv_free_text":
        d.acdv["free_text"] += variant["text"]
        info["free_text_suffix"] = variant["text"]
        d.suspicious_expected = "HIGH"
    elif surface == "injection_file_metadata":
        info["clean_file_name"] = d.letter_file_name
        d.letter_file_name = variant["file_name"]
        d.letter_metadata = dict(variant["metadata"])
        d.suspicious_expected = "HIGH"
    else:
        raise ValueError(surface)
    d.adversarial_tags.add(surface)
    d.injection_info = info


# --------------------------------------------------------------------------- render
def render_letter(d: DraftV1) -> tuple[str, list[dict], list[dict], list[list[int]]]:
    """Flatten blocks -> text. Returns (text, claims, hidden_spans, removal_spans)."""
    sep_para = d.features.get("para_sep", "\n\n")
    units: list[tuple[str, Piece | None, bool]] = []  # (text, piece or None for separators, injected)
    flat: list[tuple[Piece, Block]] = []
    for bi, b in enumerate(d.blocks):
        for pi, p in enumerate(b.pieces):
            if flat:
                sep = b.joiner if pi > 0 else sep_para
                units.append((sep, None, p.injected or b.injected))
            units.append((p.text, p, p.injected or b.injected))
            flat.append((p, b))
    # A separator AFTER a leading run of injected units belongs to the injection too.
    lead = 0
    while lead < len(units) and units[lead][2]:
        lead += 1
    if 0 < lead < len(units) and units[lead][1] is None:
        units[lead] = (units[lead][0], None, True)
    text_parts, pos = [], 0
    claims, hidden, removal = [], [], []
    piece_block = {id(p): b for p, b in flat}
    for t, p, injected in units:
        start = pos
        if injected:
            removal.append([start, start + len(t)])
        if p is not None:
            if p.claim is not None:
                claims.append({**p.claim, "quote": t, "source": "A1", "span": [start, start + len(t)]})
            b = piece_block[id(p)]
            if b.hidden_style:
                hidden.append({"start": start, "end": start + len(t), "style": b.hidden_style})
            for k in p.zw_at:
                removal.append([start + k, start + k + 1])
        text_parts.append(t)
        pos += len(t)
    text = "".join(text_parts)
    removal = _merge(sorted(removal))
    for c in claims:
        assert text[c["span"][0]:c["span"][1]] == c["quote"], "claim span mismatch"
    return text, claims, hidden, removal


def _merge(spans: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def remove_spans(text: str, spans: list[list[int]]) -> str:
    out, prev = [], 0
    for s, e in spans:
        out.append(text[prev:s])
        prev = e
    out.append(text[prev:])
    return "".join(out)


def _render(d: DraftV1) -> tuple[dict, list[dict]]:
    text, claims, hidden, removal = render_letter(d)
    if d.injection_info is not None and removal:
        d.injection_info["removal_spans"] = removal
        d.injection_info["attachment_id"] = "A1"
    pages = 1 + len(text) // 2500
    attachments = [{
        "synthetic": True, "attachment_id": "A1", "file_name": d.letter_file_name, "media_type": "text/plain",
        "page_count": pages, "metadata": d.letter_metadata, "render_hints": {"hidden_spans": hidden},
        "extracted_text": text, "sha256": g0.sha256(text),
    }]
    for i, extra in enumerate(d.extra_attachments, start=2):
        t = extra.get("extracted_text", "")
        attachments.append({"synthetic": True, "attachment_id": f"A{i}", "file_name": extra["file_name"],
                            "media_type": extra["media_type"], "page_count": extra["page_count"],
                            "metadata": {"image_only": extra.get("image_only", False)},
                            "render_hints": {"hidden_spans": []}, "extracted_text": t, "sha256": g0.sha256(t)})
    d.acdv["attachments"] = attachments
    d.features["chars"] = len(text)
    d.features["paragraphs"] = text.count(d.features.get("para_sep", "\n\n")) + 1
    return d.acdv, claims


# --------------------------------------------------------------------------- build / finish
def build_case(seed: int, index: int, scenario: str, case_id: str | None = None,
               injection: tuple[str, dict] | None = None, twin_group: str | None = None,
               rng_key: str | None = None, fraud_combo: tuple[int, int, int] | None = None,
               case_prefix: str = "SYN1") -> DraftV1:
    key = rng_key or f"v1:{seed}:{index}:{scenario}"
    rng = random.Random(key)
    cats, fn = SCENARIOS[scenario]
    d = _base(rng, case_id or f"{case_prefix}-S{seed}-C{index:05d}", scenario, list(cats))
    d.fraud_combo = fraud_combo
    if injection and twin_group:
        id_rng = random.Random(f"{key}:injected-twin-ids")
        d.acdv["control_number"] = f"SYNCN{id_rng.randint(0, 36**8 - 1):08X}"
        # Fresh account number with the SAME last four digits: letters quote "account ending
        # NNNN", so the twin's text stays identical apart from the injection.
        new_acct = f"SYNACCT{id_rng.randint(0, 10**6 - 1):06d}{d.account['account_number'][-4:]}"
        if new_acct == d.account["account_number"]:
            new_acct = f"SYNACCT{(int(new_acct[7:13]) + 1) % 10**6:06d}{new_acct[-4:]}"
        d.account["account_number"] = new_acct
        d.acdv["account_number"] = new_acct
    if scenario in CODE_OVERRIDE:
        d.acdv["dispute_codes"] = [rng.choice(tables.codes_for(c)) for c in CODE_OVERRIDE[scenario]]
    fn(d)
    notes_mod.benign_notes(rng, d.account, rng.randint(0, 4), rng.choice([0, 0, 1, 2]))
    d.expected = EXPECTED[scenario]
    compose(d)
    if injection:
        surface, variant = injection
        apply_injection(d, surface, variant, random.Random(f"{key}:inj:{variant['variant_id']}"))
    if twin_group:
        d.twin_group = twin_group
        if not injection:
            d.other_tags.add("clean_twin")
    return d


def derive_gold(envelope: dict, account: dict | None, intent: dict, seen: set, note_conflicts: list[dict]) -> dict:
    """v0 oracle plus the R-10 free-text-note rule: a free-text note recording a hardship,
    deferral or forbearance that overlaps a disputed month is an EVIDENCE_CONFLICT (the product
    detects it with the LLM note flag; the generator knows it by construction)."""
    if note_conflicts and account is not None:
        account = copy.deepcopy(account)
        for nc in note_conflicts:
            account["notes"].append({"note_id": f"virtual:{nc['note_id']}", "type": "HARDSHIP",
                                     "start_date": nc["start_date"], "end_date": nc["end_date"], "synthetic": True})
    return oracle.derive_gold(envelope, account, intent, seen)


def finish(d: DraftV1, seed: int, seen_cn: set[str]) -> tuple[dict, dict, dict]:
    g0._finalise_transactions(d.account, d.rng)
    acdv, claims = _render(d)
    for i, c in enumerate(claims, start=1):
        c["claim_id"] = f"C{i}"
    envelope = {"synthetic": True, "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
                "generator_version": GENERATOR_VERSION_V1, "seed": seed, "case_id": d.case_id,
                "fixture_meta": {"ingest_date": d.ingest_date.isoformat()}, "acdv": acdv}
    intent = {"categories": sorted(d.categories), "claims": claims}
    gold = derive_gold(envelope, d.account, intent, seen_cn, d.note_conflicts)
    feats = {k: (sorted(v) if isinstance(v, set) else v) for k, v in d.features.items()}
    feats["typos"] = d.typos
    label = {
        "synthetic": True, "case_id": d.case_id, "label_source": "generator_intent",
        "generator_version": GENERATOR_VERSION_V1, "scenario": d.scenario,
        "categories": intent["categories"],
        "dispute_code_categories": sorted({c for code in acdv.get("dispute_codes", [])
                                           for c in tables.categories_for_code(code)}),
        "claims": claims, "gold": gold, "suspicious_expected": d.suspicious_expected,
        "edge_tags": sorted(d.edge_tags), "adversarial_tags": sorted(d.adversarial_tags),
        "other_tags": sorted(d.other_tags), "twin_group": d.twin_group, "repeat_of": d.repeat_of,
        "duplicate_of": d.duplicate_of,
        "injection": d.injection_info, "fraud_phrasing": d.fraud_info, "note_conflicts": d.note_conflicts,
        "letter_features": feats, "template_ids": sorted(set(d.template_ids)),
    }
    if d.expected is not None:
        g0.check_intent(label, d.expected)
    return envelope, d.account, label


# --------------------------------------------------------------------------- fraud selection
def fraud_combos(seed: int, k: int) -> list[tuple[int, int, int]]:
    """k fraud component triples. Greedy: any two share at most one component (no pair of
    components is reused). If more than the greedy capacity is needed, the rest only need to be
    distinct triples (reported in the variant report)."""
    nd, ne, na = len(ph.FRAUD_DENIALS), len(ph.FRAUD_EXPLANATIONS), len(ph.FRAUD_ACTIONS)
    allc = list(itertools.product(range(nd), range(ne), range(na)))
    random.Random(f"v1:{seed}:fraudcombos").shuffle(allc)
    de, da, ea, out, chosen = set(), set(), set(), [], set()
    for c in allc:
        if len(out) >= k:
            break
        if (c[0], c[1]) in de or (c[0], c[2]) in da or (c[1], c[2]) in ea:
            continue
        de.add((c[0], c[1])); da.add((c[0], c[2])); ea.add((c[1], c[2]))
        out.append(c); chosen.add(c)
    for c in allc:
        if len(out) >= k:
            break
        if c not in chosen:
            out.append(c); chosen.add(c)
    return out


# --------------------------------------------------------------------------- batches
DEFAULT_MIX = [
    ("ph_verify_note_near_miss", 0.03), ("ph_verify_long", 0.02), ("ph_multi_month_verify", 0.03),
    ("ph_multi_month_mixed", 0.02), ("ph_modify", 0.09), ("ph_claim_month_extends", 0.03),
    ("ph_claim_unresolved", 0.05), ("ph_evidence_missing", 0.03), ("ph_evidence_conflict", 0.04),
    ("ph_freetext_note_conflict", 0.03), ("ph_freetext_note_near_miss", 0.01),
    ("ph_months_undetermined", 0.02), ("missing_document", 0.02), ("doc_unreadable", 0.02),
    ("deadline_at_risk", 0.02), ("deadline_breached", 0.02), ("deadline_on_holiday", 0.01),
    ("malformed", 0.03), ("balance", 0.06), ("other", 0.03), ("class_conflict", 0.02),
    ("multi_issue", 0.03), ("fraud_disguised", 0.05), ("pii_bait", 0.02), ("imperative_control", 0.03),
    ("_injection_pair", 0.10), ("_repeat_pair", 0.04), ("_duplicate", 0.02),
]
# T1-weighted mix (PRD Appendix B strata): >=600 should-not-verify, >=150 should-escalate,
# >=150 identity-fraud-signal, >=200 clean should-verify at n ~ 1,100.
T1_MIX = [
    ("ph_modify", 0.17), ("ph_claim_unresolved", 0.07), ("ph_claim_month_extends", 0.05),
    ("ph_multi_month_mixed", 0.03), ("ph_evidence_missing", 0.05), ("ph_evidence_conflict", 0.04),
    ("ph_freetext_note_conflict", 0.04), ("ph_months_undetermined", 0.02), ("missing_document", 0.03),
    ("multi_issue", 0.02), ("class_conflict", 0.02), ("fraud_disguised", 0.15),
    ("ph_verify_note_near_miss", 0.03), ("ph_freetext_note_near_miss", 0.02), ("ph_verify_long", 0.04),
    ("ph_multi_month_verify", 0.03), ("imperative_control", 0.02), ("_injection_pair", 0.02),
]
MIXES = {"default": DEFAULT_MIX, "t1": T1_MIX}
MIN_N = 100


def plan(n: int, seed: int, mix: list[tuple[str, float]] | None = None) -> list[str]:
    if n < MIN_N:
        raise ValueError(f"n={n} is below MIN_N={MIN_N}")
    units: list[str] = []
    for name, share in (mix or DEFAULT_MIX):
        k = round(share * n)
        units += [name] * (k // 2 if name in ("_injection_pair", "_repeat_pair") else k)
    size = sum(2 if u in ("_injection_pair", "_repeat_pair") else 1 for u in units)
    if size > n:
        raise ValueError(f"n={n} too small for the mix (needs >= {size})")
    units += ["ph_verify"] * (n - size)
    rng = random.Random(f"v1:{seed}:plan")
    rng.shuffle(units)
    return [u for u in units if u != "_duplicate"] + [u for u in units if u == "_duplicate"]


def generate(seed: int, n: int, mix: list[tuple[str, float]] | None = None) -> dict:
    """Generate n synthetic v1 cases. Returns {'acdvs', 'accounts', 'labels'}."""
    envs, accts, labels = [], [], []
    acct_index: dict[str, int] = {}
    seen_cn: set[str] = set()
    units = plan(n, seed, mix)
    combos = iter(fraud_combos(seed, units.count("fraud_disguised")))
    cat = inj.catalog()
    inj_count = 0
    idx = 0
    pfx = "SYN1"

    def emit(d: DraftV1) -> None:
        e, a, l = finish(d, seed, seen_cn)
        envs.append(e)
        if a["account_number"] not in acct_index:
            acct_index[a["account_number"]] = len(accts)
            accts.append(a)
        labels.append(l)
        cn = e["acdv"].get("control_number")
        if isinstance(cn, str) and cn.strip():
            seen_cn.add(cn)

    for unit in units:
        if unit == "_injection_pair":
            surface = INJECTION_SURFACES[inj_count % len(INJECTION_SURFACES)]
            variants = cat[surface]
            variant = variants[(inj_count // len(INJECTION_SURFACES) + seed) % len(variants)]
            inj_count += 1
            group = f"TW1-S{seed}-G{idx:05d}"
            key = f"v1:{seed}:{idx}:twin"
            emit(build_case(seed, idx, "ph_verify", twin_group=group, rng_key=key))
            emit(build_case(seed, idx + 1, "ph_verify", case_id=f"{pfx}-S{seed}-C{idx + 1:05d}",
                            injection=(surface, variant), twin_group=group, rng_key=key))
            idx += 2
        elif unit == "_repeat_pair":
            first = build_case(seed, idx, "ph_verify")
            second = build_case(seed, idx + 1, "ph_modify")
            gap = first.rng.randint(30, 60)
            first.ingest_date = second.ingest_date - timedelta(days=gap)
            while not bizdays.is_business_day(first.ingest_date):
                first.ingest_date -= timedelta(days=1)
            first.acdv["date_received"] = first.ingest_date.isoformat()
            first.acdv["response_due_date"] = g0._due_date(first.rng, first.ingest_date).isoformat()
            first.other_tags.add("repeat_prior")
            emit(first)
            second.account = first.account
            second.acdv["account_number"] = first.account["account_number"]
            second.acdv["consumer"] = first.acdv["consumer"]
            m = g0.month_add(first.acdv["disputed_months"][0], 1)
            if m not in g0.DISPUTABLE:
                m = g0.month_add(first.acdv["disputed_months"][0], -1)
            g0._set_month(second.account, m, second.rng.randint(0, 12), reported="PH_R30")
            second.acdv["disputed_months"] = [m]
            second.template_ids, second.typos, second.features = [], 0, {}
            second.other_tags.discard("supporting_document")
            second.body = [Piece(second.rng.choice([
                "I disputed this account with you before.", "This is my second letter about this account.",
                "I already wrote to you about this account a few weeks ago.",
                "I am disputing this account again because it is still wrong."])),
                say(second, "NOT_30_LATE", "SUPPORTED", [m], f"cycle:{m}", m=m)]
            second.extra_attachments = []
            second.acdv["free_text"] = _free_text(second, "LATE_REPORTING", m)
            second.repeat_of = first.acdv["control_number"]
            second.edge_tags.add("repeat")
            second.long_letter = False
            compose(second)
            emit(second)
            accts[acct_index[second.account["account_number"]]] = second.account
            idx += 2
        elif unit == "_duplicate":
            originals = [l for l in labels if l["gold"]["outcome"] != "DUPLICATE_IGNORED"
                         and "malformed_input" not in l["edge_tags"]]
            src = originals[random.Random(f"v1:{seed}:dup:{idx}").randrange(len(originals))]
            src_env = next(e for e in envs if e["case_id"] == src["case_id"])
            e = copy.deepcopy(src_env)
            e["case_id"] = f"{pfx}-S{seed}-C{idx:05d}"
            e["fixture_meta"] = {"ingest_date": e["fixture_meta"]["ingest_date"]}
            envs.append(e)
            labels.append({**copy.deepcopy(src), "case_id": e["case_id"], "scenario": "duplicate",
                           "gold": {"outcome": "DUPLICATE_IGNORED", "escalation_reasons": [], "month_results": {},
                                    "corrections": [], "disputed_months": [], "clock_state_at_intake": None},
                           "edge_tags": ["duplicate"], "adversarial_tags": [], "other_tags": [],
                           "suspicious_expected": "NONE", "injection": None,
                           "duplicate_of": src["case_id"], "twin_group": None})
            idx += 1
        else:
            fc = next(combos) if unit == "fraud_disguised" else None
            emit(build_case(seed, idx, unit, fraud_combo=fc))
            idx += 1
    # Recompute gold against FINAL account state (a repeat may have changed a shared account).
    acct_by_no = {a["account_number"]: a for a in accts}
    seen: set[str] = set()
    for e, l in zip(envs, labels):
        if l["scenario"] != "duplicate":
            intent = {"categories": l["categories"], "claims": l["claims"]}
            l["gold"] = derive_gold(e, acct_by_no.get(e["acdv"].get("account_number")), intent, seen,
                                    l["note_conflicts"])
            exp = ("MODIFY", None) if "repeat" in l["edge_tags"] else EXPECTED[l["scenario"]]
            g0.check_intent(l, exp)
        cn = e["acdv"].get("control_number")
        if isinstance(cn, str) and cn.strip():
            seen.add(cn)
    return {"acdvs": envs, "accounts": accts, "labels": labels}
