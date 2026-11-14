"""Hosted-mode startup safety (Level 1 demo, DECISIONS 2026-11-14). OWNER: deploy.

`enforce_hosted_safety()` runs before every process the container starts: every
`python -m disputes.cli` command (migrate, seed-demo, work, serve, ...) and the web app's
startup (lifespan of the health router, `web/health.py`). With `DISPUTES_ENV=demo` it refuses to
start when any of these is true:

  - the session secret is the built-in dev default, or shorter than 32 characters;
  - `DISPUTES_COOKIE_SECURE` is not 1;
  - `DISPUTES_DEV_SHOW_TOTP` is set to anything other than empty/0 (it would print MFA codes);
  - `Config.mode` is not "synthetic" (no real data in the demo);
  - the LLM backend is not "offline" (DECISIONS 2026-11-14: the stand-in model stays on until
    ZDR is confirmed in writing, ADR-006).

An unknown `DISPUTES_ENV` value also refuses to start (a typo must not silently mean "dev").
The container image sets `DISPUTES_ENV=demo` by default, so the image is safe unless someone
explicitly downgrades it to dev. In `dev` (local runs, tests) nothing is enforced.

The check never prints secret values, only which rule failed.
"""
from __future__ import annotations

import os
from typing import Mapping

from disputes.config import Config, Settings, defaults, settings

DEV_DEFAULT_SESSION_SECRET = "dev-only-not-a-secret"
MIN_SESSION_SECRET_CHARS = 32
KNOWN_ENVIRONMENTS = ("dev", "demo")
HOSTED_ENVIRONMENTS = ("demo",)


class UnsafeHostedConfig(RuntimeError):
    """Raised when a hosted environment is configured unsafely. The message lists the rules broken."""


def hosted_problems(st: Settings, cfg: Config, env: Mapping[str, str] | None = None) -> list[str]:
    """Every rule the given settings break. Empty list = safe (or not a hosted environment)."""
    env = os.environ if env is None else env
    if st.environment not in KNOWN_ENVIRONMENTS:
        return [f"DISPUTES_ENV must be one of {', '.join(KNOWN_ENVIRONMENTS)} "
                f"(got an unknown value of length {len(st.environment)})"]
    if st.environment not in HOSTED_ENVIRONMENTS:
        return []
    out = []
    secret = st.session_secret or ""
    if secret == DEV_DEFAULT_SESSION_SECRET:
        out.append("DISPUTES_SESSION_SECRET is the built-in dev default; set a random secret (Secrets Manager)")
    elif len(secret) < MIN_SESSION_SECRET_CHARS:
        out.append(f"DISPUTES_SESSION_SECRET is shorter than {MIN_SESSION_SECRET_CHARS} characters")
    if not st.cookie_secure:
        out.append("DISPUTES_COOKIE_SECURE must be 1 (cookies only over HTTPS)")
    if (env.get("DISPUTES_DEV_SHOW_TOTP") or "0").strip() not in ("", "0"):
        out.append("DISPUTES_DEV_SHOW_TOTP must be unset or 0 (it shows MFA codes on the login page)")
    if cfg.mode != "synthetic":
        out.append("Config.mode must be 'synthetic' (no real data in the demo)")
    if st.llm_backend != "offline":
        out.append("DISPUTES_LLM_BACKEND must be 'offline' in the demo (ADR-006; DECISIONS 2026-11-14)")
    return out


def enforce_hosted_safety(st: Settings | None = None, cfg: Config | None = None,
                          env: Mapping[str, str] | None = None) -> None:
    """Raise UnsafeHostedConfig if the process must not start."""
    st = st or settings()
    cfg = cfg or defaults()
    problems = hosted_problems(st, cfg, env)
    if problems:
        raise UnsafeHostedConfig(
            f"refusing to start in DISPUTES_ENV={st.environment if st.environment in KNOWN_ENVIRONMENTS else '?'}: "
            + "; ".join(problems))
