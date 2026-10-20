"""Same seed -> byte-identical output; different seed -> different output."""
import json

from hypothesis import given, settings, strategies as st

from synthgen import cli, generator


def _bytes(data):
    return {k: "".join(json.dumps(r, sort_keys=True) + "\n" for r in data[k]) for k in ("acdvs", "accounts", "labels")}


def test_same_seed_identical_in_process():
    assert _bytes(generator.generate(5, 150)) == _bytes(generator.generate(5, 150))


def test_different_seed_differs():
    assert _bytes(generator.generate(5, 150))["acdvs"] != _bytes(generator.generate(6, 150))["acdvs"]


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_determinism_property(seed):
    assert _bytes(generator.generate(seed, 100)) == _bytes(generator.generate(seed, 100))


def test_cli_files_identical_across_runs(tmp_path):
    m1 = cli.write_set(tmp_path / "a", 99, generator.generate(99, 120))
    m2 = cli.write_set(tmp_path / "b", 99, generator.generate(99, 120))
    assert m1["files_sha256"] == m2["files_sha256"]
    for f in ("acdvs.jsonl", "sor_accounts.jsonl", "labels.jsonl", "manifest.json"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()


def test_trial_deterministic(tmp_path):
    cli.write_trial(tmp_path / "a", 20261019)
    cli.write_trial(tmp_path / "b", 20261019)
    for f in ("trial_cases.md", "label_sheet.csv", "acdvs.jsonl"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()
    h = "_HIDDEN_generator_labels"
    assert (tmp_path / f"a{h}" / "labels.jsonl").read_bytes() == (tmp_path / f"b{h}" / "labels.jsonl").read_bytes()


def test_committed_fixture_matches_regeneration(tmp_path):
    """The committed 200-case fixture set is exactly what the generator produces today."""
    from pathlib import Path
    committed = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seed20261019_n200"
    m = cli.write_set(tmp_path, 20261019, generator.generate(20261019, 200))
    stored = json.loads((committed / "manifest.json").read_text())
    assert stored["files_sha256"] == m["files_sha256"]
