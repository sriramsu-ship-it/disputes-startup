"""FastAPI app factory. OWNER: web agent.

Two surfaces (managed-service model, DECISIONS 2026-11-07):
- /ops: our analysts' workbench (queue R-16, case view, actions R-17, second approval R-19,
  package R-20, export R-22, instrumentation R-24, admin config R-21).
- /client: the furnisher client's portal (CLIENT_VIEWER, own tenant only): volumes, SLA status,
  outcomes, audit-export downloads.
Server-rendered Jinja2 + minimal JS (ADR-001). AuthN: local accounts + TOTP MFA (R-18).
"""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    raise NotImplementedError
