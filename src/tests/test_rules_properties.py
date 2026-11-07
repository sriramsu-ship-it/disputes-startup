"""Appendix B T0 / B1: property tests for the deterministic rule layer (R-09, R-10).

Each @given test checks EVERY invariant on every generated input, so each invariant sees the
full example count. Two input distributions:
  - `arbitrary`: any classification, any comparison results (incl. malformed months), any
    notes (incl. unknown types and broken dates), any claim findings (incl. None) and evidence
    IDs (incl. unknown ones), any upstream reasons, the LLM note flag;
  - `near_verify`: a clean VERIFY case with zero or more single perturbations, so VERIFY is
    actually reached often (otherwise the VERIFY invariant is tested mostly vacuously).
Invariants (B1): never DELETE; VERIFY ⇒ every month MATCH ∧ ≥1 month ∧ no escalation flag ∧
every claim CONTRADICTED ∧ categories == {PAYMENT_HISTORY}; escalation precedence (any
escalation condition ⇒ ESCALATED, no corrections; upstream reasons always kept); MODIFY ⇔
in scope ∧ no escalation ∧ ≥1 MISMATCH, with exactly one correction per mismatched month;
R-29: every reason and every outcome has a firing with rule ID, RULES_VERSION, evidence IDs.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from disputes.domain import (Category, Claim, ClaimFinding, Classification, EscalationReason,
                             MonthComparison, MonthResult, Outcome, Route)
from disputes.rules.compare import compare_months, expected_rating
from disputes.rules.evidence import make_evidence
from disputes.rules.outcome import RULES_VERSION, decide

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
N_ARBITRARY = 5_000
N_NEAR_VERIFY = 10_000
GOOD_MONTHS = [f"2026-{m:02d}" for m in range(1, 7)] + ["2025-12"]
BAD_MONTHS = ["2026-13", "bad", "2026-1"]
PH = frozenset({Category.PAYMENT_HISTORY})
CONFLICT_TYPES = {"HARDSHIP", "DEFERRAL", "FORBEARANCE"}
KNOWN_TYPES = CONFLICT_TYPES | {"PRIOR_DISPUTE", "OTHER"}
SETTINGS = dict(deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
                database=None)

# ------------------------------------------------------------------ independent reference checks
def _days(m: str):
    y, mo = int(m[:4]), int(m[5:7])
    d = date(y, mo, 1)
    while d.month == mo:
        yield d
        d += timedelta(days=1)


def _iso(v):
    try:
        return date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def ref_note_conflict(note: dict, months: list[str]) -> bool:
    """Independent formulation (day enumeration) of C2 with the documented fail-safe semantics."""
    t = note.get("type")
    if t in KNOWN_TYPES and t not in CONFLICT_TYPES:
        return False
    valid = [m for m in months if len(m) == 7 and m[4] == "-" and m[:4].isdigit() and m[5:].isdigit()
             and 1 <= int(m[5:]) <= 12]
    if not valid:
        return False
    s = _iso(note.get("start_date"))
    if s is None:
        return True
    if note.get("end_date") is None:
        return any(d >= s for m in valid for d in _days(m))
    e = _iso(note.get("end_date"))
    if e is None or e < s:
        return True
    return any(s <= d <= e for m in valid for d in _days(m))


# ------------------------------------------------------------------ strategies
date_str = st.one_of(
    st.dates(date(2025, 6, 1), date(2026, 12, 31)).map(date.isoformat),
    st.sampled_from(["", "2026-02-30", "not-a-date"]), st.none())
note_st = st.fixed_dictionaries({
    "type": st.sampled_from(sorted(KNOWN_TYPES) + ["hardship", "UNKNOWN", None]),
    "start_date": date_str, "end_date": date_str})
finding_st = st.sampled_from([ClaimFinding.CONTRADICTED, ClaimFinding.SUPPORTED,
                              ClaimFinding.NOT_ADDRESSABLE, None])
month_st = st.sampled_from(GOOD_MONTHS + BAD_MONTHS)
cats_st = st.frozensets(st.sampled_from(list(Category)), max_size=3)
reasons_st = st.lists(st.sampled_from(list(EscalationReason)), max_size=3).map(tuple)


@st.composite
def comparisons_st(draw, months):
    out = []
    for m in months:
        r = draw(st.sampled_from(list(MonthResult)))
        out.append(MonthComparison(m, 0, "PH_R0_CURRENT", "PH_R30" if r == MonthResult.MISMATCH else "PH_R0_CURRENT",
                                   r, (f"EV-CYCLE-{m}",) if r != MonthResult.NO_DATA else ()))
    return out


def _evidence(months, notes, ft_count, dup_month=None):
    ev = [make_evidence("EV-ACDV", "acdv", "acdv", NOW, {"x": 1}),
          make_evidence("EV-ACCOUNT", "account", "mock_sor", NOW, {"a": 1})]
    for m in months:
        content = {"cycle_month": m, "dpd_at_cycle": 0, "reported_rating": "PH_R0_CURRENT"}
        if m == dup_month:
            content = {"cycle_month": m, "conflicting_rows": [content, dict(content, dpd_at_cycle=40)]}
        ev.append(make_evidence(f"EV-CYCLE-{m}", "cycle", "mock_sor", NOW, content))
    for i, n in enumerate(notes, 1):
        ev.append(make_evidence(f"EV-NOTE-{i}", "note", "mock_sor", NOW, n))
    for i in range(1, ft_count + 1):
        ev.append(make_evidence(f"EV-FTNOTE-{i}", "free_text_note", "mock_sor", NOW, {"text": "t"}))
    return ev


@st.composite
def claims_st(draw, months, ids):
    n = draw(st.integers(0, 4))
    out = []
    for i in range(n):
        cites = tuple(draw(st.lists(st.sampled_from(ids + ["EV-UNKNOWN"]), max_size=2)))
        out.append(Claim(f"C{i+1}", "t", "q", "A1", None, "PAYMENT_EVENT",
                         tuple(draw(st.lists(st.sampled_from(months or GOOD_MONTHS), max_size=2))),
                         draw(finding_st), cites))
    return out


@st.composite
def arbitrary_case(draw):
    months = sorted(set(draw(st.lists(month_st, max_size=4))))
    comps = draw(comparisons_st(months))
    notes = draw(st.lists(note_st, max_size=3))
    dup = draw(st.sampled_from([None] + months)) if months else None
    ev = _evidence([m for m in months], notes, draw(st.integers(0, 2)), dup)
    claims = draw(claims_st(months, [e.evidence_id for e in ev]))
    cats = draw(cats_st)
    cls = Classification(cats, cats, cats, (), None, draw(st.sampled_from(list(Route))), draw(reasons_st))
    return dict(classification=cls, comparisons=comps, evidence=ev, claims=claims,
                upstream_escalations=draw(reasons_st), llm_note_flag=draw(st.booleans()))


@st.composite
def near_verify_case(draw):
    """Clean VERIFY input, then each perturbation applied with probability ~1/6."""
    months = sorted(set(draw(st.lists(st.sampled_from(GOOD_MONTHS), min_size=1, max_size=3))))
    comps = [MonthComparison(m, 0, "PH_R0_CURRENT", "PH_R0_CURRENT", MonthResult.MATCH, (f"EV-CYCLE-{m}",))
             for m in months]
    notes = []
    p = lambda: draw(st.integers(0, 5)) == 0   # noqa: E731
    if p():   # flip one month's result
        i = draw(st.integers(0, len(comps) - 1))
        r = draw(st.sampled_from([MonthResult.MISMATCH, MonthResult.NO_DATA]))
        c = comps[i]
        comps[i] = MonthComparison(c.month, c.dpd, c.expected_rating, "PH_R60" if r == MonthResult.MISMATCH else None,
                                   r, c.evidence_ids)
    if p():
        notes.append(draw(note_st))
    if p():   # a non-conflict note: must not block VERIFY
        notes.append({"type": draw(st.sampled_from(["PRIOR_DISPUTE", "OTHER"])),
                      "start_date": "2026-01-01", "end_date": "2026-12-31"})
    ev = _evidence(months, notes, 1, draw(st.sampled_from(months)) if p() else None)
    claims = [Claim(f"C{i}", "t", "q", "A1", None, "PAYMENT_EVENT", (m,), ClaimFinding.CONTRADICTED,
                    (f"EV-CYCLE-{m}",)) for i, m in enumerate(months, 1)]
    if p() and claims:
        i = draw(st.integers(0, len(claims) - 1))
        c = claims[i]
        claims[i] = Claim(c.claim_id, c.text, c.quote, c.source_id, c.span, c.claim_type, c.months,
                          draw(finding_st), draw(st.sampled_from([c.evidence_ids, (), ("EV-UNKNOWN",)])))
    cats, route = PH, Route.INVESTIGATE
    if p():
        cats = draw(cats_st)
    if p():
        route = draw(st.sampled_from(list(Route)))
    upstream = draw(reasons_st) if p() else ()
    cls = Classification(cats, cats, cats, (), None, route, draw(reasons_st) if p() else ())
    return dict(classification=cls, comparisons=comps, evidence=ev, claims=claims,
                upstream_escalations=upstream, llm_note_flag=p())


# ------------------------------------------------------------------ the invariants
def check_invariants(case: dict) -> Outcome:
    d = decide(**case)
    cls, comps, claims, ev = case["classification"], case["comparisons"], case["claims"], case["evidence"]
    known = {e.evidence_id for e in ev}
    upstream = set(case["upstream_escalations"]) | set(cls.escalations)
    reasons = set(d.escalation_reasons)
    months = [c.month for c in comps]
    in_scope = cls.categories == PH

    # never DELETE
    assert d.outcome != Outcome.DELETE
    assert d.rules_version == RULES_VERSION
    assert "payment_rating_map" in d.table_versions

    # VERIFY invariant (B1) — plus the extra conditions this implementation guarantees
    if d.outcome == Outcome.VERIFIED_AS_REPORTED:
        assert comps and all(c.result == MonthResult.MATCH for c in comps)
        assert not reasons and not upstream and not case["llm_note_flag"]
        assert all(c.finding == ClaimFinding.CONTRADICTED for c in claims)
        assert all(c.evidence_ids and set(c.evidence_ids) <= known for c in claims)
        assert cls.categories == PH and cls.route == Route.INVESTIGATE
        assert not any(ref_note_conflict(e.content, months) for e in ev if e.kind == "note")
        assert not any("conflicting_rows" in e.content for e in ev if e.kind == "cycle")
        assert d.corrections == ()

    # escalation precedence
    assert upstream <= reasons
    assert (d.outcome == Outcome.ESCALATED) == bool(reasons)
    if d.outcome == Outcome.ESCALATED:
        assert d.corrections == ()
    if in_scope:
        if any(c.result == MonthResult.NO_DATA for c in comps):
            assert EscalationReason.EVIDENCE_MISSING in reasons
        if not comps:
            assert EscalationReason.MONTHS_UNDETERMINED in reasons
        if case["llm_note_flag"] or any(ref_note_conflict(e.content, months) for e in ev if e.kind == "note"):
            assert EscalationReason.EVIDENCE_CONFLICT in reasons
    else:
        assert d.outcome in (Outcome.ESCALATED, Outcome.OUT_OF_SCOPE)
    if cls.route != Route.INVESTIGATE and in_scope:
        assert d.outcome == Outcome.ESCALATED
    if Category.IDENTITY_FRAUD in cls.categories:
        assert EscalationReason.ID_FRAUD_SUSPECTED in reasons

    # MODIFY
    mism = sorted(c.month for c in comps if c.result == MonthResult.MISMATCH)
    if d.outcome == Outcome.MODIFY:
        assert in_scope and not reasons and mism
        assert [c.month for c in d.corrections] == mism
        assert all(c.field == "payment_rating" and c.corrected for c in d.corrections)
    if in_scope and not reasons and mism:
        assert d.outcome == Outcome.MODIFY   # MISMATCH beats VERIFY and CLAIM_UNRESOLVED
    if d.outcome == Outcome.MODIFY or d.outcome == Outcome.VERIFIED_AS_REPORTED:
        assert cls.route == Route.INVESTIGATE

    # R-29: every reason and the outcome have a firing with version and (where any exist) evidence
    for r in reasons:
        fs = [f for f in d.firings if f.result == r.value]
        assert fs and all(f.rule_version == RULES_VERSION and f.rule_id for f in fs)
    out_f = [f for f in d.firings if f.result == d.outcome.value and f.rule_id == "R-10.OUTCOME"]
    assert len(out_f) == 1
    for f in d.firings:
        assert set(f.evidence_ids) <= known
        if f.result in {r.value for r in EscalationReason} | {o.value for o in Outcome}:
            assert f.evidence_ids, f   # EV-ACDV is always present in these inputs

    # deterministic
    assert decide(**case) == d
    return d.outcome


def test_b1_invariants_arbitrary_inputs():
    seen = Counter()

    @settings(max_examples=N_ARBITRARY, **SETTINGS)
    @given(arbitrary_case())
    def run(case):
        seen[check_invariants(case)] += 1

    run()
    assert sum(seen.values()) >= N_ARBITRARY
    print("arbitrary outcomes:", dict(seen))


def test_b1_invariants_near_verify_inputs():
    seen = Counter()

    @settings(max_examples=N_NEAR_VERIFY, **SETTINGS)
    @given(near_verify_case())
    def run(case):
        seen[check_invariants(case)] += 1

    run()
    assert sum(seen.values()) >= N_NEAR_VERIFY
    # The VERIFY invariant must be exercised non-vacuously, and so must the other paths.
    assert seen[Outcome.VERIFIED_AS_REPORTED] >= N_NEAR_VERIFY // 10, dict(seen)
    assert seen[Outcome.MODIFY] > 0 and seen[Outcome.ESCALATED] > 0
    print("near-verify outcomes:", dict(seen))


# ------------------------------------------------------------------ R-09 property
def _ref_rating(dpd: int) -> str:
    for lo, hi, r in [(0, 29, "PH_R0_CURRENT"), (30, 59, "PH_R30"), (60, 89, "PH_R60"), (90, 119, "PH_R90"),
                      (120, 149, "PH_R120"), (150, 179, "PH_R150"), (180, 99999, "PH_R180P")]:
        if lo <= dpd <= hi:
            return r
    raise AssertionError


@settings(max_examples=2000, **SETTINGS)
@given(st.dictionaries(st.sampled_from(GOOD_MONTHS),
                       st.tuples(st.one_of(st.integers(-5, 400), st.none(), st.booleans()),
                                 st.one_of(st.sampled_from(["PH_R0_CURRENT", "PH_R30", "PH_R60", "PH_R90",
                                                            "PH_R180P", "", "XX"]), st.none())),
                       max_size=5),
       st.lists(st.sampled_from(GOOD_MONTHS), max_size=5))
def test_r09_compare_property(cycles, months):
    ev = [make_evidence(f"EV-CYCLE-{m}", "cycle", "mock_sor", NOW,
                        {"cycle_month": m, "dpd_at_cycle": dpd, "reported_rating": rep})
          for m, (dpd, rep) in cycles.items()]
    out = compare_months(months, ev)
    assert [c.month for c in out] == sorted(set(months))
    for c in out:
        if c.month not in cycles:
            assert c.result == MonthResult.NO_DATA
            continue
        dpd, rep = cycles[c.month]
        valid_dpd = isinstance(dpd, int) and not isinstance(dpd, bool) and dpd >= 0
        if not valid_dpd or not rep:
            assert c.result == MonthResult.NO_DATA
        else:
            assert c.expected_rating == _ref_rating(dpd) == expected_rating(dpd)
            assert c.result == (MonthResult.MATCH if rep == _ref_rating(dpd) else MonthResult.MISMATCH)
        assert c.evidence_ids == (f"EV-CYCLE-{c.month}",)
