"""R-34: no eval-case text in the prompt library."""
from pathlib import Path

from synthgen import isolation

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def test_prompt_library_clean(batch, trial):
    hs = isolation.eval_hashes(batch["acdvs"] + trial["acdvs"], batch["labels"] + trial["labels"])
    assert hs
    assert isolation.contaminated_files(PROMPTS, hs) == []


def test_check_detects_contamination(tmp_path, batch):
    hs = isolation.eval_hashes(batch["acdvs"], batch["labels"])
    quote = next(c["quote"] for l in batch["labels"] for c in l["claims"] if len(c["quote"]) >= 25)
    (tmp_path / "fewshot.txt").write_text("Example letter:\n" + quote.upper() + "\n")
    assert isolation.contaminated_files(tmp_path, hs)
