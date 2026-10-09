import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
import pytest


@pytest.fixture
def sample_path():
    return os.path.join(ROOT, "data", "sample.csv")


@pytest.fixture
def sample_df(sample_path):
    return pd.read_csv(sample_path)


@pytest.fixture
def chart_path(tmp_path):
    return str(tmp_path / "chart.png")
