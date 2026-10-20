import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from synthgen import generator  # noqa: E402

SEED = 20261019


@pytest.fixture(scope="session")
def batch():
    return generator.generate(SEED, 1000)


@pytest.fixture(scope="session")
def trial():
    return generator.generate_trial(SEED)
