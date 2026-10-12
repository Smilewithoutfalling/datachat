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


@pytest.fixture(autouse=True)
def _isolate_outputs(tmp_path, monkeypatch):
    """测试产生的图表与运行记录写到临时目录，不污染仓库的 outputs/。"""
    from app.tools import persist
    charts = tmp_path / "charts"
    charts.mkdir()
    monkeypatch.setattr(persist, "CHART_DIR", str(charts))
    monkeypatch.setattr(persist, "RUNS_LOG", str(tmp_path / "runs.jsonl"))
    monkeypatch.setattr(persist, "ensure_dirs", lambda: None)
    import app.react_agent
    monkeypatch.setattr(app.react_agent, "ensure_dirs", lambda: None)


class MemoryKeyring:
    """测试用的内存钥匙串：测试绝不读写开发机上真实的凭据管理器。"""
    def __init__(self):
        import keyring.backend

        class _B(keyring.backend.KeyringBackend):
            priority = 1
            store = {}

            def get_password(self, service, username):
                return self.store.get((service, username))

            def set_password(self, service, username, password):
                self.store[(service, username)] = password

            def delete_password(self, service, username):
                import keyring.errors
                if (service, username) not in self.store:
                    raise keyring.errors.PasswordDeleteError("not found")
                del self.store[(service, username)]
        self.backend = _B()


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch):
    import keyring
    mk = MemoryKeyring()
    old = keyring.get_keyring()
    keyring.set_keyring(mk.backend)
    yield mk.backend
    keyring.set_keyring(old)
