"""FastAPI app factory. OWNER: web agent.

Two surfaces (managed-service model, DECISIONS 2026-11-07):
- /ops: our analysts' workbench (queue R-16, case view, actions R-17, second approval R-19,
  package R-20, export R-22, instrumentation R-24, admin config R-21).
- /client: the furnisher client's portal (CLIENT_VIEWER, own tenant only): volumes, SLA status,
  outcomes, audit-export downloads.
Server-rendered Jinja2 + minimal JS (ADR-001). AuthN: local accounts + TOTP MFA (R-18).

Security notes: every route re-reads the user and checks role and tenant on the server; POSTs need
the session's CSRF token; cookies are HttpOnly + SameSite=Lax (+ Secure when
DISPUTES_COOKIE_SECURE=1 or mode=live); untrusted text is rendered with autoescape only.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from disputes.config import Config, settings as load_settings
from disputes.db import repo
from disputes.db.core import connect
from disputes.domain import Role
from disputes.web import actions as act
from disputes.web import auth, configsvc, export, metrics, portal, views
from disputes.web import casedata as cd
from disputes.web.pii import mask_account
from disputes.workflow.state_machine import IllegalTransition

HERE = Path(__file__).parent
SUPERVISOR_ROLES = (Role.SUPERVISOR, Role.ADMIN)


class LoginRequired(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Ctx:
    principal: auth.Principal
    session: dict
    cfg: Config
    tenants: list[str]


@dataclass
class Page:
    template: str
    data: dict
    status: int = 200


def create_app(*, database_url: str | None = None, session_secret: str | None = None, sink=None,
               mode: str | None = None) -> FastAPI:
    st = load_settings()
    db_url = database_url or st.database_url
    codec = auth.SessionCodec(session_secret or st.session_secret)
    if sink is None:
        from disputes.contracts_bridge import StubResponseSink
        sink = StubResponseSink()

    app = FastAPI(title="Disputes platform (SYNTHETIC)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sink = sink
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(label=views.label, mask_account=mask_account,
                                 reason_codes=act.REASON_CODES)
    templates.env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, sort_keys=True, default=str,
                                                                  ensure_ascii=False)

    def db():
        c = connect(db_url)
        c.autocommit = True
        return c

    def run_mode(conn) -> str:
        return mode or configsvc.effective_config(conn).mode

    def cookie_secure(m: str) -> bool:
        return os.environ.get("DISPUTES_COOKIE_SECURE") == "1" or m == "live"

    # ------------------------------------------------------------ plumbing
    def load_ctx(conn, request: Request) -> Ctx:
        cfg = configsvc.effective_config(conn)
        if mode:
            cfg = cfg.with_overrides(mode=mode)
        sess = codec.load(request.cookies.get(auth.SESSION_COOKIE), idle_timeout_s=cfg.session_idle_timeout_min * 60)
        if not sess:
            raise LoginRequired()
        p = auth.load_principal(conn, sess["uid"])
        if p is None:
            raise LoginRequired()
        return Ctx(p, codec.touch(sess), cfg, auth.tenant_ids_for(conn, p))

    def check_csrf(ctx: Ctx, token: str | None) -> None:
        if not token or not hmac.compare_digest(str(token), ctx.session["csrf"]):
            raise HttpError(403, "The form expired or did not come from this site. Reload the page and try again.")

    def require(ctx: Ctx, *roles: Role) -> None:
        if ctx.principal.role not in roles:
            raise HttpError(403, "Your role cannot open this page.")

    def require_tenant(ctx: Ctx, tenant_id: str) -> None:
        if not ctx.principal.is_staff or tenant_id not in ctx.tenants:
            raise HttpError(404, "No such client or case.")

    async def handle(request: Request, fn: Callable[..., Any], *args, form: bool = False, json_body: bool = False):
        data = None
        if form:
            data = await request.form()
        elif json_body:
            try:
                data = await request.json()
            except ValueError:
                data = {}

        def work():
            with db() as conn:
                ctx = load_ctx(conn, request)
                if form:
                    check_csrf(ctx, data.get("csrf"))
                if json_body:
                    check_csrf(ctx, (data or {}).get("csrf") or request.headers.get("x-csrf-token"))
                result = fn(conn, ctx, *args, *(() if data is None else (data,)))
                return ctx, result, run_mode(conn)
        try:
            ctx, result, m = await run_in_threadpool(work)
        except LoginRequired:
            resp = RedirectResponse("/login", status_code=303)
            resp.delete_cookie(auth.SESSION_COOKIE)
            return resp
        except HttpError as e:
            return error_page(request, e.status, e.message)
        except repo.NotFound:
            return error_page(request, 404, "No such client or case.")
        if isinstance(result, Page):
            resp = templates.TemplateResponse(request, result.template, {
                **result.data, "me": ctx.principal, "csrf": ctx.session["csrf"], "tenants": ctx.tenants,
                "cfg": ctx.cfg}, status_code=result.status)
        else:
            resp = result
        resp.set_cookie(auth.SESSION_COOKIE, codec.dump(ctx.session), httponly=True, samesite="lax",
                        secure=cookie_secure(m), path="/")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def error_page(request: Request, status: int, message: str):
        return templates.TemplateResponse(request, "error.html", {"status": status, "message": message, "me": None},
                                          status_code=status)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        return error_page(request, exc.status_code, "Page not found." if exc.status_code == 404 else str(exc.detail))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                                "frame-ancestors 'none'; form-action 'self'")
        return resp

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    # ------------------------------------------------------------ login + MFA (R-18)
    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        def work(conn, ctx):
            return RedirectResponse("/client" if ctx.principal.role == Role.CLIENT_VIEWER else "/ops", 303)
        return await handle(request, work)

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"me": None, "error": None})

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()

        def work():
            with db() as conn:
                return auth.authenticate_password(conn, str(form.get("email", "")), str(form.get("password", "")))
        user = await run_in_threadpool(work)
        if user is None:
            return templates.TemplateResponse(request, "login.html", {
                "me": None, "error": "Email or password is incorrect."}, status_code=401)
        resp = RedirectResponse("/login/mfa", status_code=303)
        resp.set_cookie(auth.PENDING_COOKIE, codec.dump_pending(user["user_id"]), httponly=True, samesite="lax",
                        max_age=auth.PENDING_MAX_AGE_S, path="/login")
        return resp

    def _pending_user(request: Request):
        uid = codec.load_pending(request.cookies.get(auth.PENDING_COOKIE))
        if not uid:
            return None, None, None
        with db() as conn:
            row = conn.execute("SELECT user_id, display_name, totp_secret, active, role FROM users WHERE user_id = %s",
                               (uid,)).fetchone()
            return row, run_mode(conn), (row or {}).get("totp_secret")

    @app.get("/login/mfa", response_class=HTMLResponse)
    async def mfa_form(request: Request):
        row, m, secret = await run_in_threadpool(_pending_user, request)
        if row is None:
            return RedirectResponse("/login", status_code=303)
        dev_code = auth.current_totp(secret) if (secret and auth.dev_show_totp_enabled(m)) else None
        return templates.TemplateResponse(request, "mfa.html", {"me": None, "error": None, "dev_code": dev_code,
                                                                "name": row["display_name"],
                                                                "enrolled": bool(secret)})

    @app.post("/login/mfa")
    async def mfa_submit(request: Request):
        form = await request.form()
        row, m, secret = await run_in_threadpool(_pending_user, request)
        if row is None or not row["active"]:
            return RedirectResponse("/login", status_code=303)
        if not auth.verify_totp(secret, str(form.get("code", ""))):
            dev_code = auth.current_totp(secret) if (secret and auth.dev_show_totp_enabled(m)) else None
            return templates.TemplateResponse(request, "mfa.html", {
                "me": None, "error": "That code is not valid. Enter the 6-digit code from your authenticator app.",
                "dev_code": dev_code, "name": row["display_name"], "enrolled": bool(secret)}, status_code=401)
        sess = codec.new_session(row["user_id"])
        resp = RedirectResponse("/client" if row["role"] == Role.CLIENT_VIEWER.value else "/ops", status_code=303)
        resp.delete_cookie(auth.PENDING_COOKIE, path="/login")
        resp.set_cookie(auth.SESSION_COOKIE, codec.dump(sess), httponly=True, samesite="lax",
                        secure=cookie_secure(m), path="/")
        return resp

    @app.post("/logout")
    async def logout(request: Request):
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.SESSION_COOKIE, path="/")
        return resp

    # ------------------------------------------------------------ /ops
    def staff(ctx: Ctx):
        if not ctx.principal.is_staff:
            raise HttpError(403, "This area is for our operations staff. Client users sign in to the client portal.")

    @app.get("/ops")
    async def ops_home(request: Request):
        def work(conn, ctx):
            staff(ctx)
            if not ctx.tenants:
                return Page("error.html", {"status": 200, "message": "You are not assigned to any client yet. "
                                           "Ask an admin to grant access."})
            return RedirectResponse(f"/ops/t/{ctx.tenants[0]}/queue", 303)
        return await handle(request, work)

    @app.get("/ops/t/{tenant_id}/queue", response_class=HTMLResponse)
    async def ops_queue(request: Request, tenant_id: str, state: str = "OPEN", flag: str = ""):
        def work(conn, ctx):
            staff(ctx)
            require_tenant(ctx, tenant_id)
            states = (views.OPEN_STATES if state == "OPEN" else None if state == "ALL"
                      else [state] if state in views.STATE_LABELS else views.OPEN_STATES)
            rows = repo.list_cases(conn, tenant_id=tenant_id, states=states, flag=flag or None)
            tname = conn.execute("SELECT display_name FROM tenants WHERE tenant_id = %s", (tenant_id,)).fetchone()
            return Page("ops_queue.html", {"tenant_id": tenant_id, "tenant_name": tname["display_name"],
                                           "rows": rows, "state": state, "flag": flag,
                                           "states": list(views.STATE_LABELS), "flags": _flags()})
        return await handle(request, work)

    def case_page(conn, ctx: Ctx, tenant_id: str, case_id: str, *, error: str | None = None,
                  error_field: str | None = None, status: int = 200, notice: str | None = None) -> Page:
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id)
        vm = views.case_view(conn, b, role=ctx.principal.role, cfg=ctx.cfg)
        tname = conn.execute("SELECT display_name FROM tenants WHERE tenant_id = %s", (tenant_id,)).fetchone()
        return Page("ops_case.html", {**vm, "tenant_id": tenant_id, "tenant_name": tname["display_name"],
                                      "error": error, "error_field": error_field, "notice": notice,
                                      "idle_cutoff_s": ctx.cfg.idle_cutoff_s}, status)

    @app.get("/ops/t/{tenant_id}/cases/{case_id}", response_class=HTMLResponse)
    async def ops_case(request: Request, tenant_id: str, case_id: str, notice: str = ""):
        def work(conn, ctx):
            staff(ctx)
            require_tenant(ctx, tenant_id)
            act.open_case(conn, tenant_id=tenant_id, case_id=case_id, actor=act.Actor.of(ctx.principal))
            return case_page(conn, ctx, tenant_id, case_id, notice=_NOTICES.get(notice))
        return await handle(request, work)

    @app.post("/ops/t/{tenant_id}/cases/{case_id}/actions/{action}")
    async def ops_action(request: Request, tenant_id: str, case_id: str, action: str):
        def work(conn, ctx, form):
            staff(ctx)
            require_tenant(ctx, tenant_id)
            actor = act.Actor.of(ctx.principal)
            ver = _int(form.get("version"))
            common = dict(tenant_id=tenant_id, case_id=case_id, actor=actor, expected_version=ver)
            rc, rt = (form.get("reason_code") or None), form.get("reason_text") or ""
            try:
                if action == "edit":
                    act.edit(conn, **common, reason_code=rc, reason_text=rt, cfg=ctx.cfg,
                             outcome=form.get("outcome") or None, corrections=_corrections(form),
                             narrative=form.get("narrative") if form.get("narrative", "").strip() else None,
                             claim_findings=_findings(form))
                elif action == "approve":
                    act.approve(conn, **common, sink=app.state.sink, cfg=ctx.cfg)
                elif action == "second_approve":
                    act.second_approve(conn, **common, sink=app.state.sink, cfg=ctx.cfg)
                elif action == "reject_second":
                    act.reject_second_approval(conn, **common, reason_code=rc, reason_text=rt)
                elif action == "escalate":
                    act.escalate(conn, **common, reason_code=rc, reason_text=rt)
                elif action == "out_of_scope":
                    act.mark_out_of_scope(conn, **common, reason_code=rc, reason_text=rt)
                elif action == "take":
                    act.take_for_review(conn, **common)
                elif action == "reopen":
                    act.reopen_submitted(conn, **common, reason_code=rc, reason_text=rt)
                else:
                    raise HttpError(404, "Unknown action.")
            except act.ActionError as e:
                return case_page(conn, ctx, tenant_id, case_id, error=str(e), error_field=e.field, status=400)
            except (act.ActionForbidden, PermissionError) as e:
                return case_page(conn, ctx, tenant_id, case_id, error=str(e), status=403)
            except (act.StaleCase, IllegalTransition) as e:
                return case_page(conn, ctx, tenant_id, case_id, error=str(e), status=409)
            return RedirectResponse(f"/ops/t/{tenant_id}/cases/{case_id}?notice={action}", 303)
        return await handle(request, work, form=True)

    @app.post("/ops/t/{tenant_id}/cases/{case_id}/metrics")
    async def ops_metrics_beacon(request: Request, tenant_id: str, case_id: str):
        def work(conn, ctx, body):
            staff(ctx)
            require_tenant(ctx, tenant_id)
            repo.get_case(conn, tenant_id=tenant_id, case_id=case_id)
            try:
                secs = float((body or {}).get("active_seconds", 0))
            except (TypeError, ValueError):
                raise HttpError(400, "active_seconds must be a number")
            stored = metrics.record_active_seconds(conn, tenant_id=tenant_id, case_id=case_id,
                                                   user_id=ctx.principal.user_id, seconds=secs)
            return JSONResponse({"stored_seconds": stored})
        return await handle(request, work, json_body=True)

    @app.get("/ops/t/{tenant_id}/cases/{case_id}/export.{fmt}")
    async def ops_export(request: Request, tenant_id: str, case_id: str, fmt: str):
        def work(conn, ctx):
            staff(ctx)
            require_tenant(ctx, tenant_id)
            ex = export.build_export(conn, tenant_id=tenant_id, case_id=case_id)
            metrics.record_case_read(conn, tenant_id=tenant_id, case_id=case_id, user_id=ctx.principal.user_id,
                                     role=ctx.principal.role.value, surface=f"export.{fmt}")
            return _export_response(request, ex, fmt, case_id)
        return await handle(request, work)

    @app.get("/ops/t/{tenant_id}/metrics.csv")
    async def ops_metrics_csv(request: Request, tenant_id: str):
        def work(conn, ctx):
            require(ctx, *SUPERVISOR_ROLES)
            require_tenant(ctx, tenant_id)
            return PlainTextResponse(metrics.metrics_csv(conn, tenant_id=tenant_id), media_type="text/csv",
                                     headers={"Content-Disposition":
                                              f'attachment; filename="review-metrics-{tenant_id}.csv"'})
        return await handle(request, work)

    # ------------------------------------------------------------ /ops/admin (R-21)
    def admin_page(conn, ctx, error=None, status=200, notice=None):
        return Page("ops_admin.html", {"rows": configsvc.current_rows(conn), "pending": configsvc.pending(conn),
                                       "error": error, "notice": notice}, status)

    @app.get("/ops/admin", response_class=HTMLResponse)
    async def ops_admin(request: Request):
        def work(conn, ctx):
            require(ctx, Role.ADMIN)
            return admin_page(conn, ctx)
        return await handle(request, work)

    @app.post("/ops/admin/propose")
    async def ops_admin_propose(request: Request):
        def work(conn, ctx, form):
            require(ctx, Role.ADMIN)
            try:
                configsvc.propose_change(conn, actor=ctx.principal, key=str(form.get("key", "")),
                                         raw_value=str(form.get("value", "")), reason=str(form.get("reason", "")))
            except configsvc.ConfigError as e:
                return admin_page(conn, ctx, error=str(e), status=400)
            return admin_page(conn, ctx, notice="Change proposed. A different admin must approve it before it applies.")
        return await handle(request, work, form=True)

    @app.post("/ops/admin/requests/{request_id}")
    async def ops_admin_decide(request: Request, request_id: int):
        def work(conn, ctx, form):
            require(ctx, Role.ADMIN)
            try:
                r = configsvc.decide_change(conn, actor=ctx.principal, request_id=request_id,
                                            approve=form.get("decision") == "approve", note=str(form.get("note", "")))
            except configsvc.ConfigError as e:
                return admin_page(conn, ctx, error=str(e), status=400)
            except configsvc.ConfigForbidden as e:
                return admin_page(conn, ctx, error=str(e), status=403)
            return admin_page(conn, ctx, notice=f"Change request {request_id} {r['status'].lower()}.")
        return await handle(request, work, form=True)

    # ------------------------------------------------------------ /client (CLIENT_VIEWER, own tenant only)
    def client_only(ctx: Ctx) -> str:
        if ctx.principal.role != Role.CLIENT_VIEWER or not ctx.principal.home_tenant_id:
            raise HttpError(403, "The client portal is for client users.")
        return ctx.principal.home_tenant_id

    @app.get("/client", response_class=HTMLResponse)
    async def client_home(request: Request):
        def work(conn, ctx):
            t = client_only(ctx)
            tname = conn.execute("SELECT display_name FROM tenants WHERE tenant_id = %s", (t,)).fetchone()
            return Page("client_dashboard.html", {"tenant_name": tname["display_name"],
                                                  "dash": portal.dashboard(conn, tenant_id=t),
                                                  "cases": portal.case_list(conn, tenant_id=t)})
        return await handle(request, work)

    @app.get("/client/cases/{case_id}", response_class=HTMLResponse)
    async def client_case(request: Request, case_id: str):
        def work(conn, ctx):
            t = client_only(ctx)
            s = portal.case_summary(conn, tenant_id=t, case_id=case_id)
            if s is None:
                raise HttpError(404, "No such case.")
            case = repo.get_case(conn, tenant_id=t, case_id=case_id)
            return Page("client_case.html", {"c": s, "timeline": views.timeline(conn, case, client_view=True),
                                             "ruler": views.deadline_ruler(case)})
        return await handle(request, work)

    @app.get("/client/cases/{case_id}/export.{fmt}")
    async def client_export(request: Request, case_id: str, fmt: str):
        def work(conn, ctx):
            t = client_only(ctx)
            s = portal.case_summary(conn, tenant_id=t, case_id=case_id)
            if s is None:
                raise HttpError(404, "No such case.")
            if not s["completed"]:
                raise HttpError(404, "The audit export is available once the case is completed.")
            ex = export.build_export(conn, tenant_id=t, case_id=case_id, masked=True)
            return _export_response(request, ex, fmt, case_id)
        return await handle(request, work)

    def _export_response(request: Request, ex: dict, fmt: str, case_id: str):
        if fmt == "json":
            return Response(json.dumps(ex, indent=2, ensure_ascii=False, sort_keys=True), media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="case-{case_id}-export.json"'})
        if fmt == "html":
            return templates.TemplateResponse(request, "export.html", {"ex": ex, "me": None})
        raise HttpError(404, "Export format must be json or html.")

    return app


# ---------------------------------------------------------------- form parsing helpers
_NOTICES = {"edit": "Edits saved. Approve when the case is ready.", "approve": "Approved.",
            "second_approve": "Second approval given. The package was written to the stub sink.",
            "reject_second": "Second approval rejected; the case is back in review.",
            "escalate": "Case escalated to a supervisor.", "out_of_scope": "Case marked out of scope.",
            "take": "You took this case for review.", "reopen": "Case reopened. The next approval writes a new package version."}


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _corrections(form) -> list[dict] | None:
    """Fields corr_month_N / corr_reported_N / corr_corrected_N. None when the form has no correction rows."""
    idx = sorted({k.rsplit("_", 1)[1] for k in form.keys() if k.startswith("corr_month_")})
    if not idx:
        return None
    out = []
    for i in idx:
        m, c = (form.get(f"corr_month_{i}") or "").strip(), (form.get(f"corr_corrected_{i}") or "").strip()
        if m or c:
            out.append({"month": m, "field": "payment_rating", "reported": form.get(f"corr_reported_{i}") or None,
                        "corrected": c})
    return out


def _findings(form) -> dict | None:
    """Fields finding__<claim_id>, finding_ev__<claim_id> (comma list), finding_reason__<claim_id>."""
    out = {}
    for k in form.keys():
        if k.startswith("finding__"):
            cid = k[len("finding__"):]
            f = form.get(k)
            if f:
                out[cid] = {"finding": f,
                            "evidence_ids": [x.strip() for x in (form.get(f"finding_ev__{cid}") or "").split(",")
                                             if x.strip()],
                            "reason": form.get(f"finding_reason__{cid}") or ""}
    return out or None


def _flags() -> list[str]:
    from disputes.domain import EscalationReason
    return [e.value for e in EscalationReason]
