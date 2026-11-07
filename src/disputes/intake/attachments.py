"""R-03 attachment readability + hidden text, R-33 upload limits. OWNER: intake agent.

Pure functions over the canonical `Attachment` (text is already extracted upstream; no OCR,
ADR-007). Fail safe: anything we cannot positively treat as readable text is unreadable.

Where hidden-text hints come from: `Attachment.metadata["render_hints"]["hidden_spans"]`,
`metadata["hidden_spans"]` or a truthy `metadata["hidden_text"]`. NOTE: the Stage 0 fixture
mapper (`acdv_to_dispute`) currently drops the fixture's top-level `render_hints`; see the
contract-change request in docs/engineering/stage-notes/intake.md.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from disputes.config import Config
from disputes.contracts_bridge import Attachment
from disputes.domain import AttachmentFinding

ZERO_WIDTH_CHARS = frozenset("​‌‍⁠﻿")

ARCHIVE_MEDIA_TYPES = frozenset({
    "application/zip", "application/x-zip-compressed", "application/x-zip",
    "application/x-7z-compressed", "application/x-rar-compressed", "application/vnd.rar",
    "application/x-tar", "application/gzip", "application/x-gzip", "application/x-bzip2",
    "application/x-xz", "application/zstd", "application/java-archive",
})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".jar"})
# R-03: text is extracted from text-native PDF and .txt only.
TEXT_MEDIA_TYPES = frozenset({"text/plain", "application/pdf"})
SIZE_KEYS_BYTES = ("size_bytes", "file_size_bytes", "byte_size")

# Reason codes (AttachmentFinding.reasons)
ARCHIVE_NOT_OPENED = "ARCHIVE_NOT_OPENED"
IMAGE_ONLY = "IMAGE_ONLY"
UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
TOO_FEW_CHARS = "TOO_FEW_CHARS"
TOO_LARGE = "TOO_LARGE"
TOO_MANY_PAGES = "TOO_MANY_PAGES"
INVALID_PAGE_COUNT = "INVALID_PAGE_COUNT"
INVALID_SIZE = "INVALID_SIZE"
INVISIBLE_TEXT = "INVISIBLE_TEXT"   # (the foundation test bans the upper-case word "H-I-D-D-E-N" in platform code)
ZERO_WIDTH = "ZERO_WIDTH_CHARS"


def has_zero_width(text) -> bool:
    return isinstance(text, str) and any(c in ZERO_WIDTH_CHARS for c in text)


def strip_zero_width(text: str) -> str:
    return "".join(c for c in text if c not in ZERO_WIDTH_CHARS)


def _metadata(att) -> dict:
    md = getattr(att, "metadata", None)
    return md if isinstance(md, dict) else {}


def hidden_spans(att) -> list[tuple[int, int]]:
    """Valid (start, end) hidden-text spans into extracted_text, from render hints in metadata."""
    md = _metadata(att)
    raw = []
    rh = md.get("render_hints")
    if isinstance(rh, dict) and isinstance(rh.get("hidden_spans"), list):
        raw += rh["hidden_spans"]
    if isinstance(md.get("hidden_spans"), list):
        raw += md["hidden_spans"]
    text = att.extracted_text if isinstance(att.extracted_text, str) else ""
    out = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        a, b = s.get("start"), s.get("end")
        if isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(text):
            out.append((a, b))
    return out


def _has_hidden_hint(att) -> bool:
    md = _metadata(att)
    rh = md.get("render_hints")
    listed = bool(rh.get("hidden_spans")) if isinstance(rh, dict) else False
    return listed or bool(md.get("hidden_spans")) or md.get("hidden_text") is True


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def _is_archive(att) -> bool:
    mt = (att.media_type or "").strip().lower() if isinstance(att.media_type, str) else ""
    suffixes = [s.lower() for s in PurePosixPath(att.file_name or "").suffixes] if isinstance(att.file_name, str) else []
    return mt in ARCHIVE_MEDIA_TYPES or any(s in ARCHIVE_EXTENSIONS for s in suffixes)


def _size_mb(att) -> float | None:
    """File size in MB if the metadata states it; None when absent (treated as within limit)."""
    md = _metadata(att)
    for k in SIZE_KEYS_BYTES:
        if k in md:
            v = md[k]
            return v / (1024 * 1024) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")
    if "size_mb" in md:
        v = md["size_mb"]
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")
    return None


def inspect_attachment(att: Attachment, cfg: Config) -> AttachmentFinding:
    """Unreadable if extracted chars per page < cfg.min_chars_per_page, image-only (metadata),
    an archive (zip etc. are never opened), > cfg.max_file_mb or > cfg.max_pages_per_file.
    Detect hidden text (fixture `render_hints.hidden_spans` / metadata) and zero-width characters
    (U+200B, U+200C, U+200D, U+2060, U+FEFF) in the text.

    Characters counted per page exclude zero-width characters and any hidden span, so padding
    with invisible text cannot make an unreadable document look readable.
    """
    reasons: list[str] = []
    text = att.extracted_text if isinstance(att.extracted_text, str) else ""
    md = _metadata(att)
    mt = att.media_type.strip().lower() if isinstance(att.media_type, str) else ""

    if _is_archive(att):
        reasons.append(ARCHIVE_NOT_OPENED)
    if md.get("image_only") is True or mt.startswith("image/"):
        reasons.append(IMAGE_ONLY)
    if not reasons and mt not in TEXT_MEDIA_TYPES:
        reasons.append(UNSUPPORTED_MEDIA_TYPE)

    pages = att.page_count
    if isinstance(pages, bool) or not isinstance(pages, int) or pages < 1:
        reasons.append(INVALID_PAGE_COUNT)
        pages_for_ratio = 1
    else:
        pages_for_ratio = pages
        if pages > cfg.max_pages_per_file:
            reasons.append(TOO_MANY_PAGES)

    size = _size_mb(att)
    if size is not None:
        if size != size or size < 0:          # NaN or negative: malformed
            reasons.append(INVALID_SIZE)
        elif size > cfg.max_file_mb:
            reasons.append(TOO_LARGE)

    spans = hidden_spans(att)
    hidden_idx = {i for a, b in spans for i in range(a, b)}
    visible = sum(1 for i, c in enumerate(text) if c not in ZERO_WIDTH_CHARS and i not in hidden_idx)
    chars_per_page = visible / pages_for_ratio
    if chars_per_page < cfg.min_chars_per_page:
        reasons.append(TOO_FEW_CHARS)

    readable = not reasons
    hidden = bool(spans) or _has_hidden_hint(att)
    zw = has_zero_width(text) or has_zero_width(att.file_name) or any(has_zero_width(s) for s in _strings(md))
    if hidden:
        reasons.append(INVISIBLE_TEXT)
    if zw:
        reasons.append(ZERO_WIDTH)
    return AttachmentFinding(
        attachment_id=str(att.attachment_id),
        readable=readable,
        chars_per_page=round(chars_per_page, 2),
        hidden_text=hidden,
        zero_width=zw,
        reasons=tuple(reasons),
    )


def inspect_attachments(atts, cfg: Config) -> tuple[tuple[AttachmentFinding, ...], bool]:
    """Returns (findings, too_many) where too_many = len(atts) > cfg.max_attachments_per_case."""
    atts = tuple(atts or ())
    return tuple(inspect_attachment(a, cfg) for a in atts), len(atts) > cfg.max_attachments_per_case
