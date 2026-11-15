"""Standalone HTML rendering of the package and the export. OWNER: package agent.

One Jinja environment over web/templates (autoescape on), with the same `tojson_pretty` filter the
web app registers, so `export.html` renders identically here and in the app. `standalone=True`
inlines package.css and drops screen-only links: used for PDF and for the zip bundle.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

WEB = Path(__file__).resolve().parent.parent / "web"
CSS_PATH = WEB / "static" / "package.css"


@lru_cache(maxsize=1)
def env() -> Environment:
    e = Environment(loader=FileSystemLoader(str(WEB / "templates")), autoescape=select_autoescape(["html"]))
    e.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, sort_keys=True, default=str, ensure_ascii=False)
    return e


@lru_cache(maxsize=1)
def css() -> Markup:
    """Our own stylesheet, trusted: marked safe here so templates never need `|safe`."""
    return Markup(CSS_PATH.read_text(encoding="utf-8"))


def render_export_html(ex: dict, *, standalone: bool = True) -> str:
    return env().get_template("export.html").render(ex=ex, standalone=standalone, css=css() if standalone else "")


def render_package_html(doc: dict, *, masked: bool, standalone: bool = True, links=None) -> str:
    return env().get_template("package.html").render(doc=doc, masked=masked, standalone=standalone,
                                                      css=css() if standalone else "", links=links)
