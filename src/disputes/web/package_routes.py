"""Routes for the response package document and the export's PDF and zip bundle. OWNER: package agent.

Mounted by one `include_router` line in `web/app.py`; the app passes in its own request plumbing
(`handle`, role and tenant checks) so authentication, CSRF/session handling and error pages are the
app's, unchanged. Paths deliberately do not overlap the app's `/export.{fmt}` route.

Staff (/ops, tenant access checked):       Client (/client, own tenant, completed cases only):
  /ops/t/{t}/cases/{c}/packages/{v}.html     /client/cases/{c}/packages/{v}.html
  /ops/t/{t}/cases/{c}/packages/{v}.json     /client/cases/{c}/packages/{v}.json
  /ops/t/{t}/cases/{c}/packages/{v}.pdf      /client/cases/{c}/packages/{v}.pdf
  /ops/t/{t}/cases/{c}/audit-export.pdf      /client/cases/{c}/audit-export.pdf
  /ops/t/{t}/cases/{c}/audit-export.zip      /client/cases/{c}/audit-export.zip

Reads: AUDITOR/ADMIN staff reads write CASE_READ (R-21, via metrics.record_case_read); every client
download writes a CASE_READ event via the app's `client_read` (R-39/R-41); a request for another
tenant's case answers 404 and the app's hooks write ACCESS_DENIED in the requester's scope (R-37).
"""
from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from disputes.db import repo
from disputes.domain import ArtifactKind
from disputes.package import bundle, model as pm, pdf as pdfmod, render
from disputes.web import export, metrics


# ---------------------------------------------------------------- service (no HTTP)
def client_package_copy(data: dict, names: tuple[str, ...]) -> dict:
    """The client's copy of a package: analysts by staff ID and role, account and personal data masked."""
    appr = [{**a, "display_name": export._staff_ref(a.get("user_id"), a.get("role"))} for a in data.get("approvals") or []]
    final = appr[-1] if appr else {}
    out = {**data, "approvals": appr,
           "dfAuthorizedName": f"[withheld in client copy: {export._staff_ref(final.get('user_id'), final.get('role'))}]"}
    out = export._mask(out, names)
    out["account_number"] = "••••" + str(data.get("account_last4") or str(data.get("account_number") or "")[-4:])
    return out


def package_docs(conn, *, tenant_id: str, case_id: str, masked: bool) -> list[dict]:
    case = repo.get_case(conn, tenant_id=tenant_id, case_id=case_id)
    rows = repo.artifact_history(conn, tenant_id=tenant_id, case_id=case_id, kind=ArtifactKind.PACKAGE)
    events = repo.audit_events_for_case(conn, tenant_id=tenant_id, case_id=case_id)
    names: tuple[str, ...] = ()
    if masked:
        d = repo.latest_artifact(conn, tenant_id=tenant_id, case_id=case_id, kind=ArtifactKind.DISPUTE)
        n = ((d or {}).get("data") or {}).get("consumer_name")
        names = tuple([n] + [p for p in n.split() if len(p) > 2]) if n else ()
    docs = []
    for r in rows:
        r = dict(r)
        integ = pm.package_integrity(r, events)
        if masked:
            r = {**r, "data": client_package_copy(r["data"], names)}
        docs.append(pm.package_document(r, events, case=case, integrity=integ))
    return docs


def _one(docs: list[dict], version: int) -> dict | None:
    return next((d for d in docs if d["version"] == version), None)


def _attachment(body: bytes, media: str, name: str) -> Response:
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def package_response(docs: list[dict], version: int, fmt: str, *, masked: bool, links_base: str, not_found):
    doc = _one(docs, version)
    if doc is None:
        raise not_found("No such package version.")
    cid = doc["pkg"].get("case_id")
    if fmt == "json":
        return _attachment(json.dumps(doc["pkg"], indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                           "application/json", f"case-{cid}-package-v{version}.json")
    if fmt == "html":
        links = [("Download PDF", f"{links_base}/packages/{version}.pdf"),
                 ("Download JSON", f"{links_base}/packages/{version}.json"),
                 ("Open case record", f"{links_base}/export.html")]
        return HTMLResponse(render.render_package_html(doc, masked=masked, standalone=False, links=links))
    if fmt == "pdf":
        return _attachment(pdfmod.html_to_pdf(render.render_package_html(doc, masked=masked)), "application/pdf",
                           f"case-{cid}-package-v{version}.pdf")
    raise not_found("Package format must be html, json or pdf.")


def export_file(conn, *, tenant_id: str, case_id: str, masked: bool, kind: str) -> Response:
    ex = export.build_export(conn, tenant_id=tenant_id, case_id=case_id, masked=masked)
    if kind == "pdf":
        return _attachment(pdfmod.html_to_pdf(render.render_export_html(ex)), "application/pdf",
                           f"case-{case_id}-export.pdf")
    docs = package_docs(conn, tenant_id=tenant_id, case_id=case_id, masked=masked)
    return _attachment(bundle.build_bundle(ex, package_docs=docs), "application/zip", f"case-{case_id}-export.zip")


# ---------------------------------------------------------------- HTTP
def build_router(*, handle: Callable, staff: Callable, require_tenant: Callable, client_only: Callable,
                 client_case_or_404: Callable, client_read: Callable) -> APIRouter:
    """Hooks are the app's own: require_tenant(conn, ctx, request, tenant_id) (404 + ACCESS_DENIED),
    client_case_or_404(conn, ctx, request, tenant, case_id) -> portal summary, and
    client_read(conn, ctx, tenant, case_id, surface) (R-39 CASE_READ for client downloads)."""
    from disputes.web.app import HttpError   # app module is loaded by the time routes run

    def not_found(msg):
        return HttpError(404, msg)

    def unavailable(e):
        return HttpError(503, f"PDF is not available on this server: {e}")

    r = APIRouter()

    def staff_read(conn, ctx, tenant_id, case_id, surface):
        metrics.record_case_read(conn, tenant_id=tenant_id, case_id=case_id, user_id=ctx.principal.user_id,
                                 role=ctx.principal.role.value, surface=surface)

    @r.get("/ops/t/{tenant_id}/cases/{case_id}/packages/{version}.{fmt}")
    async def ops_package(request: Request, tenant_id: str, case_id: str, version: int, fmt: str):
        def work(conn, ctx):
            staff(ctx)
            require_tenant(conn, ctx, request, tenant_id)
            docs = package_docs(conn, tenant_id=tenant_id, case_id=case_id, masked=False)
            try:
                resp = package_response(docs, version, fmt, masked=False, not_found=not_found,
                                        links_base=f"/ops/t/{tenant_id}/cases/{case_id}")
            except pdfmod.PdfUnavailable as e:
                raise unavailable(e)
            staff_read(conn, ctx, tenant_id, case_id, f"package.v{version}.{fmt}")
            return resp
        return await handle(request, work)

    @r.get("/ops/t/{tenant_id}/cases/{case_id}/audit-export.{kind}")
    async def ops_export_file(request: Request, tenant_id: str, case_id: str, kind: str):
        def work(conn, ctx):
            staff(ctx)
            require_tenant(conn, ctx, request, tenant_id)
            if kind not in ("pdf", "zip"):
                raise not_found("Export file must be pdf or zip.")
            try:
                resp = export_file(conn, tenant_id=tenant_id, case_id=case_id, masked=False, kind=kind)
            except pdfmod.PdfUnavailable as e:
                raise unavailable(e)
            staff_read(conn, ctx, tenant_id, case_id, f"export.{kind}")
            return resp
        return await handle(request, work)

    def client_case(conn, ctx, request, case_id):
        t = client_only(ctx)
        s = client_case_or_404(conn, ctx, request, t, case_id)
        if not s["completed"]:
            raise not_found("The audit record is available once the case is completed.")
        return t

    @r.get("/client/cases/{case_id}/packages/{version}.{fmt}")
    async def client_package(request: Request, case_id: str, version: int, fmt: str):
        def work(conn, ctx):
            t = client_case(conn, ctx, request, case_id)
            docs = package_docs(conn, tenant_id=t, case_id=case_id, masked=True)
            try:
                resp = package_response(docs, version, fmt, masked=True, not_found=not_found,
                                        links_base=f"/client/cases/{case_id}")
            except pdfmod.PdfUnavailable as e:
                raise unavailable(e)
            client_read(conn, ctx, t, case_id, f"package.v{version}.{fmt}")
            return resp
        return await handle(request, work)

    @r.get("/client/cases/{case_id}/audit-export.{kind}")
    async def client_export_file(request: Request, case_id: str, kind: str):
        def work(conn, ctx):
            t = client_case(conn, ctx, request, case_id)
            if kind not in ("pdf", "zip"):
                raise not_found("Export file must be pdf or zip.")
            try:
                resp = export_file(conn, tenant_id=t, case_id=case_id, masked=True, kind=kind)
            except pdfmod.PdfUnavailable as e:
                raise unavailable(e)
            client_read(conn, ctx, t, case_id, f"export.{kind}")
            return resp
        return await handle(request, work)

    return r
