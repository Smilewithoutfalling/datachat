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
    wf = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
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
    assert 'ReadEnvStr $UnDataDir "DATACHAT_HOME"' in un_init
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
