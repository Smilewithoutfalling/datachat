"""桌面安装器与数据文件夹解析（phase6-desktop.md §3b，issue #148）。

安装器本身只能在 Windows CI 上真装（desktop.yml），这里钉住几处跨文件的一致性和 Python 侧的解析顺序：
- 注册表位置三处一致：installer.nsi 的 MANUPRODUCTKEY（由 tauri.conf.json 的 identifier / productName 推出）、
  sidecar.rs 的 DATA_DIR_REG_KEY、app/server/app.py 的 DATA_DIR_REG_KEY；
- 自带模板的来源版本与 CI 固定的 @tauri-apps/cli 版本一致；
- 卸载只删 DataChat 自己的文件，对数据文件夹本身不做递归删除；清单覆盖 app 实际落盘的位置；
- default_home：DATACHAT_HOME → 注册表 DataDir → 默认。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.server import app as server_app

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "desktop" / "src-tauri"


def _conf() -> dict:
    return json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))


def test_registry_key_matches_installer_manufacturer_and_shell():
    conf = _conf()
    # Tauri：publisher 未设时 manufacturer = identifier 第二段（tauri-bundler nsis/mod.rs）
    assert "publisher" not in conf.get("bundle", {}), "设了 publisher 会改掉注册表键，已装用户读不到上次的目录"
    manufacturer = conf["identifier"].split(".")[1]
    expected = f"Software\\{manufacturer}\\{conf['productName']}"
    assert server_app.DATA_DIR_REG_KEY == expected
    rs = (TAURI / "src" / "sidecar.rs").read_text(encoding="utf-8")
    m = re.search(r'pub const DATA_DIR_REG_KEY: &str = r"([^"]+)";', rs)
    assert m and m.group(1) == expected
    assert f'pub const DATA_DIR_REG_VALUE: &str = "{server_app.DATA_DIR_REG_VALUE}";' in rs
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    assert '!define MANUKEY "Software\\${MANUFACTURER}"' in nsi
    assert '!define MANUPRODUCTKEY "${MANUKEY}\\${PRODUCTNAME}"' in nsi
    assert f'WriteRegStr SHCTX "${{MANUPRODUCTKEY}}" "{server_app.DATA_DIR_REG_VALUE}" $DataDir' in nsi


def test_template_is_wired_and_pinned_to_ci_cli_version():
    nsis = _conf()["bundle"]["windows"]["nsis"]
    assert nsis["template"] == "./installer.nsi"
    assert nsis["installerHooks"] == "./hooks.nsh"
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    m = re.search(r"tag tauri-cli-v(\d+\.\d+\.\d+)", nsi)
    assert m, "模板文件头要写来源 tag"
    wf = "".join((ROOT / ".github" / "workflows" / f).read_text(encoding="utf-8") for f in ("desktop.yml", "release.yml"))
    pins = set(re.findall(r"@tauri-apps/cli@(\S+)", wf))
    assert pins == {m.group(1)}, f"CI 的 CLI 版本 {pins} 与模板来源 {m.group(1)} 不一致"


def test_template_default_install_dir_is_separate_from_data_dir():
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\${PRODUCTNAME}"' in nsi
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"' not in nsi
    # 数据文件夹页：升级 / passive / update 跳过；静默安装用 /DATADIR=
    assert "Page custom DataDirPage DataDirPageLeave" in nsi
    assert nsi.index("!insertmacro MUI_PAGE_DIRECTORY") < nsi.index("Page custom DataDirPage")
    assert '${GetOptions} $CMDLINE "/DATADIR=" $0' in nsi
    assert "${AndIf} $IsUpgrade = 0" in nsi


def _hook_body() -> str:
    return (TAURI / "hooks.nsh").read_text(encoding="utf-8")


def test_uninstall_deletes_only_datachat_files():
    body = _hook_body()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith(";"))
    assert 'RMDir /r "$UnDataDir"' not in code
    assert 'RMDir "$UnDataDir"' in code
    deleted = set(re.findall(r'Delete "\$UnDataDir\\([^"]+)"', code))
    rm_dirs = set(re.findall(r'RMDir /r "\$UnDataDir\\([^"]+)"', code))
    assert {"datachat.db", "server.log"} <= deleted
    # app 在 home 下建的子目录（create_app 的 makedirs）都要在清单里
    src = (ROOT / "app" / "server" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'for d in \(([^)]*)\):\s*\n\s*os\.makedirs\(os\.path\.join\(home, d\)', src)
    assert m, "create_app 建子目录的写法变了，请同步卸载清单"
    made = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert made <= rm_dirs, f"卸载清单缺子目录：{made - rm_dirs}"
    assert 'os.path.join(home, "datachat.db")' in src
    main = (ROOT / "app" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert 'os.path.join(app.state.home, "server.log")' in main


def test_uninstall_reads_data_dir_before_official_key_cleanup():
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    un_init = nsi[nsi.index("Function un.onInit"):nsi.index("Section Uninstall")]
    assert 'ReadRegStr $UnDataDir SHCTX "${MANUPRODUCTKEY}" "DataDir"' in un_init
    # env 先读进 $0 去首尾空格（审查 B9），再落到 $UnDataDir；顺序仍是 env → 注册表 → 默认
    assert 'ReadEnvStr $0 "DATACHAT_HOME"' in un_init and "Call un.TrimSpaces" in un_init
    assert un_init.index("DATACHAT_HOME") < un_init.index("ReadRegStr $UnDataDir")


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", os.path.join(os.sep, "lad"))
    return monkeypatch


def test_default_home_env_wins(clean_env):
    clean_env.setenv("DATACHAT_HOME", "/env/home")
    clean_env.setattr(server_app, "_registry_data_dir", lambda: "/reg/home")
    assert server_app.default_home() == "/env/home"


def test_default_home_blank_env_falls_through_to_registry(clean_env):
    clean_env.setenv("DATACHAT_HOME", "   ")
    clean_env.setattr(server_app, "_registry_data_dir", lambda: "/reg/home")
    assert server_app.default_home() == "/reg/home"


def test_default_home_falls_back_to_localappdata(clean_env):
    clean_env.setattr(server_app, "_registry_data_dir", lambda: None)
    assert server_app.default_home() == os.path.join(os.sep, "lad", "datachat")


@pytest.mark.skipif(os.name == "nt", reason="非 Windows 才断言不读注册表")
def test_registry_is_not_read_off_windows():
    assert server_app._registry_data_dir() is None


# ---------------------------------------------------------------- 旧数据目录启动（#148 §9 / 节点 2）
def test_old_data_dir_survives_restart_via_registry_resolution(tmp_path, clean_env, sample_path):
    """升级或重装后，程序按「注册表 DataDir」找到原来的数据文件夹：旧会话、旧数据集、旧消息都在。
    沿用 test_web.py::test_v1_database_gains_feedback_table_without_touching_old_tables 的做法：
    先在一个数据目录里跑完一轮，再用 home=None（走 default_home 解析）新建 app 读回。"""
    from fastapi.testclient import TestClient
    from tests.test_core_analyze import wf_model
    from tests.test_server import H, TOKEN
    from tests.test_web import _one_turn

    data = str(tmp_path / "我的数据")
    c = TestClient(server_app.create_app(
        data, TOKEN, chat_model_factory=lambda: wf_model(["result = int(df['units'].sum())"], answer="总销量 1685")))
    sid, mid, _ = _one_turn(c, sample_path)
    ds_before = c.get("/datasets", headers=H).json()
    del c

    clean_env.setattr(server_app, "_registry_data_dir", lambda: data)
    assert server_app.default_home() == data
    c2 = TestClient(server_app.create_app(None, TOKEN))
    assert os.path.abspath(c2.app.state.home) == os.path.abspath(data)
    assert c2.get("/datasets", headers=H).json() == ds_before
    sess = c2.get(f"/sessions/{sid}", headers=H).json()
    assert [m["id"] for m in sess["messages"]][-1] == mid
    assert any(s["id"] == sid for s in c2.get("/sessions", headers=H).json())


def test_installer_rejects_unsafe_data_dirs_by_rule():
    """B1–B3 补强后的校验规则都在模板里（真正的行为由 desktop CI ⓪ 段在 Windows 上验）。"""
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    body = nsi[nsi.index("Function ValidateDataDir"):]
    body = body[:body.index("FunctionEnd")]
    # GetFullPathName 在路径不存在时返回空（新装时数据文件夹、安装目录都还没建），CI 红过一次（run 45922407138），不许再用
    assert "GetFullPathName " not in body.replace("; 不用 GetFullPathName", "")
    for needle in ('StrCpy $1 "\\..\\"', 'StrCpy $1 "\\.\\"', 'StrCpy $1 "/"', 'StrCpy $1 "%"',
                   '${If} $1 <= 3', '${AndIfNot} ${FileExists} "$DataDir\\datachat.db"', 'FindFirst $6 $7'):
        assert needle in body, needle
    hook = _hook_body()
    assert '${AndIf} ${FileExists} "$UnDataDir\\datachat.db"' in hook


def test_tail_fixes_b4_env_and_normalization_bypass():
    """#148 第二轮审查问题 1/2/4：没选过数据文件夹的新装也查重叠；DATACHAT_HOME 的文件夹卸载不删；
    拒绝 ? ~ $ 和以点 / 空格结尾的段。运行时行为由 desktop CI ⓪ / ⓪b 段在 Windows 上验。"""
    nsi = (TAURI / "installer.nsi").read_text(encoding="utf-8")
    sec = nsi[nsi.index("Section Install"):]
    sec = sec[:sec.index("SetOutPath $INSTDIR")]
    assert "${ElseIf} $IsUpgrade = 0" in sec and "StrCpy $R3 0" in sec
    body = nsi[nsi.index("Function ValidateDataDir"):]
    body = body[:body.index("FunctionEnd")]
    for needle in ('StrCpy $1 "?"', 'StrCpy $1 "~"', 'StrCpy $1 "$$"', 'StrCpy $1 ".\\"', 'StrCpy $1 " \\"',
                   "Goto overlap", "  overlap:"):
        assert needle in body, needle
    # mode 0 只跳过字符规则和「非空」规则，不跳过重叠检查
    assert body.index("  overlap:") < body.index("数据文件夹不能与安装目录相同")
    un_init = nsi[nsi.index("Function un.onInit"):nsi.index("Section Uninstall")]
    assert "StrCpy $UnFromEnv 1" in un_init
    assert "${AndIf} $UnFromEnv <> 1" in _hook_body()


def test_updater_config_matches_phase6_section4():
    """#149：endpoint 指向 GitHub Releases 的 latest.json；Windows 用 passive；PR 构建不生成更新签名。"""
    conf = _conf()
    up = conf["plugins"]["updater"]
    assert up["endpoints"] == ["https://github.com/Smilewithoutfalling/datachat/releases/latest/download/latest.json"]
    assert up["windows"]["installMode"] == "passive"
    assert "pubkey" in up
    assert "createUpdaterArtifacts" not in conf["bundle"], "签名只在 release.yml 里开（PR 构建没有私钥）"
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert '"createUpdaterArtifacts":true' in rel and "TAURI_SIGNING_PRIVATE_KEY" in rel
    assert "workflow_dispatch" in rel and "\n  push:" not in rel


def test_updater_pubkey_is_the_one_s_generated():
    """#149：公钥由 S 本机 gen_update_key.py 生成（11-27 14:00 发来），key id FAAA8FE893455A0D。
    换公钥 = 已装用户再也收不到更新（HANDOVER §8），所以钉死。"""
    import base64
    pk = _conf()["plugins"]["updater"]["pubkey"]
    text = base64.b64decode(pk).decode()
    assert text.splitlines()[0] == "untrusted comment: minisign public key: FAAA8FE893455A0D"
    raw = base64.b64decode(text.splitlines()[1])
    assert len(raw) == 42 and raw[:2] == b"Ed" and raw[2:10][::-1].hex().upper() == "FAAA8FE893455A0D"
