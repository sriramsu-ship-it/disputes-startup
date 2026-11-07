"""platform-core: pipeline (PRD §6 states, R-02..R-15 orchestration, R-21 audit) with fake Deps.

The fakes stand in for intake/rules/agents (built in parallel). They implement the documented
contracts just enough to drive each pipeline branch.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from disputes.audit.verify import verify_all, verify_case
from disputes.config import defaults
from disputes.contracts_bridge import Attachment, Dispute
from disputes.db import repo
from disputes.db.core import ensure_tenant
from disputes.domain import (
    ArtifactKind, AttachmentFinding, Category as C, Claim, ClaimFinding, Classification, ClockInfo, ClockState,
    Correction, Decision, Draft, DraftSentence, EscalationReason as E, Evidence, LlmCallRecord, MonthComparison,
    MonthResult, Outcome, Route, RuleFiring, SentenceSource, SuspicionLevel, SuspicionMatch, SuspicionResult,
)
from disputes.workflow import pipeline
from disputes.workflow.pipeline import Deps, NonSyntheticRefused, process_dispute

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)
CFG = defaults()


def _unavailable():
    from disputes.agents.llm import LlmUnavailable
    return LlmUnavailable


# ------------------------------------------------------------------------- fakes
class FakeBudget:
    def __init__(self):
        self._records: list[LlmCallRecord] = []

    def record(self, template: str, error: str | None = None):
        self._records.append(LlmCallRecord(
            model_id="fake-model-1", prompt_template_id=template, prompt_sha256="p" * 64,
            input_sha256s=("i" * 64,), output=None if error else {"ok": True}, error=error, latency_ms=5,
            tokens_in=10, tokens_out=5, cost_usd=0.0001, attempt=1))

    @property
    def records(self):
        return list(self._records)


def make_dispute(control="CN-1", *, tenant="synthetic-tenant-0", account="SYNACCT0001", months=("2026-01",),
                 due="2026-11-05", received="2026-10-09", free_text="late payment jan 2026 is wrong",
                 codes=("PLH-PH-01",), synthetic=True, attachments=None) -> Dispute:
    atts = attachments if attachments is not None else (
        Attachment("A1", "letter.txt", "text/plain", 1, "I paid on time in January 2026. " * 10, "a" * 64, {}),)
    raw = hashlib.sha256(f"{control}|{account}|{months}".encode()).hexdigest()
    return Dispute(tenant_id=tenant, channel="ACDV", source_schema_version="placeholder-acdv-0.1.0",
                   raw_payload_sha256=raw, synthetic=synthetic, control_number=control, cra="SYNTH-CRA-1",
                   date_received=received, response_due_date=due, account_number=account,
                   consumer_name="Test Person", dispute_codes=codes, disputed_months=months,
                   free_text=free_text, attachments=atts)


class Scenario:
    """Knobs for the fake deps. Defaults = happy VERIFY path."""

    def __init__(self, **kw):
        self.valid = True
        self.categories = {C.PAYMENT_HISTORY}
        self.route = Route.INVESTIGATE
        self.cls_escalations: tuple = ()
        self.mismatch_months: set[str] = set()
        self.no_months = False
        self.claim_finding = ClaimFinding.CONTRADICTED
        self.draft_valid = True
        self.unreadable = False
        self.clock_state = ClockState.ON_TRACK
        self.suspicion = SuspicionLevel.NONE
        self.llm_fail_at: str | None = None        # "classify" | "claims" | "map" | "draft"
        self.raise_at: str | None = None           # dep name that raises RuntimeError
        self.calls: list[str] = []
        self.budgets: list[FakeBudget] = []
        self.__dict__.update(kw)

    def _maybe_raise(self, name):
        self.calls.append(name)
        if self.raise_at == name:
            raise RuntimeError(f"boom in {name} for SYNACCT0001")

    def _llm(self, budget, name, template):
        if self.llm_fail_at == name:
            budget.record(template, error="timeout")
            budget.record(template, error="timeout")
            raise _unavailable()(f"{name}: timed out twice")
        budget.record(template)

    # intake
    def validate_dispute(self, d):
        self._maybe_raise("validate_dispute")
        if not self.valid:
            return (E.INTAKE_INVALID,), ("response_due_date missing",)
        return (), ()

    def inspect_attachments(self, atts, cfg):
        self._maybe_raise("inspect_attachments")
        f = tuple(AttachmentFinding(a.attachment_id, not self.unreadable, 10.0 if self.unreadable else 400.0,
                                    False, False, ("TOO_FEW_CHARS",) if self.unreadable else ()) for a in atts)
        return f, False

    def compute_clock(self, due, now, cfg):
        self._maybe_raise("compute_clock")
        return ClockInfo(due_date=due, internal_target=due - timedelta(days=3), state=self.clock_state,
                         evaluated_at=now, business_days_to_target=10, table_versions={"holiday_calendar": "0.1"})

    def detect_suspicious(self, d, findings):
        self._maybe_raise("detect_suspicious")
        m = (SuspicionMatch("letter_body", "ROLE_MARKER", SuspicionLevel.HIGH, "SYSTEM:"),) \
            if self.suspicion == SuspicionLevel.HIGH else ()
        return SuspicionResult(self.suspicion, m, "inj-0.1")

    def find_repeat(self, *, date_received, categories, prior_cases, window_days):
        self._maybe_raise("find_repeat")
        for p in prior_cases:
            if set(p["categories"]) & set(categories) and p["date_received"] and \
                    0 <= (date_received - p["date_received"]).days <= window_days:
                return p
        return None

    # agents
    def classify(self, d, budget):
        self._maybe_raise("classify")
        self._llm(budget, "classify", "classify_v1")
        cats = frozenset(self.categories)
        return Classification(categories=cats, code_categories=cats, llm_categories=cats,
                              fraud_signal_sources=("keyword",) if self.route == Route.ESCALATE_FRAUD else (),
                              llm_confidence=0.9, route=self.route, escalations=self.cls_escalations)

    def extract_claims(self, d, budget):
        self._maybe_raise("extract_claims")
        self._llm(budget, "claims", "claims_v1")
        return [Claim("CL-1", "paid on time in Jan 2026", "I paid on time in January 2026.", "A1", (0, 31),
                      "PAYMENT_EVENT", months=("2026-01",))], ()

    def map_claims(self, claims, evidence, budget):
        self._maybe_raise("map_claims")
        self._llm(budget, "map", "map_v1")
        return [replace(c, finding=self.claim_finding, evidence_ids=("EV-CYCLE-2026-01",)) for c in claims], ()

    def draft_narrative(self, decision, claims, evidence, budget):
        self._maybe_raise("draft_narrative")
        self._llm(budget, "draft", "draft_v1")
        s = DraftSentence("Our records show the payment was 0 days past due.", SentenceSource.LLM, None,
                          ("EV-CYCLE-2026-01",))
        if self.draft_valid:
            return Draft((s,), (), 1, True, "tpl-0.1")
        return Draft((replace(s, evidence_ids=()),), ("LLM sentence without citation",), 2, False, "tpl-0.1")

    def make_budget(self, cfg):
        b = FakeBudget()
        self.budgets.append(b)
        return b

    # rules
    def disputed_months(self, d, claim_months):
        self._maybe_raise("disputed_months")
        return [] if self.no_months else sorted(set(d.disputed_months) | set(claim_months))

    def gather_evidence(self, d, sor, months, now):
        self._maybe_raise("gather_evidence")
        ev = [Evidence("EV-ACCOUNT", "account", "mock_sor", now, "e" * 64, {"account": d.account_number})]
        ev += [Evidence(f"EV-CYCLE-{m}", "cycle", "mock_sor", now, "c" * 64, {"dpd": 0}) for m in months]
        return ev

    def compare_months(self, months, evidence):
        self._maybe_raise("compare_months")
        return [MonthComparison(m, 0, "R0", "R1" if m in self.mismatch_months else "R0",
                                MonthResult.MISMATCH if m in self.mismatch_months else MonthResult.MATCH,
                                (f"EV-CYCLE-{m}",)) for m in months]

    def decide(self, *, classification, comparisons, evidence, claims, upstream_escalations=(), llm_note_flag=False):
        self._maybe_raise("decide")
        reasons = list(upstream_escalations)
        if any(c.finding in (ClaimFinding.SUPPORTED, ClaimFinding.NOT_ADDRESSABLE) for c in claims):
            reasons.append(E.CLAIM_UNRESOLVED)
        firings = [RuleFiring(f"R-10.{r}", "1.0.0", str(r)) for r in reasons]
        if reasons:
            return Decision(Outcome.ESCALATED, tuple(dict.fromkeys(reasons)), (), tuple(firings), "1.0.0", {})
        mism = [c for c in comparisons if c.result == MonthResult.MISMATCH]
        if mism:
            return Decision(Outcome.MODIFY, (), tuple(Correction(c.month, "payment_rating", c.reported_rating,
                                                                 c.expected_rating) for c in mism),
                            (RuleFiring("R-10.MODIFY", "1.0.0", "MODIFY", ("EV-CYCLE-2026-01",)),), "1.0.0",
                            {"payment_rating_map": {"version": "0.1", "verified": False}})
        return Decision(Outcome.VERIFIED_AS_REPORTED, (), (),
                        (RuleFiring("R-10.VERIFY", "1.0.0", "VERIFIED_AS_REPORTED", ("EV-CYCLE-2026-01",)),),
                        "1.0.0", {"payment_rating_map": {"version": "0.1", "verified": False}})

    def deps(self, sor=None) -> Deps:
        return Deps(validate_dispute=self.validate_dispute, inspect_attachments=self.inspect_attachments,
                    compute_clock=self.compute_clock, detect_suspicious=self.detect_suspicious,
                    find_repeat=self.find_repeat, classify=self.classify, extract_claims=self.extract_claims,
                    disputed_months=self.disputed_months, gather_evidence=self.gather_evidence,
                    compare_months=self.compare_months, map_claims=self.map_claims, decide=self.decide,
                    draft_narrative=self.draft_narrative, make_budget=self.make_budget, sor=sor)


def run(conn, tenant, sc: Scenario | None = None, dispute=None, now=NOW):
    sc = sc or Scenario()
    res = process_dispute(conn, tenant_id=tenant, dispute=dispute or make_dispute(), deps=sc.deps(), cfg=CFG, now=now)
    return res, sc


def kinds(conn, tenant, case_id):
    return {r["kind"] for r in repo.artifact_history(conn, tenant_id=tenant, case_id=case_id)}


def events(conn, tenant, case_id, etype=None):
    evs = repo.audit_events_for_case(conn, tenant_id=tenant, case_id=case_id)
    return [e for e in evs if etype is None or e["event_type"] == etype]


def states(conn, tenant, case_id):
    return [e["payload"]["to"] for e in events(conn, tenant, case_id, "STATE_CHANGED")]


def assert_audited(conn, tenant, res):
    """Every state change has a STATE_CHANGED event that chains to the final state; chain verifies."""
    case = repo.get_case(conn, tenant_id=tenant, case_id=res.case_id)
    sc = events(conn, tenant, res.case_id, "STATE_CHANGED")
    prev = "RECEIVED"
    for e in sc:
        assert e["payload"]["from"] == prev
        prev = e["payload"]["to"]
    assert prev == case["state"] == res.state
    v = verify_case(conn, tenant_id=tenant, case_id=res.case_id)
    assert v["ok"], v
    return case, v


# ------------------------------------------------------------------------- tests
def test_happy_verify_path_reaches_draft_ready(conn, tenant):
    res, sc = run(conn, tenant)
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "DRAFT_READY"
    assert states(conn, tenant, res.case_id) == ["CLASSIFIED", "INVESTIGATING", "DRAFT_READY"]
    assert case["proposed_outcome"] == "VERIFIED_AS_REPORTED"
    assert case["categories"] == ["PAYMENT_HISTORY"] and case["escalation_reasons"] == []
    assert case["clock_state"] == "ON_TRACK" and case["internal_target_date"] == date(2026, 11, 2)
    assert case["response_due_date"] == date(2026, 11, 5) and case["account_last4"] == "0001"
    assert case["priority"] == 0 and case["suspicion_level"] == "NONE"
    expected = {k.value for k in ArtifactKind} - {"review", "package"}
    assert kinds(conn, tenant, res.case_id) == expected
    # claims: v1 extracted, v2 mapped
    claims = repo.artifact_history(conn, tenant_id=tenant, case_id=res.case_id, kind="claims")
    assert [c["version"] for c in claims] == [1, 2] and claims[1]["data"][0]["finding"] == "CONTRADICTED"
    # MODEL_CALL: one per record, all 4 calls (classify, claims, map, draft)
    mc = events(conn, tenant, res.case_id, "MODEL_CALL")
    assert len(mc) == len(sc.budgets[0].records) == 4
    assert [e["payload"]["prompt_template_id"] for e in mc] == ["classify_v1", "claims_v1", "map_v1", "draft_v1"]
    assert all(e["actor_type"] == "MODEL" and e["actor_id"] == "model:fake-model-1" for e in mc)
    # RULE_EVALUATED carries firings and table versions (R-29)
    (rule,) = events(conn, tenant, res.case_id, "RULE_EVALUATED")
    assert rule["payload"]["firings"][0]["rule_id"] == "R-10.VERIFY"
    assert rule["payload"]["table_versions"]["payment_rating_map"]["verified"] is False
    assert rule["payload"]["rules_version"] == "1.0.0"
    for t in ("CASE_CREATED", "INTAKE_VALIDATED", "SUSPICION_CHECKED", "CLASSIFIED", "CLAIMS_EXTRACTED",
              "EVIDENCE_GATHERED", "MONTHS_COMPARED", "CLAIMS_MAPPED", "DRAFT_GENERATED"):
        assert len(events(conn, tenant, res.case_id, t)) == 1, t
    assert len(repo.list_attachments(conn, tenant_id=tenant, case_id=res.case_id)) == 1
    conn.commit()
    assert verify_all(conn)["ok"]


def test_modify_path(conn, tenant):
    res, _ = run(conn, tenant, Scenario(mismatch_months={"2026-01"}))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "DRAFT_READY" and case["proposed_outcome"] == "MODIFY"
    dec = repo.latest_artifact(conn, tenant_id=tenant, case_id=res.case_id, kind="decision")["data"]
    assert dec["corrections"] == [{"month": "2026-01", "field": "payment_rating", "reported": "R1", "corrected": "R0"}]


def test_intake_invalid_escalates_without_llm(conn, tenant):
    res, sc = run(conn, tenant, Scenario(valid=False), make_dispute(due=None))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["INTAKE_INVALID"]
    assert sc.budgets == [] and "classify" not in sc.calls
    assert events(conn, tenant, res.case_id, "MODEL_CALL") == []
    assert case["raw_payload_sha256"] and case["response_due_date"] is None
    assert kinds(conn, tenant, res.case_id) == {"dispute", "intake", "suspicion"}
    intake = repo.latest_artifact(conn, tenant_id=tenant, case_id=res.case_id, kind="intake")["data"]
    assert intake["valid"] is False and intake["errors"] == ["response_due_date missing"]


def test_pipeline_flags_unparseable_dates_even_if_validator_misses_them(conn, tenant):
    res, sc = run(conn, tenant, Scenario(), make_dispute(due="11/05/2026"))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["INTAKE_INVALID"] and sc.budgets == []


def test_duplicate_creates_no_case_and_logs(conn, tenant):
    first, _ = run(conn, tenant)
    dup, sc = run(conn, tenant, dispute=make_dispute())
    assert dup.case_id is None and dup.duplicate_of == first.case_id and dup.state == "DUPLICATE_IGNORED"
    assert sc.calls == [] and sc.budgets == []
    assert conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 1
    d = conn.execute("SELECT * FROM duplicate_intakes").fetchall()
    assert len(d) == 1 and d[0]["original_case_id"] == first.case_id
    ev = conn.execute("SELECT * FROM audit_events WHERE event_type = 'DUPLICATE_IGNORED'").fetchall()
    assert len(ev) == 1 and ev[0]["case_id"] is None and ev[0]["tenant_id"] == tenant
    assert ev[0]["payload"]["original_case_id"] == first.case_id
    conn.commit()
    assert verify_all(conn)["ok"]


def test_duplicate_is_per_tenant(conn, tenant):
    ensure_tenant(conn, "synthetic-tenant-1", "Example Auto Finance (SYNTHETIC)")
    conn.commit()
    a, _ = run(conn, tenant)
    b, _ = run(conn, "synthetic-tenant-1", dispute=make_dispute(tenant="synthetic-tenant-1"))
    assert a.case_id and b.case_id and a.case_id != b.case_id and b.duplicate_of is None


def test_fraud_escalates_with_priority_and_no_draft(conn, tenant):
    res, sc = run(conn, tenant, Scenario(route=Route.ESCALATE_FRAUD, categories={C.PAYMENT_HISTORY, C.IDENTITY_FRAUD}))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["priority"] == 100
    assert "ID_FRAUD_SUSPECTED" in case["escalation_reasons"]
    assert states(conn, tenant, res.case_id) == ["CLASSIFIED", "ESCALATED"]
    k = kinds(conn, tenant, res.case_id)
    assert "draft" not in k and "evidence" not in k and "draft_narrative" not in sc.calls
    assert case["proposed_outcome"] == "ESCALATED"
    # fraud sorts first in the queue (R-16)
    other, _ = run(conn, tenant, dispute=make_dispute("CN-2", account="SYNACCT0002"))
    q = repo.list_cases(conn, tenant_id=tenant)
    assert q[0]["case_id"] == res.case_id


def test_out_of_scope(conn, tenant):
    res, sc = run(conn, tenant, Scenario(route=Route.OUT_OF_SCOPE, categories={C.BALANCE}))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "OUT_OF_SCOPE" and case["proposed_outcome"] == "OUT_OF_SCOPE"
    assert case["escalation_reasons"] == [] and "draft" not in kinds(conn, tenant, res.case_id)
    assert "extract_claims" not in sc.calls


def test_out_of_scope_but_breached_is_escalated(conn, tenant):
    res, _ = run(conn, tenant, Scenario(route=Route.OUT_OF_SCOPE, categories={C.BALANCE},
                                        clock_state=ClockState.BREACHED))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["BREACHED"]


def test_multi_issue(conn, tenant):
    res, sc = run(conn, tenant, Scenario(route=Route.ESCALATE_MULTI_ISSUE, categories={C.PAYMENT_HISTORY, C.BALANCE}))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["MULTI_ISSUE"]
    assert case["categories"] == ["BALANCE", "PAYMENT_HISTORY"] and "draft" not in kinds(conn, tenant, res.case_id)


def test_class_conflict(conn, tenant):
    res, _ = run(conn, tenant, Scenario(route=Route.ESCALATE_CLASS_CONFLICT, cls_escalations=(E.CLASS_CONFLICT,)))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["CLASS_CONFLICT"]


@pytest.mark.parametrize("where", ["classify", "claims", "map", "draft"])
def test_llm_unavailable_keeps_deterministic_results(conn, tenant, where):
    res, sc = run(conn, tenant, Scenario(llm_fail_at=where))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and "LLM_UNAVAILABLE" in case["escalation_reasons"]
    k = kinds(conn, tenant, res.case_id)
    assert "comparison" in k and "evidence" in k            # R-15: comparison still visible
    assert "draft" not in k
    if where != "classify":
        assert "decision" in k
        dec = repo.latest_artifact(conn, tenant_id=tenant, case_id=res.case_id, kind="decision")["data"]
        assert dec["outcome"] == "ESCALATED" and "LLM_UNAVAILABLE" in dec["escalation_reasons"]
        # LLM down at draft time happens after the first decision -> re-decided with LLM_UNAVAILABLE
        assert len(events(conn, tenant, res.case_id, "RULE_EVALUATED")) == (2 if where == "draft" else 1)
    else:
        assert states(conn, tenant, res.case_id) == ["ESCALATED"]
    # failed calls are audited too, one event per record
    mc = events(conn, tenant, res.case_id, "MODEL_CALL")
    assert len(mc) == len(sc.budgets[0].records)
    assert sum(1 for e in mc if e["payload"]["error"] == "timeout") == 2
    assert len(events(conn, tenant, res.case_id, "LLM_UNAVAILABLE")) == 1


def test_draft_invalid_escalates_and_keeps_draft(conn, tenant):
    res, _ = run(conn, tenant, Scenario(draft_valid=False))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["DRAFT_INVALID"]
    d = repo.latest_artifact(conn, tenant_id=tenant, case_id=res.case_id, kind="draft")["data"]
    assert d["valid"] is False and d["validator_errors"]
    decs = repo.artifact_history(conn, tenant_id=tenant, case_id=res.case_id, kind="decision")
    assert [x["data"]["outcome"] for x in decs] == ["VERIFIED_AS_REPORTED", "ESCALATED"]
    assert case["proposed_outcome"] == "ESCALATED"


def test_claim_unresolved_is_drafted_for_the_reviewer(conn, tenant):
    res, sc = run(conn, tenant, Scenario(claim_finding=ClaimFinding.SUPPORTED))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["CLAIM_UNRESOLVED"]
    assert "draft" in kinds(conn, tenant, res.case_id)
    assert len(events(conn, tenant, res.case_id, "RULE_EVALUATED")) == 1   # no needless re-decide


def test_months_undetermined(conn, tenant):
    res, _ = run(conn, tenant, Scenario(no_months=True))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and "MONTHS_UNDETERMINED" in case["escalation_reasons"]


@pytest.mark.parametrize("where", ["gather_evidence", "decide", "validate_dispute", "classify", "compute_clock",
                                   "draft_narrative"])
def test_unexpected_exception_escalates_fail_safe(conn, tenant, where):
    res, _ = run(conn, tenant, Scenario(raise_at=where))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED"
    (err,) = events(conn, tenant, res.case_id, "PIPELINE_ERROR")
    assert err["payload"]["error_type"] == "RuntimeError" and where in err["payload"]["error"]
    last = events(conn, tenant, res.case_id, "STATE_CHANGED")[-1]
    assert last["payload"]["reason"] == "SYSTEM_ERROR"
    if where == "gather_evidence":       # the failed step's writes rolled back
        assert "evidence" not in kinds(conn, tenant, res.case_id)
    conn.commit()
    assert verify_all(conn)["ok"]


def test_repeat_is_linked_and_still_investigated(conn, tenant):
    first, _ = run(conn, tenant, dispute=make_dispute("CN-1", received="2026-09-01"))
    second, _ = run(conn, tenant, dispute=make_dispute("CN-2", received="2026-10-01"))
    case, _ = assert_audited(conn, tenant, second)
    assert case["repeat_of_case_id"] == first.case_id and second.state == "DRAFT_READY"
    (ev,) = events(conn, tenant, second.case_id, "REPEAT_LINKED")
    assert ev["payload"]["prior_proposed_outcome"] == "VERIFIED_AS_REPORTED"
    intake = repo.artifact_history(conn, tenant_id=tenant, case_id=second.case_id, kind="intake")
    assert [i["version"] for i in intake] == [1, 2] and intake[1]["data"]["repeat_of_case_id"] == first.case_id
    # outside the 90-day window: no link
    third, _ = run(conn, tenant, dispute=make_dispute("CN-3", received="2027-03-01", due="2027-03-30"))
    assert repo.get_case(conn, tenant_id=tenant, case_id=third.case_id)["repeat_of_case_id"] is None


def test_breached_and_unreadable_escalate_but_still_investigate(conn, tenant):
    res, _ = run(conn, tenant, Scenario(clock_state=ClockState.BREACHED, unreadable=True))
    case, _ = assert_audited(conn, tenant, res)
    assert res.state == "ESCALATED" and case["escalation_reasons"] == ["DOC_UNREADABLE", "BREACHED"]
    assert case["clock_state"] == "BREACHED"
    k = kinds(conn, tenant, res.case_id)
    assert {"comparison", "decision", "draft"} <= k


def test_high_suspicion_recorded_on_case(conn, tenant):
    res, _ = run(conn, tenant, Scenario(suspicion=SuspicionLevel.HIGH))
    case, _ = assert_audited(conn, tenant, res)
    assert case["suspicion_level"] == "HIGH" and res.state == "DRAFT_READY"   # flag never changes the outcome


def test_refuses_non_synthetic_and_wrong_tenant(conn, tenant):
    with pytest.raises(NonSyntheticRefused):
        run(conn, tenant, dispute=make_dispute(synthetic=False))
    with pytest.raises(ValueError):
        run(conn, tenant, dispute=make_dispute(tenant="synthetic-tenant-9"))
    assert conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 0


def test_case_ids_are_readable_and_unique_per_tenant(conn, tenant):
    ensure_tenant(conn, "synthetic-tenant-1", "Example Auto Finance (SYNTHETIC)")
    ensure_tenant(conn, "synthetic-thing-1", "Prefix collision (SYNTHETIC)")
    conn.commit()
    ids = [run(conn, tenant, dispute=make_dispute(f"CN-{i}", account=f"SYNACCT{i:04d}"))[0].case_id for i in range(3)]
    assert ids == ["ST0-20261010-00001", "ST0-20261010-00002", "ST0-20261010-00003"]
    nxt = run(conn, tenant, dispute=make_dispute("CN-9"), now=NOW + timedelta(days=1))[0].case_id
    assert nxt == "ST0-20261011-00001"
    b = run(conn, "synthetic-tenant-1", dispute=make_dispute(tenant="synthetic-tenant-1"))[0].case_id
    c = run(conn, "synthetic-thing-1", dispute=make_dispute(tenant="synthetic-thing-1"))[0].case_id
    assert b == "ST1-20261010-00001" and c == "ST12-20261010-00001"


def test_attachments_with_repeated_ids_are_all_kept(conn, tenant):
    atts = (Attachment("A1", "a.txt", "text/plain", 1, "x" * 300, "1" * 64, {}),
            Attachment("A1", "b.txt", "text/plain", None, "y" * 300, "2" * 64, {}))
    res, _ = run(conn, tenant, dispute=make_dispute(attachments=atts))
    rows = repo.list_attachments(conn, tenant_id=tenant, case_id=res.case_id)
    assert [r["attachment_id"] for r in rows] == ["A1", "A1#dup"]


def test_full_run_of_every_branch_verifies_globally(conn, tenant, tmp_path):
    scenarios = [Scenario(), Scenario(mismatch_months={"2026-01"}), Scenario(valid=False),
                 Scenario(route=Route.ESCALATE_FRAUD), Scenario(llm_fail_at="claims"),
                 Scenario(raise_at="compare_months"), Scenario(draft_valid=False)]
    for i, sc in enumerate(scenarios):
        process_dispute(conn, tenant_id=tenant, dispute=make_dispute(f"CN-{i}", account=f"SYNACCT{i:04d}"),
                        deps=sc.deps(), cfg=CFG, now=NOW)
    run(conn, tenant, dispute=make_dispute("CN-0", account="SYNACCT0000"))  # duplicate
    conn.commit()
    from disputes.audit.anchor import write_anchor
    write_anchor(conn, tmp_path)
    v = verify_all(conn, anchor_dir=str(tmp_path))
    assert v["ok"] and v["trigger_present"] and v["anchor"]["ok"] and v["events"] > 50, v
    for r in conn.execute("SELECT case_id FROM cases").fetchall():
        assert verify_case(conn, tenant_id=tenant, case_id=r["case_id"])["ok"]


def test_default_deps_wires_real_modules():
    try:
        d = pipeline.default_deps(sor=object(), llm_client=object(), cfg=CFG)
    except ImportError as e:   # another module's stub does not import yet (reported in stage notes)
        pytest.skip(f"a module stub fails to import: {e}")
    for name in ("validate_dispute", "inspect_attachments", "compute_clock", "detect_suspicious", "find_repeat",
                 "classify", "extract_claims", "disputed_months", "gather_evidence", "compare_months",
                 "map_claims", "decide", "draft_narrative", "make_budget"):
        assert callable(getattr(d, name)), name
    from disputes.intake import suspicious
    from disputes.rules import outcome
    assert d.detect_suspicious is suspicious.detect and d.decide is outcome.decide


def test_find_repeat_failure_with_prior_case_escalates(conn, tenant):
    run(conn, tenant, dispute=make_dispute("CN-1", received="2026-09-01"))
    res, _ = run(conn, tenant, Scenario(raise_at="find_repeat"), make_dispute("CN-2", received="2026-10-01"))
    assert res.state == "ESCALATED"
    assert_audited(conn, tenant, res)


def test_concurrent_duplicate_race_is_recorded_as_duplicate(conn, tenant, monkeypatch):
    """Two intakes of one control number race: the loser hits the unique index and is logged
    as DUPLICATE_IGNORED instead of failing."""
    first, _ = run(conn, tenant)
    real = repo.find_case_by_control_number
    calls = {"n": 0}

    def racy(*a, **kw):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*a, **kw)   # first look misses the other intake
    monkeypatch.setattr(pipeline.repo, "find_case_by_control_number", racy)
    dup, _ = run(conn, tenant)
    assert dup.case_id is None and dup.duplicate_of == first.case_id and calls["n"] == 2
    assert conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 1
    conn.commit()
    assert verify_all(conn)["ok"]
