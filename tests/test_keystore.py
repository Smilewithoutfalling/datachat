"""阶段 4：API Key 进系统钥匙串。conftest 已把钥匙串换成内存实现。"""
import keyring
import pytest

from app.core import keystore
from app.core.llm import LLMConfig


def test_roundtrip_and_resolve_order(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert keystore.resolve_api_key() == (None, None)
    keystore.set_api_key("  sk-from-keyring \n")
    assert keystore.get_api_key() == "sk-from-keyring"
    assert keystore.resolve_api_key() == ("sk-from-keyring", "keyring")
    assert LLMConfig.from_env().api_key == "sk-from-keyring"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")            # 环境变量显式设置时优先
    assert keystore.resolve_api_key() == ("sk-env", "env")
    assert keystore.delete_api_key() is True and keystore.delete_api_key() is False


@pytest.mark.parametrize("bad", ["", "   ", "sk-a sk-b"])
def test_rejects_bad_key(bad):
    with pytest.raises(keystore.KeyStoreError):
        keystore.set_api_key(bad)


def test_unavailable_backend_is_unconfigured_not_crash(monkeypatch):
    """无桌面的 Linux / CI 没有钥匙串后端：读取按"未配置"处理，写入给出明确错误。"""
    from keyring.backends.fail import Keyring as Fail
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    keyring.set_keyring(Fail())
    assert keystore.resolve_api_key() == (None, None)
    with pytest.raises(keystore.KeyStoreError, match="不可用"):
        keystore.set_api_key("sk-x")


def test_config_repr_and_errors_never_contain_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    keystore.set_api_key("sk-very-secret")
    assert "sk-very-secret" not in repr(LLMConfig.from_env())
    assert keystore.main(["status"]) == 0
    out = capsys.readouterr()
    assert "sk-very-secret" not in out.out + out.err and "已保存" in out.out


def test_migrate_from_env_file(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_MODEL=x\nDEEPSEEK_API_KEY=sk-in-dotenv\n", encoding="utf-8")
    assert keystore.main(["migrate", "--env-file", str(env)]) == 0
    assert keystore.get_api_key() == "sk-in-dotenv"
    assert "sk-in-dotenv" not in capsys.readouterr().out
    assert keystore.main(["status", "--env-file", str(env)]) == 0
    assert "仍有明文" in capsys.readouterr().out


def test_set_via_getpass(monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-typed")
    assert keystore.main(["set"]) == 0 and keystore.get_api_key() == "sk-typed"


def test_sandbox_cannot_import_keyring(sample_df, chart_path):
    from app.tools.sandbox import run_code
    _, _, err = run_code("import keyring\nresult = keyring.get_password('datachat', 'llm_api_key')",
                         sample_df, chart_path)
    assert err and "keyring" in err
