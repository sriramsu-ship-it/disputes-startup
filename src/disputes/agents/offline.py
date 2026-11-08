"""Offline heuristic backend: one handler per prompt template. Deterministic, no network.

These are transparent keyword / date / sentence rules standing in for the model so the pipeline
runs in CI and demos. They read ONLY the `data` the real model would receive. They must never
import synthgen or read labels (test-enforced). Their agreement with generator labels is NOT a
measure of the product's model quality: the heuristics were written by someone who has seen the
generator's letter styles, so the numbers are optimistic for that distribution and say nothing
about real letters.
"""
from __future__ import annotations

import re
from datetime import date

from disputes.agents.text import month_label, normalise, parse_months, sentences, words

# ----------------------------------------------------------------------------- suspicious text
_SUSPICIOUS = [
    ("role_marker", re.compile(r"(^|[\s.;:!?])(system|assistant|developer)\s*:", re.I)),
    ("override", re.compile(r"\b(ignore|disregard|forget|override)\b[\w\s,]{0,40}\b(instruction|instructions|prompt|rules)\b", re.I)),
    ("role_change", re.compile(r"\byou are now\b|\bnew instructions\b|\bact as\b", re.I)),
    ("tool_syntax", re.compile(r"\{\s*\"(tool|function|name|arguments|action)\"\s*:", re.I)),
    ("dictated_result", re.compile(r"\b(mark|report|respond|set)\b[\w\s]{0,30}\b(deleted|delete|verified|paid as agreed)\b", re.I)),
]


def suspicious_reason(text: str) -> str | None:
    t = (text or "").replace("_", " ")
    for name, rx in _SUSPICIOUS:
        if rx.search(t):
            return name
    return None


# ----------------------------------------------------------------------------- classification
_FRAUD = re.compile(
    r"identity theft|identity fraud|stolen identity|not my account|not mine\b|isn't mine|never opened|"
    r"do not recogni[sz]e|don't recogni[sz]e|never done business|someone used my|somebody used my|"
    r"opened (this|it|the account)? ?in my name|without my (permission|consent|knowledge)|"
    r"fraudulent(ly)? (account|opened)|none of these payments are mine", re.I)
_PH = re.compile(
    r"\blate\b|on time|payment history|past due|days late|\bbehind\b|\bpaid\b|\bpayments?\b|"
    r"\binstall?ments?\b|deferr?al|forbearance|hardship|\bdelinquen", re.I)
_BAL_STRICT = re.compile(
    r"\bbalance (of \$[\d,.]+ )?(is|was|should|shows|of \$[\d,.]+ is)\b.*\b(too high|wrong|incorrect|not|should)\b|"
    r"\bbalance should be\b|\b(i|we) (do not|don't) owe\b|\bowe (only|nothing|less)\b|"
    r"\b(amount|balance) (you )?(report|reported|show|shown)\b.*\b(wrong|incorrect|too high)\b", re.I)
_BAL_LOOSE = re.compile(r"\bbalance\b|\bamount owed\b", re.I)
_STATUS = re.compile(r"\b(should (be|show) (as )?(closed|open|paid in full)|charged? off|account status|"
                     r"(was|is) closed\b|paid in full|settled)\b", re.I)
_OTHER = re.compile(r"\baddress\b|date of birth|\bname is (wrong|misspelled|incorrect)|"
                    r"\bspelled\b|date opened|\bemployer\b", re.I)


def _units(doc_text: str) -> list[str]:
    return [doc_text[s:e] for s, e, _ in sentences(doc_text)]


def classify(data: dict) -> dict:
    cats: set[str] = set()
    flags: list[str] = []
    texts: list[tuple[str, bool]] = []      # (sentence, is_bureau_free_text)
    for u in _units(data.get("bureau_free_text") or ""):
        texts.append((u, True))
    for d in data.get("documents") or []:
        r = suspicious_reason(d.get("file_name", "")) or suspicious_reason(_meta_text(d))
        if r:
            flags.append(f"{d.get('source_id')}: {r} in file name or metadata")
        for u in _units(d.get("text") or ""):
            texts.append((u, False))
    fraud = False
    for u, is_ft in texts:
        r = suspicious_reason(u)
        if r:
            flags.append(r)
            continue                            # instructions are data to report, not content to classify
        if _FRAUD.search(u):
            fraud = True
        if _PH.search(u) and not _is_statement_row(u):
            cats.add("PAYMENT_HISTORY")
        if (_BAL_LOOSE if is_ft else _BAL_STRICT).search(u):
            cats.add("BALANCE")
        if _STATUS.search(u):
            cats.add("ACCOUNT_STATUS")
        if _OTHER.search(u):
            cats.add("OTHER")
    if fraud:
        out_cats = ["IDENTITY_FRAUD"]
        conf = 0.8
    elif cats:
        out_cats = sorted(cats)
        conf = 0.75 if len(cats) == 1 else 0.6
    else:
        out_cats = ["UNCERTAIN"]
        conf = 0.3
    return {
        "categories": out_cats,
        "confidence": conf,
        "rationale": "offline keyword heuristics over the free text and documents",
        "suspicious_content": bool(flags),
        "suspicious_reason": "; ".join(sorted(set(flags)))[:200],
    }


def _meta_text(d: dict) -> str:
    md = d.get("metadata") or {}
    return " ".join(str(v) for v in md.values()) if isinstance(md, dict) else str(md)


_ROW = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s{2,}|\s{2,}-?\$[\d,]+\.\d\d\s*$")


def _is_statement_row(u: str) -> bool:
    return bool(_ROW.search(u))


# ----------------------------------------------------------------------------- claim extraction
_NOT_CLAIM_START = re.compile(
    r"^(to whom|dear|hello|hi\b|my name is|sincerely|regards|yours|thank|please|i ask|i am writing|"
    r"i'm writing|kindly|could you|can you|would you|while you are at it|for identification|you can also)", re.I)
_CLAIM_KW = re.compile(
    r"\bpaid\b|\bpay(ment|ments)?\b|\binstall?ments?\b|\blate\b|on time|\bbehind\b|past due|"
    r"\bbalance\b|\$\d|\bowe\b|deferr?al|forbearance|hardship|\bplan\b|\bagree(d|ment)?\b|representative|"
    r"told me|promised|not my account|never opened|recogni[sz]e|identity|in my name|someone used|"
    r"somebody|closed|charged? off|settled", re.I)
_AGREE = re.compile(r"deferr?al|forbearance|hardship|\bplan\b|\bagree(d|ment)\b|representative|told me|promised|waive", re.I)
_AMOUNT = re.compile(r"\$\s?\d|\bbalance\b|\bowe\b", re.I)
_STATUS_CLAIM = re.compile(r"never\s+(once\s+)?(been\s+)?late|not my account|never opened|recogni[sz]e|"
                           r"in my name|someone used|somebody|identity|closed|charged? off|settled", re.I)


def _claim_type(s: str, months: list[str]) -> str:
    if _FRAUD.search(s):
        return "ACCOUNT_STATUS"
    if _AGREE.search(s):
        return "AGREEMENT"
    if _AMOUNT.search(s) and not re.search(r"\blate\b|on time|behind", s, re.I):
        return "AMOUNT"
    if months and re.search(r"\bpaid\b|\bpay|install?ment|\blate\b|on time|behind|past due|statement", s, re.I):
        return "PAYMENT_EVENT"
    if _STATUS_CLAIM.search(s) or re.search(r"\blate\b", s, re.I):
        return "ACCOUNT_STATUS"
    if months:
        return "DATE"
    return "PAYMENT_EVENT"


def extract_claims(data: dict) -> dict:
    claims = []
    flags = []
    for d in data.get("documents") or []:
        sid = d.get("source_id")
        text = d.get("text") or ""
        if d.get("kind") == "bureau_free_text" and not re.search(r"\b(i|my|me)\b", text, re.I):
            continue    # bureau summary codes ("CONSUMER DISPUTES ...") restate the dispute, not a first-person claim
        units = []
        for s, e, line in sentences(text):
            u = text[s:e]
            r = suspicious_reason(u)
            if r:
                flags.append(f"{sid}: {r}")
                continue
            if _NOT_CLAIM_START.match(normalise(u)) or "SYNTHETIC TEST" in u or _is_statement_row(u):
                continue
            if not _CLAIM_KW.search(u):
                continue
            months = parse_months(u)
            units.append({"s": s, "e": e, "line": line, "months": months, "type": _claim_type(u, months)})
        merged = []
        for u in units:   # continuation: same line, no month of its own, same type -> one claim
            p = merged[-1] if merged else None
            if p and p["line"] == u["line"] and not u["months"] and p["type"] == u["type"]:
                p["e"] = u["e"]
            else:
                merged.append(dict(u))
        for u in merged:
            q = text[u["s"]:u["e"]]
            claims.append({"text": q, "quote": q, "source_id": sid, "claim_type": u["type"],
                           "months": u["months"]})
    return {"claims": claims, "suspicious_content": bool(flags),
            "suspicious_reason": "; ".join(sorted(set(flags)))[:200]}


# ----------------------------------------------------------------------------- claim mapping
_ON_TIME = re.compile(r"on time|never\s+(once\s+)?(been\s+)?(\d+\s+days\s+)?late|before the due date|cleared before|"
                      r"\bpaid\b|not late|was never|early", re.I)
_ONE_BEHIND = re.compile(r"\bone payment behind\b|only (30|thirty) days|one month behind|only one (payment|month)", re.I)
_ENCLOSURE = re.compile(r"\b(enclosed|attached|attach|enclose|see the|included)\b", re.I)
_PLAN_NOTE_TYPES = {"HARDSHIP", "DEFERRAL", "FORBEARANCE"}
_FT_CONFLICT = re.compile(r"hardship|deferr?al|forbearance|payment plan|promise|waive|courtesy|do not report|"
                          r"don't report|reported in error|in error|agreed|skip[- ]a[- ]pay", re.I)


def _dpd(content: dict):
    for k in ("dpd_at_cycle", "dpd", "days_past_due"):
        if isinstance(content.get(k), int):
            return content[k]
    return None


def _cycle_month(ev: dict) -> str | None:
    c = ev.get("content") or {}
    m = c.get("cycle_month") or c.get("month")
    if m:
        return m
    mm = re.fullmatch(r"EV-CYCLE-(\d{4}-\d{2})", ev.get("evidence_id", ""))
    return mm.group(1) if mm else None


def _month_bounds(m: str) -> tuple[date, date]:
    y, mm = int(m[:4]), int(m[5:7])
    first = date(y, mm, 1)
    nxt = date(y + (mm == 12), 1 if mm == 12 else mm + 1, 1)
    return first, date.fromordinal(nxt.toordinal() - 1)


def _note_overlaps(content: dict, month: str) -> bool:
    try:
        s = date.fromisoformat(str(content.get("start_date") or content.get("start")))
        e = date.fromisoformat(str(content.get("end_date") or content.get("end")))
    except ValueError:
        return False
    first, last = _month_bounds(month)
    return s <= last and e >= first


def _ev_kind(ev: dict) -> str:
    k = ev.get("kind") or ""
    eid = ev.get("evidence_id", "")
    if k:
        return k
    for pfx, kind in (("EV-CYCLE-", "cycle"), ("EV-NOTE-", "note"), ("EV-FTNOTE-", "free_text_note"),
                      ("EV-ATT-", "attachment"), ("EV-ACDV", "acdv"), ("EV-ACCOUNT", "account")):
        if eid.startswith(pfx):
            return kind
    return ""


def map_claims(data: dict) -> dict:
    ev = data.get("evidence") or []
    cycles = {}
    for e in ev:
        if _ev_kind(e) == "cycle":
            m = _cycle_month(e)
            if m:
                cycles[m] = e
    notes = [e for e in ev if _ev_kind(e) == "note"]
    ftnotes = [e for e in ev if _ev_kind(e) == "free_text_note"]
    atts = [e for e in ev if _ev_kind(e) == "attachment"]
    mappings = []
    for c in data.get("claims") or []:
        mappings.append(_map_one(c, cycles, notes, atts))
    conflict = [e["evidence_id"] for e in ftnotes
                if _FT_CONFLICT.search(str((e.get("content") or {}).get("text", "")))]
    return {"mappings": mappings, "note_conflict": bool(conflict),
            "note_conflict_reason": ", ".join(conflict)}


def _readable_other_attachment(atts, source_id) -> list[str]:
    out = []
    for a in atts:
        c = a.get("content") or {}
        aid = c.get("attachment_id") or a["evidence_id"].removeprefix("EV-ATT-")
        text = c.get("extracted_text") or c.get("text") or ""
        if aid != source_id and len(text.strip()) > 0:
            out.append(a["evidence_id"])
    return out


def _map_one(c: dict, cycles: dict, notes: list, atts: list) -> dict:
    cid = c.get("claim_id")
    q = c.get("quote") or c.get("text") or ""
    ctype = c.get("claim_type")
    months = [m for m in (c.get("months") or []) if isinstance(m, str)]

    def na(reason):
        return {"claim_id": cid, "finding": "NOT_ADDRESSABLE", "evidence_ids": [], "reason": reason}

    if _FRAUD.search(q):
        return na("An identity-theft assertion cannot be settled from the payment records.")
    if ctype == "AMOUNT":
        return na("Balance and amount claims are not compared with the records in this release.")
    if ctype == "AGREEMENT":
        if re.search(r"deferr?al|forbearance|hardship|plan", q, re.I):
            for m in months:
                hits = [n["evidence_id"] for n in notes
                        if str((n.get("content") or {}).get("type") or (n.get("content") or {}).get("note_type")
                               ).upper() in _PLAN_NOTE_TYPES and _note_overlaps(n.get("content") or {}, m)]
                if hits:
                    return {"claim_id": cid, "finding": "SUPPORTED", "evidence_ids": hits,
                            "reason": f"An account note records an arrangement covering {month_label(m)}."}
        return na("No call record or arrangement note in the evidence covers this.")
    if _ENCLOSURE.search(q) and re.search(r"statement|receipt|letter|record|proof|confirmation", q, re.I):
        if not _readable_other_attachment(atts, c.get("source_id")):
            return na("The document the consumer refers to is not among the readable attachments.")
    one_behind = bool(_ONE_BEHIND.search(q))
    on_time = bool(_ON_TIME.search(q)) and not one_behind
    if months:
        threshold = 60 if one_behind else 30
        ids_sup, ids_con, missing = [], [], []
        for m in months:
            e = cycles.get(m)
            dpd = _dpd((e or {}).get("content") or {}) if e else None
            if dpd is None:
                missing.append(m)
            elif dpd < threshold:
                ids_sup.append(e["evidence_id"])
            else:
                ids_con.append(e["evidence_id"])
        if missing:
            return na(f"No cycle record for {', '.join(missing)} in the evidence.")
        if not (on_time or one_behind):
            return na("The claim does not state a payment timing that a cycle record can settle.")
        if ids_con:
            return {"claim_id": cid, "finding": "CONTRADICTED", "evidence_ids": ids_con,
                    "reason": "The cycle record shows the payment past due at the cycle date."}
        return {"claim_id": cid, "finding": "SUPPORTED", "evidence_ids": ids_sup,
                "reason": "The cycle record shows the payment within the claimed lateness."}
    # no month: a general "never late" claim is checked against every cycle in evidence
    general = re.search(r"never\s+(once\s+)?(been\s+)?(\d+\s+days\s+)?late|always (paid|on time)", q, re.I)
    if general and not cycles:
        return na("No cycle records are in the evidence.")
    if general:
        late = [e["evidence_id"] for m, e in sorted(cycles.items())
                if (_dpd(e.get("content") or {}) or 0) >= 30]
        if late:
            return {"claim_id": cid, "finding": "CONTRADICTED", "evidence_ids": late,
                    "reason": "At least one cycle record shows the account 30 or more days past due."}
        return {"claim_id": cid, "finding": "SUPPORTED", "evidence_ids": [e["evidence_id"] for _, e in sorted(cycles.items())],
                "reason": "No cycle record in evidence shows the account 30 or more days past due."}
    return na("No month identified; the claim cannot be compared with any cycle record.")


# ----------------------------------------------------------------------------- draft
def _ev_index(data):
    return {e["evidence_id"]: e for e in data.get("evidence") or []}


def _fact(c: dict, evidx: dict) -> tuple[str, list[str]]:
    ids = [i for i in c.get("evidence_ids") or [] if i in evidx]
    parts = []
    for i in ids:
        con = evidx[i].get("content") or {}
        kind = _ev_kind(evidx[i])
        if kind == "cycle":
            m = _cycle_month(evidx[i])
            parts.append(f"our cycle record for {month_label(m) if m else i} shows {_dpd(con)} days past due "
                         f"and a reported rating of {con.get('reported_rating', 'none')} ({i})")
        elif kind == "note":
            parts.append(f"account note {i} records a {str(con.get('type') or con.get('note_type') or 'note').lower()} "
                         f"arrangement from {con.get('start_date')} to {con.get('end_date')}")
        else:
            parts.append(f"see {i}")
    if parts:
        if len(parts) > 2:
            parts = parts[:2] + [f"{len(parts) - 2} further cycle records ({', '.join(ids[2:])})"]
        return "; ".join(parts), ids
    reason = (c.get("reason") or "the records provided do not address it").rstrip(".")
    return f"this was not settled by the records provided: {reason[0].lower() + reason[1:]}", []


def draft(data: dict) -> dict:
    evidx = _ev_index(data)
    limit = int(data.get("word_limit") or 100)
    compact = bool(data.get("previous_errors"))
    sents = []
    for c in data.get("claims") or []:
        fact, ids = _fact(c, evidx)
        if not ids:
            src = c.get("source_id")
            fallback = f"EV-ATT-{src}" if f"EV-ATT-{src}" in evidx else ("EV-ACDV" if "EV-ACDV" in evidx else None)
            if fallback is None:
                continue
            ids = [fallback]
        quote = c.get("quote") or ""
        if compact or not quote:
            text = f"Regarding the consumer's claim {c.get('claim_id')}, {fact}."
            quotes = []
        else:
            text = f"The consumer wrote \"{quote}\"; {fact}."
            quotes = [{"source_id": c.get("source_id"), "quote": quote}]
        sents.append({"text": text[0].upper() + text[1:], "evidence_ids": ids, "quotes": quotes})
    total = sum(words(s["text"]) for s in sents)
    if total > limit and not compact:
        return draft({**data, "previous_errors": ["word limit"]})
    while sents and sum(words(s["text"]) for s in sents) > limit:
        sents.pop()   # last resort: the reviewer still sees every claim in the claim map
    return {"sentences": sents}


HANDLERS = {
    "classify": classify,
    "extract_claims": extract_claims,
    "map_claims": map_claims,
    "draft": draft,
}
