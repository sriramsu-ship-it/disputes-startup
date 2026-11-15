"""FastAPI app factory. OWNER: web agent.

Two surfaces (managed-service model, DECISIONS 2026-11-07):
- /ops: our analysts' workbench (queue R-16, case view, actions R-17, second approval R-19,
  package R-20, export R-22, instrumentation R-24, admin config R-21).
- /client: the furnisher client's portal (CLIENT_VIEWER, own tenant only): volumes, SLA status,
  outcomes, audit-export downloads.
Server-rendered Jinja2 + minimal JS (ADR-001). AuthN: local accounts + TOTP MFA (R-18).

Security notes (hardening, see docs/engineering/stage-notes/hardening.md):
- server-side sessions (web_sessions), rotated at the password step and after MFA, revocable;
  every route re-reads the session row and the user and checks role and tenant on the server;
- POSTs need the session's CSRF token, and every unsafe request from a browser whose Origin /
  Sec-Fetch-Site says cross-site is refused (covers the pre-session login forms too);
- any unsafe request carrying a CLIENT_VIEWER session is refused (403) and audited (R-39);
- cookies HttpOnly + SameSite=Lax (+ Secure and the __Host- prefix when Settings.cookie_secure);
- HSTS when cookie_secure; CSP without inline script/style; body size limit; errors never carry a
  stack trace to the client; structured request log through the R-27 masking filter;
- untrusted text is rendered with autoescape only.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from disputes.audit.chain import append_event
from disputes.config import Config, settings as load_settings
from disputes.db import repo
from disputes.db.core import connect
from disputes.domain import ActorType, Role
from disputes.web import actions as act
from disputes.web import admin_users, auth, configsvc, export, metrics, portal, views
from disputes.web import casedata as cd
from disputes.web.pii import PiiMaskingFilter, mask_account, mask_text
from disputes.workflow.state_machine import IllegalTransition

HERE = Path(__file__).parent
SUPERVISOR_ROLES = (Role.SUPERVISOR, Role.ADMIN)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PRE_SESSION_PATHS = ("/login", "/logout", "/invite/")      # unsafe requests allowed without a staff session
DEFAULT_MAX_BODY_BYTES = 1_048_576
CSP = ("default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
       "form-action 'self'; base-uri 'none'; object-src 'none'")
_INVITE_PATH = re.compile(r"^/invite/[^/]+")
req_log = logging.getLogger("disputes.web.request")


def redact_path(path: str) -> str:
    """Request paths for logs: invite tokens are secrets."""
    return _INVITE_PATH.sub("/invite/<redacted>", path or "")


def max_body_bytes() -> int:
    try:
        return max(1024, int(os.environ.get("DISPUTES_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)))
    except ValueError:
        return DEFAULT_MAX_BODY_BYTES


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Pure ASGI: 413 when Content-Length exceeds the limit, or when a streamed body does."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cl = dict(scope.get("headers") or []).get(b"content-length")
        if cl is not None:
            try:
                too_big = int(cl) > self.max_bytes
            except ValueError:
                return await _plain(send, 400, b"Bad Content-Length")
            if too_big:
                return await _plain(send, 413, b"Request too large")
        seen, started = 0, False

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge()
            return msg

        async def tracked(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)
        try:
            await self.app(scope, limited, tracked)
        except BodyTooLarge:
            if not started:
                await _plain(send, 413, b"Request too large")


async def _plain(send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


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
    # Sessions are server-side random tokens (auth.SessionStore); session_secret is no longer used to
    # sign them. Kept as a parameter for compatibility with callers.
    del session_secret
    store = auth.SessionStore()
    secure_cookies = bool(st.cookie_secure)
    session_cookie = auth.SECURE_SESSION_COOKIE if secure_cookies else auth.SESSION_COOKIE
    if sink is None:
        from disputes.contracts_bridge import StubResponseSink
        sink = StubResponseSink()

    app = FastAPI(title="Disputes platform (SYNTHETIC)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sink = sink
    app.state.database_url = db_url
    from disputes.web.health import router as health_router; app.include_router(health_router)  # noqa: E702 (deploy)
    app.state.session_cookie = session_cookie
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(label=views.label, mask_account=mask_account,
                                 reason_codes=act.REASON_CODES)
    templates.env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, sort_keys=True, default=str,
                                                                  ensure_ascii=False)
    if not any(isinstance(f, PiiMaskingFilter) for f in req_log.filters):
        req_log.addFilter(PiiMaskingFilter())

    def db():
        c = connect(db_url)
        c.autocommit = True
        return c

    def run_mode(conn) -> str:
        return mode or configsvc.effective_config(conn).mode

    def cookie_secure(m: str) -> bool:
        return secure_cookies or m == "live"

    def ip_of(request: Request) -> str:
        return auth.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))

    def set_session_cookie(resp, token: str, m: str) -> None:
        resp.set_cookie(session_cookie, token, httponly=True, samesite="lax", secure=cookie_secure(m), path="/")

    def audit_user_event(conn, *, user_id: str, role: str, home_tenant: str | None, event_type: str,
                         payload: dict) -> None:
        with conn.transaction():
            append_event(conn, tenant_id=home_tenant or "ops", case_id=None, event_type=event_type,
                         actor_type=ActorType.HUMAN, actor_id=user_id, actor_role=role, payload=payload)

    # ------------------------------------------------------------ plumbing
    def load_ctx(conn, request: Request) -> Ctx:
        cfg = configsvc.effective_config(conn)
        if mode:
            cfg = cfg.with_overrides(mode=mode)
        tok = request.cookies.get(session_cookie)
        row = store.load(conn, tok, stage="ACTIVE", idle_timeout_s=cfg.session_idle_timeout_min * 60)
        if not row:
            raise LoginRequired()
        p = auth.load_principal(conn, row["user_id"])
        if p is None:
            store.revoke(conn, tok, "user inactive")
            raise LoginRequired()
        request.state.user_id = p.user_id
        return Ctx(p, {"uid": p.user_id, "csrf": row["csrf"]}, cfg, auth.tenant_ids_for(conn, p))

    def check_csrf(ctx: Ctx, token: str | None) -> None:
        if not token or not hmac.compare_digest(str(token), ctx.session["csrf"]):
            raise HttpError(403, "The form expired or did not come from this site. Reload the page and try again.")

    def require(ctx: Ctx, *roles: Role) -> None:
        if ctx.principal.role not in roles:
            raise HttpError(403, "Your role cannot open this page.")

    def access_denied(conn, ctx: Ctx, request: Request, *, tenant_id: str | None, case_id: str | None) -> None:
        """R-37: a request for another tenant's (or a non-existent) record answers not-found and is
        audited in the requester's own scope (never written into the other tenant's case chain)."""
        p = ctx.principal
        audit_user_event(conn, user_id=p.user_id, role=p.role.value,
                         home_tenant=p.home_tenant_id if p.role == Role.CLIENT_VIEWER else "ops",
                         event_type="ACCESS_DENIED",
                         payload={"user_id": p.user_id, "role": p.role.value, "requested_tenant": tenant_id,
                                  "requested_case": case_id, "path": redact_path(request.url.path),
                                  "method": request.method})

    def require_tenant(conn, ctx: Ctx, request: Request, tenant_id: str) -> None:
        if not ctx.principal.is_staff or tenant_id not in ctx.tenants:
            access_denied(conn, ctx, request, tenant_id=tenant_id, case_id=None)
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
                try:
                    if form:
                        check_csrf(ctx, data.get("csrf"))
                    if json_body:
                        check_csrf(ctx, (data or {}).get("csrf") or request.headers.get("x-csrf-token"))
                    result = fn(conn, ctx, *args, *(() if data is None else (data,)))
                except repo.NotFound:
                    access_denied(conn, ctx, request, tenant_id=request.path_params.get("tenant_id"),
                                  case_id=request.path_params.get("case_id"))
                    raise
                return ctx, result, run_mode(conn)
        try:
            ctx, result, m = await run_in_threadpool(work)
        except LoginRequired:
            resp = RedirectResponse("/login", status_code=303)
            resp.delete_cookie(session_cookie, path="/")
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
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def error_page(request: Request, status: int, message: str):
        resp = templates.TemplateResponse(request, "error.html", {"status": status, "message": message, "me": None},
                                          status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        msg = {404: "Page not found.", 405: "That method is not allowed here."}.get(exc.status_code, "Request refused.")
        return error_page(request, exc.status_code, msg)

    # ------------------------------------------------------------ middleware (innermost first)
    app.add_middleware(BodyLimitMiddleware, max_bytes=max_body_bytes())

    @app.middleware("http")
    async def unsafe_request_guard(request: Request, call_next):
        """CSRF defence in depth (Origin / Sec-Fetch-Site) and R-39 (CLIENT_VIEWER is read-only)."""
        if request.method in UNSAFE_METHODS:
            sfs = (request.headers.get("sec-fetch-site") or "").lower()
            origin = request.headers.get("origin")
            if sfs == "cross-site" or (origin is not None and not _same_origin(origin, request)):
                return error_page(request, 403, "Cross-site request refused.")
            tok = request.cookies.get(session_cookie)
            if tok and not request.url.path.startswith(PRE_SESSION_PATHS):
                if await run_in_threadpool(_client_write_denied, tok, request):
                    return error_page(request, 403, "The client portal is read-only.")
        return await call_next(request)

    def _same_origin(origin: str, request: Request) -> bool:
        allowed = {o.strip().rstrip("/") for o in os.environ.get("DISPUTES_ALLOWED_ORIGINS", "").split(",") if o.strip()}
        if origin.rstrip("/") in allowed:
            return True
        host = request.headers.get("host", "")
        return bool(host) and origin.split("://", 1)[-1].rstrip("/") == host

    def _client_write_denied(tok: str, request: Request) -> bool:
        with db() as conn:
            row = store.load(conn, tok, stage="ACTIVE", touch=False)
            if row is None:
                return False
            u = conn.execute("SELECT user_id, role, tenant_id FROM users WHERE user_id = %s AND active",
                             (row["user_id"],)).fetchone()
            if u is None or u["role"] != Role.CLIENT_VIEWER.value:
                return False
            audit_user_event(conn, user_id=u["user_id"], role=u["role"], home_tenant=u["tenant_id"],
                             event_type="CLIENT_WRITE_DENIED",
                             payload={"user_id": u["user_id"], "role": u["role"], "method": request.method,
                                      "path": redact_path(request.url.path)})
            return True

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if secure_cookies:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    @app.middleware("http")
    async def request_log_and_errors(request: Request, call_next):
        """Outermost: request ID, structured access log (masked), and no stack trace to the client."""
        rid = secrets.token_hex(8)
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception as e:  # noqa: BLE001 - last line of defence: generic page, details only in the log
            frames = [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(e.__traceback__)]
            req_log.error(json.dumps({"event": "unhandled_error", "request_id": rid, "error_type": type(e).__name__,
                                      "error": mask_text(str(e))[:500], "frames": frames[-8:]}, ensure_ascii=False))
            resp = error_page(request, 500, f"Something went wrong on our side. Reference: {rid}.")
            for h in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options"):
                resp.headers.setdefault(h, {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY",
                                            "X-Content-Type-Options": "nosniff"}[h])
        resp.headers["X-Request-ID"] = rid
        req_log.info(json.dumps({"event": "http_request", "request_id": rid, "method": request.method,
                                 "path": redact_path(request.url.path), "status": resp.status_code,
                                 "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                                 "client_ip": ip_of(request),
                                 "user_id": getattr(request.state, "user_id", None)}, ensure_ascii=False))
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

    def login_page(request: Request, *, error: str | None = None, notice: str | None = None, status: int = 200):
        resp = templates.TemplateResponse(request, "login.html", {"me": None, "error": error, "notice": notice},
                                          status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, enrolled: str = ""):
        return login_page(request, notice="Your sign-in is set up. Sign in with your new password and code."
                          if enrolled else None)

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        ip = ip_of(request)

        def work():
            with db() as conn:
                res = auth.authenticate_password(conn, str(form.get("email", ""))[:320],
                                                 str(form.get("password", "")), ip=ip, env=st.environment)
                if res.user is None:
                    return res, None
                # New pre-auth session; whatever session the browser presented is revoked (no fixation).
                store.revoke(conn, request.cookies.get(session_cookie), "new sign-in")
                store.revoke(conn, request.cookies.get(auth.PENDING_COOKIE), "new sign-in")
                tok, _ = store.create(conn, res.user["user_id"], stage="MFA_PENDING", ip=ip)
                return res, tok
        res, tok = await run_in_threadpool(work)
        if tok is None:
            return login_page(request, error=res.error, status=res.status)
        resp = RedirectResponse("/login/mfa", status_code=303)
        resp.delete_cookie(session_cookie, path="/")
        resp.set_cookie(auth.PENDING_COOKIE, tok, httponly=True, samesite="lax", secure=secure_cookies,
                        max_age=auth.PENDING_MAX_AGE_S, path="/login")
        return resp

    def _pending_user(request: Request):
        tok = request.cookies.get(auth.PENDING_COOKIE)
        with db() as conn:
            sess = store.load(conn, tok, stage="MFA_PENDING", touch=False)
            if sess is None:
                return None, None, None
            row = conn.execute("SELECT user_id, email, display_name, totp_secret, active, role, tenant_id FROM users "
                               "WHERE user_id = %s", (sess["user_id"],)).fetchone()
            return row, run_mode(conn), (row or {}).get("totp_secret")

    def mfa_page(request: Request, row, m, secret, *, error=None, status=200):
        dev_code = auth.current_totp(secret) if (secret and auth.dev_show_totp_enabled(m)) else None
        resp = templates.TemplateResponse(request, "mfa.html", {"me": None, "error": error, "dev_code": dev_code,
                                                                "name": row["display_name"],
                                                                "enrolled": bool(secret)}, status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/login/mfa", response_class=HTMLResponse)
    async def mfa_form(request: Request):
        row, m, secret = await run_in_threadpool(_pending_user, request)
        if row is None:
            return RedirectResponse("/login", status_code=303)
        return mfa_page(request, row, m, secret)

    @app.post("/login/mfa")
    async def mfa_submit(request: Request):
        form = await request.form()
        ip = ip_of(request)
        ptok = request.cookies.get(auth.PENDING_COOKIE)

        def work():
            with db() as conn:
                sess = store.load(conn, ptok, stage="MFA_PENDING", touch=False)
                if sess is None:
                    return "restart", None, None, None
                row = conn.execute("SELECT * FROM users WHERE user_id = %s", (sess["user_id"],)).fetchone()
                m = run_mode(conn)
                if row is None or not row["active"]:
                    store.revoke(conn, ptok, "user inactive")
                    return "restart", None, None, None
                key = auth.account_key(row["email"])
                with conn.transaction():
                    auth._lock_account(conn, key)
                    if auth.ip_throttled(conn, ip) or auth.account_locked(conn, key):
                        auth.record_attempt(conn, kind="TOTP", key=key, ip=ip, success=False)
                        store.revoke(conn, ptok, "locked")
                        return "locked", row, m, None
                    ok = auth.consume_totp(conn, row["user_id"], row["totp_secret"], str(form.get("code", "")))
                    auth.record_attempt(conn, kind="TOTP", key=key, ip=ip, success=ok)
                    if not ok:
                        store.mfa_failed(conn, ptok)
                        auth.audit_if_lock_started(conn, key, row, ip=ip, kind="TOTP")
                        return "bad", row, m, None
                    store.revoke(conn, ptok, "mfa complete")
                    tok, _ = store.create(conn, row["user_id"], stage="ACTIVE", ip=ip)   # rotated after MFA
                    audit_user_event(conn, user_id=row["user_id"], role=row["role"], home_tenant=row["tenant_id"],
                                     event_type="SIGNED_IN", payload={"user_id": row["user_id"], "role": row["role"],
                                                                      "mfa": "TOTP", "source_ip": ip})
                return "ok", row, m, tok
        status, row, m, tok = await run_in_threadpool(work)
        if status == "restart":
            return RedirectResponse("/login", status_code=303)
        if status == "locked":
            return login_page(request, error=auth.LOCKED_ERROR, status=429)
        if status == "bad":
            return mfa_page(request, row, m, row["totp_secret"], status=401,
                            error="That code is not valid. Enter the 6-digit code from your authenticator app.")
        resp = RedirectResponse("/client" if row["role"] == Role.CLIENT_VIEWER.value else "/ops", status_code=303)
        resp.delete_cookie(auth.PENDING_COOKIE, path="/login")
        set_session_cookie(resp, tok, m)
        return resp

    @app.post("/logout")
    async def logout(request: Request):
        tok = request.cookies.get(session_cookie)

        def work():
            with db() as conn:
                row = store.load(conn, tok, stage="ACTIVE", touch=False)
                if row and store.revoke(conn, tok, "logout"):
                    u = conn.execute("SELECT role, tenant_id FROM users WHERE user_id = %s", (row["user_id"],)).fetchone()
                    audit_user_event(conn, user_id=row["user_id"], role=u["role"], home_tenant=u["tenant_id"],
                                     event_type="SIGNED_OUT", payload={"user_id": row["user_id"]})
        await run_in_threadpool(work)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(session_cookie, path="/")
        return resp

    # ------------------------------------------------------------ invite / first login (hardening)
    def invite_page(request: Request, token: str, view: dict, *, error: str | None = None, status: int = 200):
        resp = templates.TemplateResponse(request, "invite.html", {"me": None, "v": view, "error": error,
                                                                   "token": token}, status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/invite/{token}", response_class=HTMLResponse)
    async def invite_form(request: Request, token: str):
        def work():
            with db() as conn:
                return admin_users.invite_view(conn, token)
        view = await run_in_threadpool(work)
        if view is None:
            return error_page(request, 404, "This link is not valid any more. Ask an admin for a new one.")
        return invite_page(request, token, view)

    @app.post("/invite/{token}")
    async def invite_submit(request: Request, token: str):
        form = await request.form()
        ip = ip_of(request)

        def work():
            with db() as conn:
                if auth.ip_throttled(conn, ip):
                    return "locked", None
                try:
                    admin_users.complete_invite(conn, token=token, password=str(form.get("password", "")),
                                                confirm=str(form.get("confirm", "")), code=str(form.get("code", "")),
                                                ip=ip)
                except admin_users.AdminError as e:
                    return str(e), admin_users.invite_view(conn, token)
                return "ok", None
        status, view = await run_in_threadpool(work)
        if status == "ok":
            return RedirectResponse("/login?enrolled=1", status_code=303)
        if status == "locked":
            return error_page(request, 429, auth.LOCKED_ERROR)
        if view is None:
            return error_page(request, 404, status)
        return invite_page(request, token, view, error=status, status=400)

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
            require_tenant(conn, ctx, request, tenant_id)
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
            require_tenant(conn, ctx, request, tenant_id)
            act.open_case(conn, tenant_id=tenant_id, case_id=case_id, actor=act.Actor.of(ctx.principal))
            return case_page(conn, ctx, tenant_id, case_id, notice=_NOTICES.get(notice))
        return await handle(request, work)

    @app.post("/ops/t/{tenant_id}/cases/{case_id}/actions/{action}")
    async def ops_action(request: Request, tenant_id: str, case_id: str, action: str):
        def work(conn, ctx, form):
            staff(ctx)
            require_tenant(conn, ctx, request, tenant_id)
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
            require_tenant(conn, ctx, request, tenant_id)
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
            require_tenant(conn, ctx, request, tenant_id)
            ex = export.build_export(conn, tenant_id=tenant_id, case_id=case_id)
            metrics.record_case_read(conn, tenant_id=tenant_id, case_id=case_id, user_id=ctx.principal.user_id,
                                     role=ctx.principal.role.value, surface=f"export.{fmt}")
            return _export_response(request, ex, fmt, case_id)
        return await handle(request, work)

    @app.get("/ops/t/{tenant_id}/metrics.csv")
    async def ops_metrics_csv(request: Request, tenant_id: str):
        def work(conn, ctx):
            require(ctx, *SUPERVISOR_ROLES)
            require_tenant(conn, ctx, request, tenant_id)
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

    # ------------------------------------------------------------ /ops/admin/users (hardening; R-18, R-21, R-38)
    def users_page(conn, request: Request, *, error=None, notice=None, invite=None, status=200):
        base = f"{request.url.scheme}://{request.headers.get('host', '')}"
        return Page("ops_users.html", {"users": admin_users.list_users(conn),
                                       "client_tenants": admin_users.client_tenants(conn),
                                       "roles": [*admin_users.STAFF_ROLE_VALUES, Role.CLIENT_VIEWER.value],
                                       "error": error, "notice": notice,
                                       "invite_url": (base + invite) if invite else None,
                                       "invite_ttl_hours": auth.INVITE_TTL_HOURS}, status)

    @app.get("/ops/admin/users", response_class=HTMLResponse)
    async def ops_users(request: Request):
        def work(conn, ctx):
            require(ctx, Role.ADMIN)
            return users_page(conn, request)
        return await handle(request, work)

    @app.post("/ops/admin/users")
    async def ops_users_create(request: Request):
        def work(conn, ctx, form):
            require(ctx, Role.ADMIN)
            try:
                out = admin_users.create_user(conn, actor_id=ctx.principal.user_id, actor_role=ctx.principal.role,
                                              email=str(form.get("email", "")),
                                              display_name=str(form.get("display_name", "")),
                                              role=str(form.get("role", "")),
                                              client_tenant=str(form.get("client_tenant", "")) or None,
                                              staff_tenants=form.getlist("staff_tenants"))
            except admin_users.AdminError as e:
                return users_page(conn, request, error=str(e), status=400)
            return users_page(conn, request, invite=out["invite_path"],
                              notice=f"User {out['user_id']} created. Give them the one-time link below.")
        return await handle(request, work, form=True)

    @app.post("/ops/admin/users/{user_id}/{op}")
    async def ops_users_op(request: Request, user_id: str, op: str):
        def work(conn, ctx, form):
            require(ctx, Role.ADMIN)
            who = dict(actor_id=ctx.principal.user_id, actor_role=ctx.principal.role, user_id=user_id)
            invite, notice = None, None
            try:
                if op == "deactivate":
                    n = admin_users.deactivate(conn, **who, reason=str(form.get("reason", "")))
                    notice = f"{user_id} deactivated; {n} session(s) ended."
                elif op == "reset":
                    out = admin_users.reset_signin(conn, **who)
                    invite, notice = out["invite_path"], f"Sign-in reset for {user_id}. Give them the new link."
                elif op == "revoke":
                    notice = f"{admin_users.revoke_sessions(conn, **who)} session(s) ended for {user_id}."
                elif op == "unlock":
                    admin_users.unlock(conn, **who)
                    notice = f"{user_id} unlocked."
                elif op == "access":
                    new = admin_users.set_staff_access(conn, **who, tenants=form.getlist("staff_tenants"))
                    notice = f"Client access for {user_id}: {', '.join(new) or 'none'}."
                else:
                    raise HttpError(404, "Unknown user action.")
            except admin_users.AdminError as e:
                return users_page(conn, request, error=str(e), status=400)
            except admin_users.AdminForbidden as e:
                return users_page(conn, request, error=str(e), status=403)
            return users_page(conn, request, notice=notice, invite=invite)
        return await handle(request, work, form=True)

    # ------------------------------------------------------------ /client (CLIENT_VIEWER, own tenant only)
    def client_only(ctx: Ctx) -> str:
        if ctx.principal.role != Role.CLIENT_VIEWER or not ctx.principal.home_tenant_id:
            raise HttpError(403, "The client portal is for client users.")
        return ctx.principal.home_tenant_id

    def client_read(conn, ctx: Ctx, tenant_id: str, case_id: str, surface: str) -> None:
        """R-39: every client page view of a case and every download is an audit event."""
        p = ctx.principal
        with conn.transaction():
            append_event(conn, tenant_id=tenant_id, case_id=case_id, event_type="CASE_READ",
                         actor_type=ActorType.HUMAN, actor_id=p.user_id, actor_role=p.role.value,
                         payload={"user_id": p.user_id, "role": p.role.value, "detail": {"surface": surface}})

    def client_case_or_404(conn, ctx: Ctx, request: Request, t: str, case_id: str) -> dict:
        s = portal.case_summary(conn, tenant_id=t, case_id=case_id)
        if s is None:
            access_denied(conn, ctx, request, tenant_id=None, case_id=case_id)
            raise HttpError(404, "No such case.")
        return s

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
            s = client_case_or_404(conn, ctx, request, t, case_id)
            case = repo.get_case(conn, tenant_id=t, case_id=case_id)
            client_read(conn, ctx, t, case_id, "client_case_view")
            return Page("client_case.html", {"c": s, "timeline": portal.client_timeline(
                                                 views.timeline(conn, case, client_view=True)),
                                             "ruler": views.deadline_ruler(case)})
        return await handle(request, work)

    @app.get("/client/cases/{case_id}/export.{fmt}")
    async def client_export(request: Request, case_id: str, fmt: str):
        def work(conn, ctx):
            t = client_only(ctx)
            s = client_case_or_404(conn, ctx, request, t, case_id)
            if not s["completed"]:
                raise HttpError(404, "The audit export is available once the case is completed.")
            if fmt not in ("json", "html"):
                raise HttpError(404, "Export format must be json or html.")
            client_read(conn, ctx, t, case_id, f"client_export.{fmt}")
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
