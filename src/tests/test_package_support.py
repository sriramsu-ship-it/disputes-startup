"""Helpers for the package tests (no tests here). Data is SYNTHETIC."""
from __future__ import annotations

from html.parser import HTMLParser


class _ById(HTMLParser):
    """Collects, for each element with an `id`, its full text and its table rows (cells' text)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.text: dict[str, list[str]] = {}
        self.rows: dict[str, list[list[str]]] = {}
        self._row: dict[str, list[str] | None] = {}
        self._cell: dict[str, list[str] | None] = {}

    def _open_ids(self):
        return [i for _, i in self.stack if i]

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "meta", "link", "img", "input", "hr"):
            return
        i = dict(attrs).get("id")
        self.stack.append((tag, i))
        if i:
            self.text.setdefault(i, [])
            self.rows.setdefault(i, [])
        for oid in self._open_ids():
            if tag == "tr":
                self._row[oid] = []
            elif tag in ("td", "th") and self._row.get(oid) is not None:
                self._cell[oid] = []

    def handle_endtag(self, tag):
        for oid in self._open_ids():
            if tag in ("td", "th") and self._cell.get(oid) is not None:
                self._row[oid].append(" ".join("".join(self._cell[oid]).split()))
                self._cell[oid] = None
            elif tag == "tr" and self._row.get(oid) is not None:
                if self._row[oid]:
                    self.rows[oid].append(self._row[oid])
                self._row[oid] = None
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        for oid in self._open_ids():
            self.text[oid].append(data)
            if self._cell.get(oid) is not None:
                self._cell[oid].append(data)


def parse_by_id(html: str) -> tuple[dict[str, str], dict[str, list[list[str]]]]:
    p = _ById()
    p.feed(html)
    return {k: " ".join("".join(v).split()) for k, v in p.text.items()}, p.rows


def body_rows(rows: list[list[str]]) -> list[list[str]]:
    """Drop the header row (first row) of a parsed table."""
    return rows[1:]
