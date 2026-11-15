"""HTML -> PDF with a headless Chromium binary. OWNER: package agent.

Why a browser and not a PDF library: R-22 asks for the PDF to be rendered from the same HTML as
the on-screen export, and a browser's print engine is the only thing that guarantees that. No new
Python dependency is added; the binary is an operational prerequisite of the host.

Binary search order: $DISPUTES_PDF_BROWSER, then chrome-headless-shell (Playwright's build under
/opt/pw-browsers or $PLAYWRIGHT_BROWSERS_PATH), then chromium / chromium-browser / google-chrome on
PATH. If none is found, `PdfUnavailable` is raised and the routes answer 503 with a plain message
(the HTML export prints to PDF from any browser). The demo Docker image has no browser yet: see
docs/engineering/stage-notes/package.md.

Hardening: the HTML is our own autoescaped rendering with the stylesheet inlined and no external
references and a `default-src 'none'` CSP meta tag (no scripts, no fetches; the browser's own
`--blink-settings=scriptEnabled=false` switch breaks print-to-pdf in Chromium 140+, so CSP is used); the browser gets a black-hole proxy so it cannot reach any
network; a throwaway profile directory; a hard timeout. `--no-sandbox` is passed because the demo
runs as root or in containers without user namespaces (stated risk in the notes).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT_S = 25


class PdfUnavailable(RuntimeError):
    pass


def find_browser() -> str | None:
    env = os.environ.get("DISPUTES_PDF_BROWSER")
    if env:
        return env if Path(env).exists() else None
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/opt/pw-browsers", str(Path.home() / ".cache/ms-playwright")]
    for root in filter(None, roots):
        hits = sorted(glob.glob(os.path.join(root, "chromium_headless_shell-*", "chrome-*", "chrome-headless-shell")))
        if hits:
            return hits[-1]
    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def available() -> bool:
    return find_browser() is not None


def html_to_pdf(html: str, *, timeout_s: int = TIMEOUT_S) -> bytes:
    browser = find_browser()
    if browser is None:
        raise PdfUnavailable("No headless Chromium found for PDF rendering. Open the HTML export and use the "
                             "browser's Print > Save as PDF, or set DISPUTES_PDF_BROWSER.")
    with tempfile.TemporaryDirectory(prefix="disputes-pdf-") as tmp:
        src, out = Path(tmp) / "doc.html", Path(tmp) / "doc.pdf"
        src.write_text(html, encoding="utf-8")
        args = [browser, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--no-first-run", "--disable-extensions", "--disable-background-networking",
                "--proxy-server=http://127.0.0.1:9",
                "--proxy-bypass-list=<-loopback>", f"--user-data-dir={tmp}/profile", "--no-pdf-header-footer",
                f"--print-to-pdf={out}", src.as_uri()]
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as e:
            raise PdfUnavailable(f"PDF rendering timed out after {timeout_s} s") from e
        if not out.exists() or out.stat().st_size == 0:
            raise PdfUnavailable("PDF rendering produced no output")
        data = out.read_bytes()
    if not data.startswith(b"%PDF"):
        raise PdfUnavailable("PDF renderer returned something that is not a PDF")
    return data
