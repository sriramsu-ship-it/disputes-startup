"""Integration guard: a letter with text but no extracted claims never reaches VERIFY."""
from types import SimpleNamespace

from disputes.workflow.pipeline import NARRATIVE_MIN_WORDS, _has_consumer_narrative


def _d(*texts):
    return SimpleNamespace(attachments=tuple(SimpleNamespace(extracted_text=t) for t in texts))


def test_narrative_detection():
    assert not _has_consumer_narrative(_d())
    assert not _has_consumer_narrative(_d("short note"))
    assert _has_consumer_narrative(_d("word " * NARRATIVE_MIN_WORDS))
    assert _has_consumer_narrative(_d("word " * 20, "word " * 10))


def test_agreement_claim_is_never_contradicted_by_ledger():
    from disputes.agents.claims import _agreement_backstop
    from disputes.domain import Claim, ClaimFinding
    c = Claim("C1", "t", "your agent confirmed 04/2026 would be reported as paid on time", "A1", (0, 10),
              "PAYMENT_EVENT", ("2026-04",), ClaimFinding.CONTRADICTED, ("EV-CYCLE-2026-04",), "late")
    out = _agreement_backstop(c)
    assert out.finding == ClaimFinding.NOT_ADDRESSABLE and out.reason.startswith("AGREEMENT_BACKSTOP")
    plain = Claim("C2", "t", "I paid April on time", "A1", (0, 5), "PAYMENT_EVENT", ("2026-04",),
                  ClaimFinding.CONTRADICTED, ("EV-CYCLE-2026-04",), "late")
    assert _agreement_backstop(plain) == plain
