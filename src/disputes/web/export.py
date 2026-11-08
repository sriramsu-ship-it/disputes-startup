"""R-22 case export (JSON + print-friendly HTML from the same dict). OWNER: web agent.

Contents: the dispute as received; the timeline against the deadline; the evidence list with hashes
and content; attachments with hashes and extracted text; the per-month comparison; claims, quotes
and findings (system and human); every draft version with sentence sources; reviewer decisions and
reasons; packages; model / prompt / rules / template versions; reference-table versions and
`verified` status; the hash-chain status from `disputes.audit.verify.verify_case` (platform-core;
"verification unavailable" if verification itself raises).

Attachments' original bytes are not stored by the synthetic fixtures (extracted text only), so the
"zip bundle beside the export" is represented by the attachment list with hashes (see notes).

`masked=True` (client portal) masks names, SSN-like strings and account numbers to last 4 in every
string (R-27); hashes still refer to the unmasked originals.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from disputes import reference
from disputes.audit.chain import canonical, sha256_hex
from disputes.audit.verify import verify_case
from disputes.db import repo
from disputes.domain import ArtifactKind, to_jsonable
from disputes.web import casedata as cd
from disputes.web.pii import mask_account, mask_deep

EXPORT_SCHEMA_VERSION = "web-export-1"


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
                         "extracted_text": a["extracted_text"]} for a in b.attachments],
        "comparison": b.get(ArtifactKind.COMPARISON) or [],
        "claims": cd.effective_claims(b, w),
        "decision": b.get(ArtifactKind.DECISION),
        "drafts": [{"version": r["version"], "created_by": r["created_by"], "created_at": r["created_at"],
                    "sha256": r["data_sha256"], **r["data"]} for r in b.drafts],
        "reviews": [{"version": r["version"], "created_at": r["created_at"], "sha256": r["data_sha256"], **r["data"]}
                    for r in b.reviews],
        "packages": [{"version": r["version"], "created_at": r["created_at"], "sha256": r["data_sha256"],
                      **r["data"]} for r in b.packages],
        "versions": cd.versions_for_case(conn, b),
        "reference_tables": _ref_versions(),
        "hash_chain": chain_status(conn, tenant_id=tenant_id, case_id=case_id),
    }
    out = to_jsonable(out)
    if masked:
        names = [n for n in (dispute.get("consumer_name"),) if n]
        names += [p for n in names for p in n.split() if len(p) > 2]
        out = mask_deep(out, names)
        out["case"]["account_number"] = mask_account(case.get("account_number"))
    out["content_sha256"] = sha256_hex(canonical({k: v for k, v in out.items() if k != "generated_at"}))
    out["generation_seconds"] = round(time.perf_counter() - t0, 3)
    return out
