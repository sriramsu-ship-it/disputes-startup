"""R-22 case export (JSON, HTML, PDF, zip bundle from the same dict). OWNER: package agent (was web).

Contents: a case `summary` (page 1, R-53: what was disputed, what we looked at, what we decided,
why, who decided, when, can the record be trusted), then the detail: the dispute as received; the
timeline against the deadline; evidence with hashes and content; attachments with hashes and
extracted text; the per-month comparison; claims, quotes and findings (system and human); every
draft version with sentence sources; reviewer decisions and reasons; packages and their recomputed
integrity; model / prompt / rules / template versions; reference-table versions and `verified`
status; the hash-chain status from `disputes.audit.verify.verify_case`.

Audiences
- `masked=False` (staff, AUDITOR): the full record, unmasked (the audit store is not masked, R-27).
- `masked=True` (client portal, R-39/R-41): account numbers and SSN-shaped strings masked to the last
  4, the consumer's name to initials; analysts appear by staff ID and role only (names are a contract
  decision, Q16); audit-event payloads are omitted (event IDs, types, actors and hashes stay, so the
  chain status is still meaningful); suspicious-content pattern IDs and excerpts are reduced to a
  level and a count. Hash values are never masked and refer to the unmasked originals.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from disputes import reference
from disputes.audit.chain import canonical, sha256_hex
from disputes.audit.verify import verify_case
from disputes.db import repo
from disputes.domain import ArtifactKind, to_jsonable
from disputes.package import model as pm
from disputes.web import casedata as cd
from disputes.web.pii import mask_account, mask_text

EXPORT_SCHEMA_VERSION = "web-export-2"
LIMITATIONS = (
    "SYNTHETIC DEMONSTRATION: no real consumer, account, furnisher or bureau. Nothing was sent anywhere.",
    "The response package uses a placeholder schema that has not been validated against the e-OSCAR ACDV "
    "response format or the Metro 2 format (U6). Payment-rating values and dispute codes are invented placeholders.",
    "Reference tables marked verified=false are placeholders and must be replaced before any real use (R-35).",
    "Original attachment files are not stored by this demo; the record holds each attachment's hash as received "
    "and its extracted text.",
    "Deadlines are shown in calendar days; the business-day calendar used for ACDV due dates is unverified (U21).",
    "This record is not legal advice and has not been reviewed by counsel or an examiner.",
)
CLIENT_REDACTIONS = (
    "Account numbers and SSN-shaped values masked to the last 4; the consumer's name reduced to initials.",
    "Analysts are shown by staff ID and role; names withheld pending the service contract (Q16).",
    "Audit-event payloads omitted; event IDs, types, actors, payload hashes and chain hashes retained.",
    "Suspicious-content pattern IDs and excerpts reduced to a level and a count.",
)


def chain_status(conn, *, tenant_id: str, case_id: str) -> dict:
    try:
        r = dict(verify_case(conn, tenant_id=tenant_id, case_id=case_id))
    except Exception as e:  # noqa: BLE001 - an export must still be produced; the status says why
        return {"ok": None, "status": "verification unavailable", "detail": f"{type(e).__name__}: {e}"}
    r["status"] = "verified" if r.get("ok") else "BROKEN"
    return r


def _ref_versions() -> dict:
    try:
        return reference.versions()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"reference tables unavailable: {e}"}


def _mask(obj, names: tuple[str, ...], key: str = ""):
    """mask_text on every string except hash-valued keys (hashes must stay verifiable)."""
    if isinstance(obj, str):
        return obj if pm.is_hash_key(key) else mask_text(obj, names)
    if isinstance(obj, dict):
        return {k: _mask(v, names, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_mask(v, names, key) for v in obj]
    return obj


def _staff_ref(user_id, role) -> str:
    return f"staff {user_id} ({role})" if user_id else "staff (unknown)"


def _client_view(out: dict) -> dict:
    out["timeline"] = [{k: v for k, v in e.items() if k != "payload"} | {"payload": "omitted in client copy"}
                       for e in out["timeline"]]
    out["reviews"] = [{**r, "actor_name": _staff_ref(r.get("actor_id"), r.get("actor_role"))} for r in out["reviews"]]
    pk = []
    for p in out["packages"]:
        appr = [{**a, "display_name": _staff_ref(a.get("user_id"), a.get("role"))} for a in p.get("approvals") or []]
        final = appr[-1] if appr else {}
        pk.append({**p, "approvals": appr,
                   "dfAuthorizedName": f"[withheld in client copy: {_staff_ref(final.get('user_id'), final.get('role'))}]"})
    out["packages"] = pk
    s = out.get("suspicion") or {}
    if s:
        out["suspicion"] = {"level": s.get("level"), "patterns_version": s.get("patterns_version"),
                            "matches": len(s.get("matches") or []), "detail": "pattern IDs omitted in client copy"}
    out["summary"]["who"] = [{**w, "actor_name": _staff_ref(w.get("actor_id"), w.get("actor_role"))}
                             for w in out["summary"]["who"]]
    if out["summary"].get("authorized_name"):
        out["summary"]["authorized_name"] = pk[-1]["dfAuthorizedName"] if pk else None
    return out


def anchor_status(events: list[dict]) -> dict:
    """Latest external anchor of the global log (R-21) and whether it covers this case's last event.
    Reported, not re-verified here (`disputes.cli verify` checks anchors against the log)."""
    try:
        from disputes.audit.anchor import latest_anchor
        from disputes.config import settings
        a = latest_anchor(settings().anchor_dir)
    except Exception as e:  # noqa: BLE001 - the export must still be produced
        return {"at": None, "detail": f"anchor store unavailable: {type(e).__name__}"}
    if a is None:
        return {"at": None, "detail": "no anchor written yet"}
    last = max((e["event_id"] for e in events), default=0)
    return {"at": a.get("at"), "global_head_event_id": a.get("global_head_event_id"),
            "covers_case": int(a.get("global_head_event_id") or 0) >= last > 0, "detail": "reported, not re-verified"}


def build_export(conn, *, tenant_id: str, case_id: str, masked: bool = False) -> dict:
    t0 = time.perf_counter()
    b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id)
    case = b.case
    events = repo.audit_events_for_case(conn, tenant_id=tenant_id, case_id=case_id)
    w = cd.working_state(b)
    dispute = b.get(ArtifactKind.DISPUTE) or {}
    out = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic": bool(case.get("synthetic")),
        "masked": masked,
        "audience": "client" if masked else "staff",
        "limitations": list(LIMITATIONS),
        "redactions": list(CLIENT_REDACTIONS) if masked else [],
        "case": {k: case.get(k) for k in ("case_id", "tenant_id", "channel", "control_number", "cra",
                                          "account_number", "account_last4", "date_received", "response_due_date",
                                          "internal_target_date", "clock_state", "state", "categories",
                                          "escalation_reasons", "proposed_outcome", "final_outcome",
                                          "suspicion_level", "priority", "repeat_of_case_id", "raw_payload_sha256",
                                          "created_at", "updated_at")},
        "dispute_as_received": dispute,
        "deadline": {"date_received": case.get("date_received"), "internal_target_date":
                     case.get("internal_target_date"), "response_due_date": case.get("response_due_date"),
                     "clock_state": case.get("clock_state"), "clock": (b.get(ArtifactKind.INTAKE) or {}).get("clock")},
        "timeline": [{"event_id": e["event_id"], "occurred_at": e["occurred_at"], "event_type": e["event_type"],
                      "actor_type": e["actor_type"], "actor_id": e["actor_id"], "actor_role": e["actor_role"],
                      "payload": e["payload"], "payload_sha256": e["payload_sha256"], "case_hash": e["case_hash"]}
                     for e in events],
        "intake": b.get(ArtifactKind.INTAKE), "suspicion": b.get(ArtifactKind.SUSPICION),
        "classification": b.get(ArtifactKind.CLASSIFICATION),
        "evidence": b.evidence,
        "attachments": [{"attachment_id": a["attachment_id"], "file_name": a["file_name"],
                         "media_type": a["media_type"], "page_count": a["page_count"], "sha256": a["sha256"],
                         "extracted_text": a["extracted_text"],
                         "extracted_text_sha256": sha256_hex(a["extracted_text"] or ""),
                         "original_stored": False} for a in b.attachments],
        "comparison": b.get(ArtifactKind.COMPARISON) or [],
        "claims": cd.effective_claims(b, w),
        "decision": b.get(ArtifactKind.DECISION),
        "drafts": [{"version": r["version"], "created_by": r["created_by"], "created_at": r["created_at"],
                    "sha256": r["data_sha256"], **r["data"]} for r in b.drafts],
        "reviews": [{"version": r["version"], "created_at": r["created_at"], "sha256": r["data_sha256"], **r["data"]}
                    for r in b.reviews],
        "packages": [{"version": r["version"], "created_at": r["created_at"], "sha256": r["data_sha256"],
                      **r["data"]} for r in b.packages],
        "package_integrity": [{"version": r["data"].get("package_version"), **pm.package_integrity(r, events)}
                              for r in b.packages],
        "versions": cd.versions_for_case(conn, b),
        "reference_tables": _ref_versions(),
        "hash_chain": chain_status(conn, tenant_id=tenant_id, case_id=case_id),
        "anchor": anchor_status(events),
    }
    out = to_jsonable(out)
    out["summary"] = pm.export_summary(out)
    if masked:
        out = _client_view(out)
        names = [n for n in (dispute.get("consumer_name"),) if n]
        names += [p for n in names for p in n.split() if len(p) > 2]
        out = _mask(out, tuple(names))
        out["case"]["account_number"] = mask_account(case.get("account_number"))
    out["content_sha256"] = sha256_hex(canonical({k: v for k, v in out.items() if k != "generated_at"}))
    out["generation_seconds"] = round(time.perf_counter() - t0, 3)
    return out
