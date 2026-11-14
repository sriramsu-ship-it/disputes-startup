#!/usr/bin/env python3
"""End-to-end smoke test of a running demo stack (SYNTHETIC). Standard library only.

    python scripts/smoke_test.py [--base-url http://127.0.0.1:8000] [--email E --password P]
                                 [--expect-cases N] [--timeout S]

Checks, in order (exit 1 on the first failure, with a one-line reason):
  1. GET /healthz -> 200;  GET /readyz -> 200 (DB reachable, migrations applied)
  2. GET /login -> 200 and contains the login form
  3. (with --email/--password) log in; the MFA code is read from the page (local dev mode only,
     DISPUTES_DEV_SHOW_TOTP=1); GET /ops -> the analyst queue renders
  4. (with --expect-cases N) the queue page lists at least N case links within --timeout seconds
     (proves the worker processed the synthetic disputes)
Inside the compose stack:  docker compose exec -T web python - < scripts/smoke_test.py  (see demo.sh).
"""
from __future__ import annotations

import argparse
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class Fail(Exception):
    pass


def opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(op, url, timeout=10):
    try:
        with op.open(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url


def post(op, url, data: dict, timeout=10):
    body = urllib.parse.urlencode(data).encode()
    try:
        with op.open(urllib.request.Request(url, data=body, method="POST"), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url


def hidden_inputs(html: str) -> dict:
    out = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', html):
        n, v = re.search(r'name="([^"]+)"', m.group(0)), re.search(r'value="([^"]*)"', m.group(0))
        if n:
            out[n.group(1)] = v.group(1) if v else ""
    return out


def wait_ready(op, base, timeout):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        try:
            s, body, _ = get(op, base + "/readyz", timeout=5)
            if s == 200:
                return
            last = f"{s} {body[:80]}"
        except (urllib.error.URLError, OSError) as e:
            last = type(e).__name__
        time.sleep(1)
    raise Fail(f"/readyz not 200 after {timeout}s (last: {last})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--expect-cases", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args(argv)
    base, op = a.base_url.rstrip("/"), opener()
    try:
        wait_ready(op, base, a.timeout)
        s, body, _ = get(op, base + "/healthz")
        if s != 200 or '"ok"' not in body:
            raise Fail(f"/healthz returned {s}")
        print("ok   /healthz 200, /readyz 200")
        s, body, _ = get(op, base + "/login")
        if s != 200 or 'name="password"' not in body:
            raise Fail(f"/login returned {s} or has no password field")
        print("ok   /login renders the sign-in form")
        if a.email:
            s, body, url = post(op, base + "/login", {"email": a.email, "password": a.password or "",
                                                       **hidden_inputs(body)})
            if s != 200 or "/login/mfa" not in url:
                raise Fail(f"password step failed (HTTP {s}, ended at {urllib.parse.urlsplit(url).path})")
            m = re.search(r'data-testid="dev-totp"[^>]*>.*?<strong>(\d{6})</strong>', body, re.S)
            if not m:
                raise Fail("MFA page shows no dev code (is DISPUTES_DEV_SHOW_TOTP=1 and DISPUTES_ENV=dev?)")
            s, body, url = post(op, base + "/login/mfa", {"code": m.group(1), **hidden_inputs(body)})
            if s != 200 or "/ops" not in url:
                raise Fail(f"MFA step failed (HTTP {s}, ended at {urllib.parse.urlsplit(url).path})")
            print(f"ok   signed in as {a.email}; landed on {urllib.parse.urlsplit(url).path}")
            if a.expect_cases:
                deadline, n = time.time() + a.timeout, 0
                while time.time() < deadline:
                    s, body, url = get(op, base + "/ops")
                    n = len(set(re.findall(r'href="(/ops/t/[^/"]+/cases/[^"/?]+)"', body)))
                    if s == 200 and n >= a.expect_cases:
                        break
                    time.sleep(2)
                if n < a.expect_cases:
                    raise Fail(f"queue lists {n} cases after {a.timeout}s, expected >= {a.expect_cases}")
                print(f"ok   analyst queue lists {n} processed synthetic cases")
    except Fail as e:
        print(f"FAIL {e}")
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"FAIL cannot reach {base}: {type(e).__name__}")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
