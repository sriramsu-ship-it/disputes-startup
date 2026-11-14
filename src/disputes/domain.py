"""Shared domain contract for the disputes platform (ADR-011).

Every module (intake, rules, agents, workflow, web) speaks these types. Changing a
name or field here is a cross-module change: open a PR that touches only this file
and say which modules it affects. PRD references: docs/product/prd-mvp-v0.md §6.

Pure data only: no I/O, no imports from other `disputes` modules.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum


# --------------------------------------------------------------------------- enums
class CaseState(StrEnum):
    """PRD §6 'Case states'. Transitions live in workflow/state_machine.py."""
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INVESTIGATING = "INVESTIGATING"
    DRAFT_READY = "DRAFT_READY"
    ESCALATED = "ESCALATED"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_SECOND_APPROVAL = "AWAITING_SECOND_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED_STUB = "SUBMITTED_STUB"


class EscalationReason(StrEnum):
    """PRD §6 closed list. Order here is not precedence."""
    INTAKE_INVALID = "INTAKE_INVALID"
    DOC_UNREADABLE = "DOC_UNREADABLE"
    BREACHED = "BREACHED"
    CLASS_CONFLICT = "CLASS_CONFLICT"
    ID_FRAUD_SUSPECTED = "ID_FRAUD_SUSPECTED"
    MULTI_ISSUE = "MULTI_ISSUE"
    MONTHS_UNDETERMINED = "MONTHS_UNDETERMINED"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    CLAIM_UNRESOLVED = "CLAIM_UNRESOLVED"
    QUOTE_UNLOCATED = "QUOTE_UNLOCATED"
    UNADDRESSED_CLAIM = "UNADDRESSED_CLAIM"
    DRAFT_INVALID = "DRAFT_INVALID"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    SYSTEM_ERROR = "SYSTEM_ERROR"          # fail-safe: unexpected pipeline/job failure (platform-core; PM to add to PRD list)


class Category(StrEnum):
    """R-06 closed enum, plus UNCERTAIN (LLM only)."""
    PAYMENT_HISTORY = "PAYMENT_HISTORY"
    BALANCE = "BALANCE"
    ACCOUNT_STATUS = "ACCOUNT_STATUS"
    IDENTITY_FRAUD = "IDENTITY_FRAUD"
    OTHER = "OTHER"
    UNCERTAIN = "UNCERTAIN"


class Route(StrEnum):
    """R-07 routing result."""
    ESCALATE_FRAUD = "ESCALATE_FRAUD"          # ESCALATED / ID_FRAUD_SUSPECTED, priority, no draft
    ESCALATE_MULTI_ISSUE = "ESCALATE_MULTI_ISSUE"
    ESCALATE_CLASS_CONFLICT = "ESCALATE_CLASS_CONFLICT"
    INVESTIGATE = "INVESTIGATE"                # exactly {PAYMENT_HISTORY}
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ClockState(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class MonthResult(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NO_DATA = "NO_DATA"


class ClaimFinding(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ADDRESSABLE = "NOT_ADDRESSABLE"


class Outcome(StrEnum):
    VERIFIED_AS_REPORTED = "VERIFIED_AS_REPORTED"
    MODIFY = "MODIFY"
    DELETE = "DELETE"          # human-only; the system never proposes it (R-10)
    ESCALATED = "ESCALATED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class SuspicionLevel(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    HIGH = "HIGH"


class NoteType(StrEnum):
    HARDSHIP = "HARDSHIP"
    DEFERRAL = "DEFERRAL"
    FORBEARANCE = "FORBEARANCE"
    PRIOR_DISPUTE = "PRIOR_DISPUTE"
    OTHER = "OTHER"


class Role(StrEnum):
    """R-18 roles, plus CLIENT_VIEWER for the managed-service client portal (DECISIONS 2026-11-07)."""
    SPECIALIST = "SPECIALIST"        # our analyst
    SUPERVISOR = "SUPERVISOR"
    ADMIN = "ADMIN"
    AUDITOR = "AUDITOR"
    CLIENT_VIEWER = "CLIENT_VIEWER"  # a furnisher client's user; read-only, own tenant only


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    EDIT = "EDIT"
    ESCALATE = "ESCALATE"
    MARK_OUT_OF_SCOPE = "MARK_OUT_OF_SCOPE"
    SECOND_APPROVE = "SECOND_APPROVE"
    REJECT_SECOND_APPROVAL = "REJECT_SECOND_APPROVAL"
    REOPEN_AFTER_SUBMISSION = "REOPEN_AFTER_SUBMISSION"


class SentenceSource(StrEnum):
    LLM = "LLM"
    TEMPLATE = "TEMPLATE"
    HUMAN = "HUMAN"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    MODEL = "MODEL"
    HUMAN = "HUMAN"


class ArtifactKind(StrEnum):
    """Versioned per-case artifacts stored in `case_artifacts` (insert-only)."""
    DISPUTE = "dispute"                 # canonical Dispute as received
    INTAKE = "intake"                   # IntakeResult
    SUSPICION = "suspicion"             # SuspicionResult
    CLASSIFICATION = "classification"   # Classification
    EVIDENCE = "evidence"               # list[Evidence]
    COMPARISON = "comparison"           # list[MonthComparison]
    CLAIMS = "claims"                   # list[Claim]
    DECISION = "decision"               # Decision
    DRAFT = "draft"                     # Draft
    REVIEW = "review"                   # ReviewRecord
    PACKAGE = "package"                 # response package (R-20)


# --------------------------------------------------------------------------- records
@dataclass(frozen=True)
class RuleFiring:
    """R-29 explainability: which rule produced an outcome or escalation, and why."""
    rule_id: str                 # e.g. "R-10.EVIDENCE_MISSING"
    rule_version: str
    result: str                  # an Outcome or EscalationReason value, or a note
    evidence_ids: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class ClockInfo:
    due_date: date
    internal_target: date
    state: ClockState
    evaluated_at: datetime
    business_days_to_target: int
    table_versions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AttachmentFinding:
    """R-03 / R-33 result for one attachment."""
    attachment_id: str
    readable: bool
    chars_per_page: float
    hidden_text: bool
    zero_width: bool
    reasons: tuple[str, ...] = ()          # e.g. ("ARCHIVE_NOT_OPENED",) or ("TOO_FEW_CHARS",)


@dataclass(frozen=True)
class SuspicionMatch:
    surface: str               # "letter_body" | "free_text" | "file_metadata" | "hidden_text" | "llm_flag"
    pattern_id: str
    level: SuspicionLevel
    excerpt: str               # short, for the reviewer


@dataclass(frozen=True)
class SuspicionResult:
    level: SuspicionLevel
    matches: tuple[SuspicionMatch, ...] = ()
    patterns_version: str = ""


@dataclass(frozen=True)
class IntakeResult:
    """Output of intake (R-02 to R-05, R-33). `escalations` empty means proceed."""
    valid: bool
    escalations: tuple[EscalationReason, ...]
    clock: ClockInfo | None
    attachment_findings: tuple[AttachmentFinding, ...]
    duplicate_of_case_id: str | None = None
    repeat_of_case_id: str | None = None
    errors: tuple[str, ...] = ()           # human-readable validation messages


@dataclass(frozen=True)
class Classification:
    """R-06. `categories` is the final set used for routing."""
    categories: frozenset[Category]
    code_categories: frozenset[Category]
    llm_categories: frozenset[Category]
    fraud_signal_sources: tuple[str, ...]  # subset of ("code_table", "keyword", "llm")
    llm_confidence: float | None           # logged, never gates
    route: Route
    escalations: tuple[EscalationReason, ...] = ()
    llm_suspicious: bool = False           # model flagged suspicious content (R-14); also on the budget


@dataclass(frozen=True)
class Evidence:
    """R-08 evidence item. `content` is JSON-serialisable."""
    evidence_id: str           # e.g. "EV-ACCOUNT", "EV-CYCLE-2026-01", "EV-NOTE-1", "EV-ATT-A1"
    kind: str                  # "account" | "cycle" (includes that month's transactions) | "profile" | "note" | "free_text_note" | "attachment" | "acdv"
    source: str                # "mock_sor" | "acdv" | ...
    retrieved_at: datetime
    sha256: str
    content: dict


@dataclass(frozen=True)
class MonthComparison:
    """R-09 per-month result."""
    month: str                 # "YYYY-MM"
    dpd: int | None
    expected_rating: str | None
    reported_rating: str | None
    result: MonthResult
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    """R-11. span is (start, end) into the source text, located by code, never by the LLM."""
    claim_id: str
    text: str
    quote: str
    source_id: str             # attachment_id or "FREE_TEXT"
    span: tuple[int, int] | None
    claim_type: str            # "DATE" | "AMOUNT" | "PAYMENT_EVENT" | "ACCOUNT_STATUS" | "AGREEMENT"
    months: tuple[str, ...] = ()
    finding: ClaimFinding | None = None
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""           # required when NOT_ADDRESSABLE


@dataclass(frozen=True)
class Correction:
    month: str
    field: str                 # "payment_rating"
    reported: str | None
    corrected: str


@dataclass(frozen=True)
class Decision:
    """R-10 output. All triggered reasons are recorded."""
    outcome: Outcome
    escalation_reasons: tuple[EscalationReason, ...]
    corrections: tuple[Correction, ...]
    firings: tuple[RuleFiring, ...]
    rules_version: str
    table_versions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DraftSentence:
    text: str
    source: SentenceSource
    template_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    quote_spans: tuple[tuple[str, int, int], ...] = ()   # (source_id, start, end)


@dataclass(frozen=True)
class Draft:
    """R-12. Outcome/corrected values come only from TEMPLATE slots filled from Decision."""
    sentences: tuple[DraftSentence, ...]
    validator_errors: tuple[str, ...] = ()
    attempts: int = 1
    valid: bool = True
    template_library_version: str = ""
    human_authored: bool = False           # reviewer-written narrative (all sentences source=HUMAN)


@dataclass(frozen=True)
class LlmCallRecord:
    """R-15/R-21/R-30/R-36: one model call, as written to the audit log."""
    model_id: str
    prompt_template_id: str
    prompt_sha256: str
    input_sha256s: tuple[str, ...]
    output: dict | None
    error: str | None
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    attempt: int


@dataclass(frozen=True)
class ReviewRecord:
    """The `review` artifact written by every reviewer action (R-17, R-19, R-20)."""
    action: str                      # ReviewAction value
    actor_id: str
    actor_role: Role
    actor_name: str
    from_state: CaseState
    to_state: CaseState
    reason_code: str | None = None   # PRD Appendix C
    reason_text: str | None = None
    working: dict | None = None      # {outcome, corrections, claim_findings, narrative}
    extra: dict = field(default_factory=dict)   # stage, first_approver, changed, ...


# --------------------------------------------------------------------------- helpers
def to_jsonable(obj):
    """Dataclasses / enums / dates / sets / tuples -> plain JSON types (sorted sets)."""
    from dataclasses import is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, StrEnum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(to_jsonable(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(to_jsonable(k)): to_jsonable(v) for k, v in obj.items()}
    return obj
