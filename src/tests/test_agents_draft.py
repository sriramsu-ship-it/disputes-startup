"""R-12 draft narrative and R-13 validator (S5 acceptance criteria)."""
from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from disputes.agents.draft import draft_narrative, template_sentences
from disputes.agents.llm import CaseBudget, LlmUnavailable, OfflineLlmClient
from disputes.agents.validator import outcome_terms_in, templates, validate_draft
from disputes.config import defaults
from disputes.domain import (Claim, ClaimFinding, Correction, Decision, Draft, DraftSentence, EscalationReason,
                             Outcome, RuleFiring, SentenceSource)
from test_agents_helpers import FakeClient, att_ev, cycle_ev

LETTER = "Dear team,\nMy March 2026 payment was on time.\nRegards"
EV = [cycle_ev("2026-03", 35, "PH_R30"), att_ev("A1", LETTER)]
SRC = {"A1": LETTER}
QUOTE = "My March 2026 payment was on time."
QS = LETTER.index(QUOTE)
CLAIM = Claim("CL-1", QUOTE, QUOTE, "A1", (QS, QS + len(QUOTE)), "PAYMENT_EVENT", ("2026-03",),
              ClaimFinding.CONTRADICTED, ("EV-CYCLE-2026-03",), "35 DPD")
VERIFY = Decision(Outcome.VERIFIED_AS_REPORTED, (), (), (RuleFiring("R-10.VERIFY", "1", "VERIFIED_AS_REPORTED",
                                                                     ("EV-CYCLE-2026-03",)),), "1.0.0")


def llm_s(text, ids=("EV-CYCLE-2026-03",), spans=()):
    return DraftSentence(text=text, source=SentenceSource.LLM, evidence_ids=tuple(ids), quote_spans=tuple(spans))


def tpl(tid, **slots):
    return DraftSentence(text=templates()[tid].format(**slots), source=SentenceSource.TEMPLATE, template_id=tid)


def v(*sentences, max_words=150):
    return validate_draft(Draft(sentences=tuple(sentences)), EV, SRC, max_words=max_words)


GOOD_LLM = llm_s(f'The consumer wrote "{QUOTE}"; the March 2026 cycle shows 35 days past due.',
                 spans=(("A1", QS, QS + len(QUOTE)),))


# ----------------------------------------------------------------------------- validator rules (R-13)
def test_valid_draft_passes():
    assert v(tpl("TPL-INTRO"), GOOD_LLM, tpl("TPL-OUTCOME-VERIFIED_AS_REPORTED"), tpl("TPL-REVIEW")) == []


def test_rejects_llm_sentence_without_citation():
    errs = v(llm_s("The March 2026 cycle shows 35 days past due.", ids=()))
    assert any(e.startswith("LLM_NO_CITATION") for e in errs)


def test_rejects_unknown_evidence_id():
    errs = v(llm_s("The cycle shows 35 days past due.", ids=("EV-CYCLE-2019-01",)))
    assert any(e.startswith("UNKNOWN_EVIDENCE_ID") for e in errs)


def test_rejects_quote_not_in_source():
    errs = v(llm_s('The consumer wrote "My March payment was early"; see the cycle.'))
    assert any(e.startswith("QUOTE_NOT_VERBATIM") for e in errs)


def test_rejects_span_that_is_not_in_the_sentence_or_source():
    errs = v(llm_s("The cycle shows 35 days past due.", spans=(("A1", QS, QS + len(QUOTE)),)))
    assert any(e.startswith("QUOTE_NOT_VERBATIM") for e in errs)
    errs = v(llm_s("x", spans=(("A9", 0, 3),)))
    assert any(e.startswith("QUOTE_SPAN_INVALID") for e in errs)
    errs = v(llm_s("x", spans=(("A1", 5, 5000),)))
    assert any(e.startswith("QUOTE_SPAN_INVALID") for e in errs)


def test_rejects_template_sentence_not_matching_its_template():
    bad = DraftSentence(text="Result: the disputed payment history is fine.", source=SentenceSource.TEMPLATE,
                        template_id="TPL-OUTCOME-VERIFIED_AS_REPORTED")
    assert any(e.startswith("TEMPLATE_MISMATCH") for e in v(bad))
    unk = DraftSentence(text="Anything.", source=SentenceSource.TEMPLATE, template_id="TPL-NOPE")
    assert any(e.startswith("TEMPLATE_UNKNOWN") for e in v(unk))


@pytest.mark.parametrize("phrase", ["verified as reported", "Verified", "will be deleted", "was modified",
                                    "is accurate as reported", "has been corrected", "accurate  as\nreported"])
def test_rejects_outcome_words_in_llm_sentences(phrase):
    errs = v(llm_s(f"The cycle record {phrase} per EV-CYCLE-2026-03."))
    assert any(e.startswith("OUTCOME_WORD") for e in errs)


def test_outcome_words_do_not_match_inside_other_words():
    assert outcome_terms_in("unverified, undeleted, remodified") == []


def test_outcome_word_inside_a_verified_consumer_quote_is_allowed():
    text = "Dear team,\nPlease note my March 2026 payment was verified by my bank.\n"
    q = "my March 2026 payment was verified by my bank."
    s = text.index(q)
    sent = llm_s(f'The consumer wrote "{q}"; the March 2026 cycle shows 35 days past due.', spans=(("A1", s, s + len(q)),))
    assert validate_draft(Draft((sent,)), EV, {"A1": text}) == []
    # but the same words outside the located quote are rejected
    sent2 = llm_s(f'The consumer wrote "{q}"; the payment was verified.', spans=(("A1", s, s + len(q)),))
    assert any(e.startswith("OUTCOME_WORD") for e in validate_draft(Draft((sent2,)), EV, {"A1": text}))


def test_template_sentences_may_carry_outcome_words():
    assert v(tpl("TPL-OUTCOME-VERIFIED_AS_REPORTED")) == []


def test_rejects_over_150_words():
    long = llm_s(" ".join(["word"] * 151))
    errs = v(long)
    assert any(e.startswith("TOO_LONG") for e in errs)
    assert not any(e.startswith("TOO_LONG") for e in v(llm_s(" ".join(["word"] * 150))))


def test_empty_draft_is_invalid():
    assert validate_draft(Draft(()), EV, SRC) == ["EMPTY_DRAFT: no sentences"]


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=120), st.sampled_from(["verified", "deleted", "modified", "accurate as reported"]))
def test_property_no_llm_sentence_with_outcome_word_or_no_citation_passes(prefix, word):
    no_cite = llm_s(prefix + " cycle", ids=())
    assert v(no_cite)
    outcome = llm_s(f"{prefix.replace(chr(34), '')} {word} .")
    assert v(outcome)


# ----------------------------------------------------------------------------- draft_narrative (R-12)
def draft_out(text=None, ids=("EV-CYCLE-2026-03",), quotes=None):
    text = text if text is not None else f'The consumer wrote "{QUOTE}"; the March 2026 cycle shows 35 days past due.'
    return {"sentences": [{"text": text, "evidence_ids": list(ids),
                           "quotes": quotes if quotes is not None else [{"source_id": "A1", "quote": QUOTE}]}]}


def test_draft_structure_and_outcome_only_from_templates():
    b = CaseBudget(FakeClient([draft_out()]), defaults())
    d = draft_narrative(VERIFY, [CLAIM], EV, b, source_texts=SRC)
    assert d.valid and d.attempts == 1 and d.template_library_version
    kinds = [(s.source, s.template_id) for s in d.sentences]
    assert kinds[0] == (SentenceSource.TEMPLATE, "TPL-INTRO")
    assert (SentenceSource.TEMPLATE, "TPL-OUTCOME-VERIFIED_AS_REPORTED") in kinds
    llm = [s for s in d.sentences if s.source == SentenceSource.LLM]
    assert llm and all(s.evidence_ids for s in llm) and llm[0].quote_spans == (("A1", QS, QS + len(QUOTE)),)
    # the outcome statement is a template filled from the Decision, never from the model
    assert not any(outcome_terms_in(s.text) for s in llm)


def test_modify_corrections_are_template_slots_from_decision():
    dec = Decision(Outcome.MODIFY, (), (Correction("2026-03", "payment_rating", "PH_R30", "PH_R0_CURRENT"),),
                   (), "1.0.0")
    before, after = template_sentences(dec, {"EV-CYCLE-2026-03"})
    texts = [s.text for s in after]
    assert "For March 2026, the payment rating changes from PH_R30 to PH_R0_CURRENT." in texts
    assert after[1].evidence_ids == ("EV-CYCLE-2026-03",)


def test_escalated_template_lists_reasons():
    dec = Decision(Outcome.ESCALATED, (EscalationReason.EVIDENCE_MISSING, EscalationReason.CLAIM_UNRESOLVED),
                   (), (), "1.0.0")
    _, after = template_sentences(dec, set())
    assert "(EVIDENCE_MISSING, CLAIM_UNRESOLVED)" in after[0].text


def test_invalid_then_retry_succeeds():
    fc = FakeClient([draft_out(text="The cycle was verified.", quotes=[]), draft_out()])
    b = CaseBudget(fc, defaults().with_overrides(llm_max_calls_per_case=5))
    d = draft_narrative(VERIFY, [CLAIM], EV, b, source_texts=SRC)
    assert d.valid and d.attempts == 2
    assert fc.calls[1][1]["previous_errors"] and fc.calls[1][1]["previous_errors"][0].startswith("OUTCOME_WORD")


def test_invalid_twice_returns_invalid_draft():
    """S5: no citation -> rejected, retried once, then invalid (caller escalates DRAFT_INVALID)."""
    fc = FakeClient([draft_out(text="The cycle shows lateness.", ids=(), quotes=[])])
    b = CaseBudget(fc, defaults().with_overrides(llm_max_calls_per_case=5))
    d = draft_narrative(VERIFY, [CLAIM], EV, b, source_texts=SRC)
    assert not d.valid and d.attempts == 2 and len(fc.calls) == 2
    assert any(e.startswith("LLM_NO_CITATION") for e in d.validator_errors)


def test_retry_skipped_when_call_cap_reached_is_invalid_not_silent():
    fc = FakeClient([draft_out(text="The cycle shows lateness.", ids=(), quotes=[])])
    b = CaseBudget(fc, defaults().with_overrides(llm_max_calls_per_case=4))   # cap 4 explicit
    for _ in range(3):
        b._calls += 1                        # classify, extract, map already spent
    d = draft_narrative(VERIFY, [CLAIM], EV, b, source_texts=SRC)
    assert not d.valid and d.attempts == 1 and any(e.startswith("RETRY_SKIPPED") for e in d.validator_errors)


def test_llm_unavailable_propagates_from_draft():
    b = CaseBudget(FakeClient([RuntimeError("down")]), defaults(), backoff_s=0.0)
    with pytest.raises(LlmUnavailable):
        draft_narrative(VERIFY, [CLAIM], EV, b, source_texts=SRC)


def test_offline_draft_is_valid_and_rebuilds_sources_from_evidence():
    b = CaseBudget(OfflineLlmClient(), defaults())
    d = draft_narrative(VERIFY, [CLAIM], EV, b)          # source_texts rebuilt from EV-ATT-A1
    assert d.valid, d.validator_errors
    assert sum(len(s.text.split()) for s in d.sentences) <= 150


def test_offline_draft_stays_under_word_limit_with_many_claims():
    claims = [Claim(f"CL-{i}", QUOTE, QUOTE, "A1", (QS, QS + len(QUOTE)), "PAYMENT_EVENT", ("2026-03",),
                    ClaimFinding.CONTRADICTED, ("EV-CYCLE-2026-03",), "") for i in range(1, 12)]
    b = CaseBudget(OfflineLlmClient(), defaults())
    d = draft_narrative(VERIFY, claims, EV, b, source_texts=SRC)
    assert d.valid, d.validator_errors
    assert sum(len(s.text.split()) for s in d.sentences) <= 150
