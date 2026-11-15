"""R-22 attachments bundle: one zip per case export. OWNER: package agent.

Layout
  MANIFEST.json                     every file with sha256 and size; what is and is not included
  README.txt                        plain-language description and limitations
  export.json / export.html         the R-22 export (HTML is standalone: stylesheet inlined)
  export.pdf                        when a PDF renderer is available (else listed as not included)
  packages/package-vN.json|.html    each response package version
  attachments/<id>__<name>.extracted.txt   extracted text of each attachment

Original attachment files are not stored by this demo, so they cannot be bundled; the manifest says
so and records the hash taken at intake for each original. File names from the dispute are
untrusted: they are reduced to [A-Za-z0-9._-] and truncated before use in the archive.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

from disputes.audit.chain import sha256_hex
from disputes.package import pdf as pdfmod
from disputes.package import render

BUNDLE_SCHEMA_VERSION = "export-bundle-1"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)   # zip entry timestamps fixed; the manifest carries generated_at


def safe_name(s: str, limit: int = 80) -> str:
    out = _SAFE.sub("_", str(s or "")).strip("._") or "file"
    return out[:limit]


def build_bundle(ex: dict, *, package_docs: list[dict], include_pdf: bool = True) -> bytes:
    """ex: the export dict (masked or not). package_docs: model.package_document views, already masked
    for the client copy by the caller (integrity computed on the unmasked rows)."""
    files: list[tuple[str, bytes, str]] = []
    files.append(("export.json", json.dumps(ex, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                  "R-22 export, machine-readable"))
    html = render.render_export_html(ex, standalone=True)
    files.append(("export.html", html.encode("utf-8"), "R-22 export, human-readable (open in any browser)"))
    not_included = []
    if include_pdf:
        try:
            files.append(("export.pdf", pdfmod.html_to_pdf(html), "R-22 export, PDF rendered from export.html"))
        except pdfmod.PdfUnavailable as e:
            not_included.append({"path": "export.pdf", "reason": str(e)})
    for doc in package_docs:
        v = doc["version"]
        files.append((f"packages/package-v{v}.json",
                      json.dumps(doc["pkg"], indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                      f"response package version {v} as stored"))
        files.append((f"packages/package-v{v}.html",
                      render.render_package_html(doc, masked=bool(ex.get("masked"))).encode("utf-8"),
                      f"response package version {v}, human-readable"))
    originals = []
    for a in ex.get("attachments") or []:
        name = f"attachments/{safe_name(a['attachment_id'], 20)}__{safe_name(a['file_name'])}.extracted.txt"
        files.append((name, (a.get("extracted_text") or "").encode("utf-8"),
                      f"extracted text of attachment {a['attachment_id']}"))
        originals.append({"attachment_id": a["attachment_id"], "file_name": a["file_name"],
                          "original_sha256_at_intake": a.get("sha256"), "original_included": False})
    manifest = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION, "case_id": ex["case"]["case_id"],
        "generated_at": ex.get("generated_at"), "synthetic": ex.get("synthetic"), "masked": ex.get("masked"),
        "audience": ex.get("audience"), "export_content_sha256": ex.get("content_sha256"),
        "files": [{"path": p, "sha256": sha256_hex(b), "bytes": len(b), "description": d} for p, b, d in files],
        "not_included": not_included,
        "original_attachments": originals,
        "original_attachments_note": ("Original attachment files are NOT included: this demo stores only each "
                                      "attachment's extracted text and the sha256 of the original taken at intake."),
        "limitations": ex.get("limitations") or [],
    }
    readme = "\n".join([
        f"Case record bundle for case {ex['case']['case_id']} (SYNTHETIC DEMONSTRATION).",
        "",
        "export.html   open in a browser: page 1 is the examiner summary, then the full record.",
        "export.json   the same record, machine-readable.",
        "export.pdf    the same record as PDF (when the server could render it; see MANIFEST.json).",
        "packages/     each response package version (JSON as stored, plus a readable HTML copy).",
        "attachments/  extracted text of each attachment. Original files are not stored by this demo.",
        "MANIFEST.json lists every file with its sha256.",
        "",
        *ex.get("limitations", []),
        *(["Client copy: " + r for r in ex.get("redactions") or []]),
        "",
    ])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, data in [("MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")),
                           ("README.txt", readme.encode("utf-8"))] + [(p, b) for p, b, _ in files]:
            z.writestr(zipfile.ZipInfo(path, date_time=_FIXED_TIME), data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()
