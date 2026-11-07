"""Foundation tests: migrations, audit chain append, state machine, repository, guards."""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from disputes.audit.chain import GENESIS, append_event, event_body, sha256_hex
from disputes.db import repo
from disputes.db.core import migrate
from disputes.domain import ActorType, ArtifactKind, CaseState, Category, Role, to_jsonable
from disputes.workflow.state_machine import Forbidden, IllegalTransition, transition

SRC = Path(__file__).resolve().parents[1]
PLATFORM = SRC / "disputes"


def _case(conn, tenant, case_id="CASE-1", control="CN-1"):
    with conn.transaction():
        return repo.insert_case(conn, tenant_id=tenant, case={
            "case_id": case_id, "channel": "ACDV", "control_number": control, "account_number": "SYNACCT1",
            "account_last4": "CT1", "date_received": date(2026, 10, 1), "state": CaseState.RECEIVED.value,
            "raw_payload_sha256": "0" * 64, "synthetic": True})


def test_migrate_is_idempotent(conn):
    assert migrate(conn) == []


def test_append_event_builds_both_chains(conn, tenant):
    _case(conn, tenant)
    with conn.transaction():
        e1 = append_event(conn, tenant_id=tenant, case_id="CASE-1", event_type="T", actor_type=ActorType.SYSTEM,
                          actor_id="system", actor_role=None, payload={"a": 1})
        e2 = append_event(conn, tenant_id=tenant, case_id=None, event_type="ADMIN", actor_type=ActorType.HUMAN,
                          actor_id="u1", actor_role="ADMIN", payload={"b": 2})
        e3 = append_event(conn, tenant_id=tenant, case_id="CASE-1", event_type="T", actor_type=ActorType.SYSTEM,
                          actor_id="system", actor_role=None, payload={"a": 3})
    rows = conn.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
    assert [r["event_id"] for r in rows] == [e1["event_id"], e2["event_id"], e3["event_id"]]
    assert rows[0]["case_prev_hash"] == GENESIS and rows[0]["global_prev_hash"] == GENESIS
    assert rows[1]["case_hash"] is None and rows[1]["global_prev_hash"] == rows[0]["global_hash"]
    assert rows[2]["case_prev_hash"] == rows[0]["case_hash"]
    assert rows[2]["global_prev_hash"] == rows[1]["global_hash"]
    # recompute event 1 from stored columns
    r = rows[0]
    from disputes.audit.chain import rfc3339
    body = event_body(tenant_id=r["tenant_id"], case_id=r["case_id"], event_type=r["event_type"],
                      actor_type=r["actor_type"], actor_id=r["actor_id"], actor_role=r["actor_role"],
                      occurred_at=rfc3339(r["occurred_at"]), payload_sha256=r["payload_sha256"])
    assert r["case_hash"] == sha256_hex(GENESIS + body)


def test_append_event_requires_transaction(conn, tenant):
    conn.commit()
    with pytest.raises(RuntimeError):
        append_event(conn, tenant_id=tenant, case_id=None, event_type="X", actor_type=ActorType.SYSTEM,
                     actor_id="s", actor_role=None, payload={})


def test_state_machine_happy_path_and_guards(conn, tenant):
    _case(conn, tenant)
    sys_actor = dict(actor_type=ActorType.SYSTEM, actor_id="system")
    transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.CLASSIFIED, **sys_actor)
    with pytest.raises(IllegalTransition):
        transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.APPROVED, **sys_actor)
    transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.ESCALATED, reason="CLASS_CONFLICT", **sys_actor)
    with pytest.raises(Forbidden):
        transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.IN_REVIEW,
                   actor_type=ActorType.HUMAN, actor_id="u1", actor_role=Role.SPECIALIST)
    with pytest.raises(Forbidden):
        transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.IN_REVIEW,
                   actor_type=ActorType.HUMAN, actor_id="c1", actor_role=Role.CLIENT_VIEWER)
    row = transition(conn, tenant_id=tenant, case_id="CASE-1", to=CaseState.IN_REVIEW,
                     actor_type=ActorType.HUMAN, actor_id="u2", actor_role=Role.SUPERVISOR)
    assert row["state"] == "IN_REVIEW" and row["version"] == 4
    evs = repo.audit_events_for_case(conn, tenant_id=tenant, case_id="CASE-1")
    assert [e["payload"]["to"] for e in evs] == ["CLASSIFIED", "ESCALATED", "IN_REVIEW"]


def test_artifacts_are_versioned(conn, tenant):
    _case(conn, tenant)
    with conn.transaction():
        a1 = repo.put_artifact(conn, tenant_id=tenant, case_id="CASE-1", kind=ArtifactKind.DRAFT,
                               data={"s": [1]}, created_by="system")
        a2 = repo.put_artifact(conn, tenant_id=tenant, case_id="CASE-1", kind=ArtifactKind.DRAFT,
                               data={"s": [2]}, created_by="u1")
    assert (a1["version"], a2["version"]) == (1, 2)
    assert repo.latest_artifact(conn, tenant_id=tenant, case_id="CASE-1", kind="draft")["data"] == {"s": [2]}
    assert len(repo.artifact_history(conn, tenant_id=tenant, case_id="CASE-1")) == 2


def test_tenant_isolation_in_repo(conn, tenant):
    from disputes.db.core import ensure_tenant
    ensure_tenant(conn, "synthetic-tenant-1", "Other client (SYNTHETIC)")
    _case(conn, tenant)
    with pytest.raises(repo.NotFound):
        repo.get_case(conn, tenant_id="synthetic-tenant-1", case_id="CASE-1")
    assert repo.list_cases(conn, tenant_id="synthetic-tenant-1") == []


def test_every_repo_query_is_tenant_scoped():
    """ADR-008: every SQL string in db/repo.py that touches a tenant table names tenant_id."""
    src = (PLATFORM / "db" / "repo.py").read_text()
    tree = ast.parse(src)
    sqls = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", n.value)]
    assert sqls
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        body = ast.get_source_segment(src, fn)
        if re.search(r"\b(SELECT .* FROM|INSERT INTO|UPDATE) ", body):
            assert "tenant_id" in body, fn.name


def test_platform_never_imports_synthgen_or_labels():
    for p in PLATFORM.rglob("*.py"):
        text = p.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any(n.startswith("synthgen") for n in names), p
        assert "labels.jsonl" not in text and "HIDDEN" not in text, p


def test_to_jsonable_sorts_sets():
    assert to_jsonable({"c": frozenset({Category.OTHER, Category.BALANCE})}) == {"c": ["BALANCE", "OTHER"]}
