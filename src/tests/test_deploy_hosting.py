"""Deploy module: hosted-mode startup safety (DISPUTES_ENV=demo). Synthetic only."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from disputes.config import Settings, defaults
from disputes.hosting import UnsafeHostedConfig, enforce_hosted_safety, hosted_problems

SRC = Path(__file__).resolve().parents[1]
GOOD_SECRET = "x" * 48


def demo_settings(**kw) -> Settings:
    base = dict(database_url="postgresql://unused/none", session_secret=GOOD_SECRET, llm_backend="offline",
                anchor_dir="/tmp/x", cookie_secure=True, environment="demo")
    base.update(kw)
    return Settings(**base)


def test_safe_demo_config_passes():
    assert hosted_problems(demo_settings(), defaults(), env={}) == []
    enforce_hosted_safety(demo_settings(), defaults(), env={})


def test_dev_env_enforces_nothing():
    st = demo_settings(environment="dev", session_secret="dev-only-not-a-secret", cookie_secure=False,
                       llm_backend="anthropic")
    assert hosted_problems(st, defaults().with_overrides(mode="live"), env={"DISPUTES_DEV_SHOW_TOTP": "1"}) == []


@pytest.mark.parametrize("kw,cfg_kw,env,needle", [
    ({"session_secret": "dev-only-not-a-secret"}, {}, {}, "built-in dev default"),
    ({"session_secret": "short-secret"}, {}, {}, "shorter than 32"),
    ({"session_secret": ""}, {}, {}, "shorter than 32"),
    ({"cookie_secure": False}, {}, {}, "DISPUTES_COOKIE_SECURE"),
    ({}, {}, {"DISPUTES_DEV_SHOW_TOTP": "1"}, "DISPUTES_DEV_SHOW_TOTP"),
    ({}, {}, {"DISPUTES_DEV_SHOW_TOTP": "true"}, "DISPUTES_DEV_SHOW_TOTP"),
    ({}, {"mode": "live"}, {}, "synthetic"),
    ({"llm_backend": "anthropic"}, {}, {}, "offline"),
])
def test_each_unsafe_setting_is_refused(kw, cfg_kw, env, needle):
    st, cfg = demo_settings(**kw), defaults().with_overrides(**cfg_kw)
    problems = hosted_problems(st, cfg, env=env)
    assert len(problems) == 1 and needle in problems[0]
    with pytest.raises(UnsafeHostedConfig):
        enforce_hosted_safety(st, cfg, env=env)


def test_show_totp_zero_or_empty_is_allowed():
    for v in ("0", "", " 0 "):
        assert hosted_problems(demo_settings(), defaults(), env={"DISPUTES_DEV_SHOW_TOTP": v}) == []


def test_unknown_environment_is_refused():
    for env_name in ("prod", "Demo", "staging", ""):
        assert hosted_problems(demo_settings(environment=env_name), defaults(), env={})


def test_error_message_never_contains_the_secret():
    secret = "s3cr3t-value-that-is-too-short"
    with pytest.raises(UnsafeHostedConfig) as e:
        enforce_hosted_safety(demo_settings(session_secret=secret, cookie_secure=False), defaults(), env={})
    assert secret not in str(e.value)
    assert "DISPUTES_COOKIE_SECURE" in str(e.value)


def _cli(env_extra: dict, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), **env_extra}
    return subprocess.run([sys.executable, "-m", "disputes.cli", "--database-url",
                           "postgresql://nobody@127.0.0.1:1/none", *args],
                          cwd=SRC, env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("cmd", [("work", "--loop"), ("migrate",), ("seed-demo",), ("serve",)])
def test_cli_refuses_every_command_with_default_secret_in_demo(cmd):
    r = _cli({"DISPUTES_ENV": "demo", "DISPUTES_COOKIE_SECURE": "1"}, *cmd)
    assert r.returncode == 2, r.stderr
    assert "refusing to start" in r.stderr and "built-in dev default" in r.stderr


def test_cli_refuses_without_secure_cookie_and_with_show_totp():
    r = _cli({"DISPUTES_ENV": "demo", "DISPUTES_SESSION_SECRET": GOOD_SECRET, "DISPUTES_DEV_SHOW_TOTP": "1"},
             "work", "--loop")
    assert r.returncode == 2
    assert "DISPUTES_COOKIE_SECURE" in r.stderr and "DISPUTES_DEV_SHOW_TOTP" in r.stderr
    assert GOOD_SECRET not in r.stderr


def test_web_app_startup_refuses_unsafe_demo(monkeypatch):
    """The health router's lifespan runs the check, so uvicorn (and TestClient's startup) fails."""
    from disputes.web.app import create_app
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    monkeypatch.delenv("DISPUTES_SESSION_SECRET", raising=False)
    monkeypatch.setenv("DISPUTES_COOKIE_SECURE", "1")
    app = create_app(database_url="postgresql://nobody@127.0.0.1:1/none")
    with pytest.raises(UnsafeHostedConfig):
        with TestClient(app):
            pass


def test_web_app_startup_allows_safe_demo(monkeypatch):
    from disputes.web.app import create_app
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    monkeypatch.setenv("DISPUTES_SESSION_SECRET", GOOD_SECRET)
    monkeypatch.setenv("DISPUTES_COOKIE_SECURE", "1")
    monkeypatch.delenv("DISPUTES_DEV_SHOW_TOTP", raising=False)
    monkeypatch.setenv("DISPUTES_LLM_BACKEND", "offline")
    app = create_app(database_url="postgresql://nobody@127.0.0.1:1/none")
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200


def test_health_router_lifespan_is_merged_into_any_app(monkeypatch):
    from disputes.web.health import router
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    monkeypatch.setenv("DISPUTES_SESSION_SECRET", "dev-only-not-a-secret")
    app = FastAPI()
    app.include_router(router)
    with pytest.raises(UnsafeHostedConfig):
        with TestClient(app):
            pass
