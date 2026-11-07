"""R-03 attachment readability + hidden text, R-33 upload limits. OWNER: intake agent."""
from __future__ import annotations

from disputes.config import Config
from disputes.contracts_bridge import Attachment
from disputes.domain import AttachmentFinding


def inspect_attachment(att: Attachment, cfg: Config) -> AttachmentFinding:
    """Unreadable if extracted chars per page < cfg.min_chars_per_page, image-only (metadata),
    an archive (zip etc. are never opened), > cfg.max_file_mb or > cfg.max_pages_per_file.
    Detect hidden text (fixture `render_hints.hidden_spans` / metadata) and zero-width characters
    (U+200B, U+200C, U+200D, U+2060, U+FEFF) in the text.
    """
    raise NotImplementedError


def inspect_attachments(atts, cfg: Config) -> tuple[tuple[AttachmentFinding, ...], bool]:
    """Returns (findings, too_many) where too_many = len(atts) > cfg.max_attachments_per_case."""
    raise NotImplementedError
