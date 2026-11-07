"""Operator CLI. OWNER: platform-core.  Usage: `python -m disputes.cli <command> [options]`

    migrate                      create the database if missing, apply migrations
    seed-demo                    synthetic tenants, demo users (needs disputes.web.auth), staff access
    ingest --tenant T --fixtures DIR [--fixture-dates]
                                 enqueue one process_dispute job per line of DIR/acdvs.jsonl; the
                                 tenant's system of record is DIR/sor_accounts.jsonl
    work [--no-wait] [--max-jobs N]
                                 run the worker until the queue is empty
    verify [--anchor-dir D] [--case CASE --tenant T]
                                 recompute the audit chains (exit 1 if broken)
    anchor [--anchor-dir D]      write a write-once anchor of the global head
    backup --out FILE            pg_dump -Fc of the database
    restore --file FILE --target-db NAME
                                 create NAME and pg_restore FILE into it

Settings come from `disputes.config.settings()` (DISPUTES_DATABASE_URL, DISPUTES_ANCHOR_DIR, ...);
`--database-url` overrides. Everything is SYNTHETIC.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from disputes.config import defaults, settings

DEMO_TENANTS = (("synthetic-tenant-0", "Example Fintech Lender (SYNTHETIC)"),
                ("synthetic-tenant-1", "Example Auto Finance (SYNTHETIC)"))
DEMO_STAFF = (("u-specialist-1", "SPECIALIST", "Demo Specialist One (SYNTHETIC)"),
              ("u-specialist-2", "SPECIALIST", "Demo Specialist Two (SYNTHETIC)"),
              ("u-supervisor-1", "SUPERVISOR", "Demo Supervisor One (SYNTHETIC)"),
              ("u-supervisor-2", "SUPERVISOR", "Demo Supervisor Two (SYNTHETIC)"),
              ("u-admin-1", "ADMIN", "Demo Admin (SYNTHETIC)"),
              ("u-auditor-1", "AUDITOR", "Demo Auditor (SYNTHETIC)"))
PG_BIN_DEFAULT = "/usr/lib/postgresql/16/bin"


def _pg_bin(name: str) -> str:
    d = os.environ.get("PGBIN", PG_BIN_DEFAULT)
    p = Path(d) / name
    return str(p) if p.exists() else (shutil.which(name) or name)


def _dbname(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def _with_db(url: str, dbname: str) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, "/" + dbname, u.query, u.fragment))


def _create_database(url: str, *, if_missing: bool = True) -> bool:
    name = _dbname(url)
    with psycopg.connect(_with_db(url, "postgres"), autocommit=True) as a:
        exists = a.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if exists:
            if if_missing:
                return False
            raise SystemExit(f"database {name} already exists; refusing to restore over it")
        a.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
            sql.Identifier(name)))
        return True


# ------------------------------------------------------------------------ commands
def cmd_migrate(url: str, args) -> int:
    from disputes.db.core import connect, migrate
    created = _create_database(url)
    with connect(url) as c:
        applied = migrate(c)
        c.commit()
    print(json.dumps({"database_created": created, "applied": applied}))
    return 0


def _web_auth():
    try:
        from disputes.web.auth import hash_password, new_totp_secret
        return hash_password, new_totp_secret
    except (ImportError, AttributeError):
        return None


def seed_demo(conn, *, password: str | None = None) -> dict:
    """Tenants always; users + staff access only if disputes.web.auth provides hashing/TOTP."""
    from disputes.audit.chain import append_event
    from disputes.db.core import ensure_tenant
    from disputes.domain import ActorType
    out: dict = {"tenants": [t for t, _ in DEMO_TENANTS], "users": [], "skipped_users": None}
    with conn.transaction():
        for tid, name in DEMO_TENANTS:
            ensure_tenant(conn, tid, name, synthetic=True)
    auth = _web_auth()
    if auth is None:
        out["skipped_users"] = ("disputes.web.auth.hash_password / new_totp_secret not available yet "
                                "(web module); tenants seeded, users skipped")
        return out
    hash_password, new_totp_secret = auth
    password = password or os.environ.get("DISPUTES_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    users = [(uid, role, name, None) for uid, role, name in DEMO_STAFF]
    users += [(f"u-client-{i}", "CLIENT_VIEWER", f"Demo Client Viewer {i} (SYNTHETIC)", tid)
              for i, (tid, _) in enumerate(DEMO_TENANTS)]
    with conn.transaction():
        for uid, role, name, tid in users:
            totp = new_totp_secret()
            row = conn.execute(
                "INSERT INTO users (user_id, email, display_name, role, tenant_id, password_hash, totp_secret) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING RETURNING user_id",
                (uid, f"{uid}@demo.invalid", name, role, tid, hash_password(password), totp)).fetchone()
            if row is None:
                continue
            out["users"].append({"user_id": uid, "email": f"{uid}@demo.invalid", "role": role, "tenant_id": tid,
                                 "totp_secret": totp})
            append_event(conn, tenant_id=tid or "ops", case_id=None, event_type="USER_CREATED",
                         actor_type=ActorType.SYSTEM, actor_id="system:seed-demo", actor_role=None,
                         payload={"user_id": uid, "role": role, "tenant_id": tid, "synthetic": True})
        for uid, role, _, _ in users:
            if role == "CLIENT_VIEWER":
                continue
            for tid, _ in DEMO_TENANTS:
                conn.execute("INSERT INTO staff_tenant_access (user_id, tenant_id) VALUES (%s,%s) "
                             "ON CONFLICT DO NOTHING", (uid, tid))
    out["password"] = password if out["users"] else None
    return out


def cmd_seed_demo(url: str, args) -> int:
    from disputes.db.core import connect
    with connect(url) as c:
        out = seed_demo(c, password=args.password)
    if out.get("skipped_users"):
        print("NOTE: " + out["skipped_users"], file=sys.stderr)
    print(json.dumps(out, indent=2))
    return 0


def ingest(conn, *, tenant_id: str, fixtures_dir, fixture_dates: bool = False) -> dict:
    from disputes.workflow import jobs
    d = Path(fixtures_dir).resolve()
    acdvs, sor = d / "acdvs.jsonl", d / "sor_accounts.jsonl"
    if not acdvs.exists() or not sor.exists():
        raise SystemExit(f"{d} must contain acdvs.jsonl and sor_accounts.jsonl")
    with conn.transaction():
        if conn.execute("SELECT 1 FROM tenants WHERE tenant_id = %s", (tenant_id,)).fetchone() is None:
            raise SystemExit(f"unknown tenant {tenant_id}; run seed-demo first")
    n = 0
    with acdvs.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            env = json.loads(line)
            payload = {"envelope": env, "sor_path": str(sor)}
            meta = env.get("fixture_meta") or {}
            if fixture_dates and meta.get("ingest_date"):
                payload["as_of"] = f"{meta['ingest_date']}T15:00:00+00:00"
            jobs.enqueue(conn, tenant_id=tenant_id, kind="process_dispute", payload=payload)
            n += 1
    return {"tenant_id": tenant_id, "enqueued": n, "sor": str(sor)}


def cmd_ingest(url: str, args) -> int:
    from disputes.db.core import connect
    with connect(url) as c:
        print(json.dumps(ingest(c, tenant_id=args.tenant, fixtures_dir=args.fixtures,
                                fixture_dates=args.fixture_dates)))
    return 0


def cmd_work(url: str, args) -> int:
    from disputes.db.core import connect
    from disputes.workflow.worker import run_worker
    cfg = defaults()
    try:
        from disputes.rules.gate import check_tables
        check_tables(cfg)
    except NotImplementedError:
        print("WARNING: rules.gate.check_tables not implemented yet; R-35 gate skipped", file=sys.stderr)
    with connect(url) as c:
        stats = run_worker(c, cfg=cfg, max_jobs=args.max_jobs, wait_for_backoff=not args.no_wait)
    print(json.dumps(stats))
    return 0


def cmd_verify(url: str, args) -> int:
    from disputes.audit.verify import verify_all, verify_case
    from disputes.db.core import connect
    with connect(url) as c:
        if args.case:
            if not args.tenant:
                raise SystemExit("--case needs --tenant")
            res = verify_case(c, tenant_id=args.tenant, case_id=args.case)
        else:
            res = verify_all(c, anchor_dir=args.anchor_dir or settings().anchor_dir)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def cmd_anchor(url: str, args) -> int:
    from disputes.audit.anchor import write_anchor
    from disputes.db.core import connect
    with connect(url) as c:
        print(json.dumps(write_anchor(c, args.anchor_dir or settings().anchor_dir)))
    return 0


def backup(url: str, out_file) -> dict:
    out = Path(out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_pg_bin("pg_dump"), "--format=custom", "--no-owner", f"--file={out}", f"--dbname={url}"],
                   check=True, capture_output=True, text=True)
    return {"file": str(out), "bytes": out.stat().st_size}


def restore(url: str, in_file, target_db: str) -> dict:
    target = _with_db(url, target_db)
    _create_database(target, if_missing=False)
    subprocess.run([_pg_bin("pg_restore"), "--no-owner", "--exit-on-error", f"--dbname={target}", str(in_file)],
                   check=True, capture_output=True, text=True)
    return {"restored_to": target_db}


def cmd_backup(url: str, args) -> int:
    print(json.dumps(backup(url, args.out)))
    return 0


def cmd_restore(url: str, args) -> int:
    print(json.dumps(restore(url, args.file, args.target_db)))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="disputes.cli", description="Disputes platform operator CLI (SYNTHETIC)")
    p.add_argument("--database-url", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    s = sub.add_parser("seed-demo")
    s.add_argument("--password", default=None)
    s = sub.add_parser("ingest")
    s.add_argument("--tenant", required=True)
    s.add_argument("--fixtures", required=True)
    s.add_argument("--fixture-dates", action="store_true",
                   help="use each fixture's ingest_date as the pipeline clock (replay)")
    s = sub.add_parser("work")
    s.add_argument("--max-jobs", type=int, default=None)
    s.add_argument("--no-wait", action="store_true", help="do not wait for jobs in backoff")
    s = sub.add_parser("verify")
    s.add_argument("--anchor-dir", default=None)
    s.add_argument("--case", default=None)
    s.add_argument("--tenant", default=None)
    s = sub.add_parser("anchor")
    s.add_argument("--anchor-dir", default=None)
    s = sub.add_parser("backup")
    s.add_argument("--out", required=True)
    s = sub.add_parser("restore")
    s.add_argument("--file", required=True)
    s.add_argument("--target-db", required=True)
    args = p.parse_args(argv)
    url = args.database_url or settings().database_url
    handlers = {"migrate": cmd_migrate, "seed-demo": cmd_seed_demo, "ingest": cmd_ingest, "work": cmd_work,
                "verify": cmd_verify, "anchor": cmd_anchor, "backup": cmd_backup, "restore": cmd_restore}
    return handlers[args.cmd](url, args)


if __name__ == "__main__":
    sys.exit(main())
