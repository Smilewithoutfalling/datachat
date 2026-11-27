"""scripts/desktop/make_latest_json.py：latest.json 的结构符合 tauri-plugin-updater 的静态 JSON 格式（#149）。"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("make_latest_json", ROOT / "scripts" / "desktop" / "make_latest_json.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_latest_json_shape(tmp_path):
    setup = tmp_path / "DataChat_0.1.1_x64-setup.exe"
    setup.write_bytes(b"x")
    Path(str(setup) + ".sig").write_text("U0lH\n", encoding="utf-8")
    d = m.build("0.1.1", setup, "Smilewithoutfalling/datachat", "v0.1.1", "修复", datetime(2026, 11, 27, tzinfo=timezone.utc))
    assert d == {
        "version": "0.1.1",
        "notes": "修复",
        "pub_date": "2026-11-27T00:00:00Z",
        "platforms": {"windows-x86_64": {
            "signature": "U0lH",
            "url": "https://github.com/Smilewithoutfalling/datachat/releases/download/v0.1.1/DataChat_0.1.1_x64-setup.exe",
        }},
    }


def test_rejects_bad_version_and_empty_signature(tmp_path):
    setup = tmp_path / "a.exe"
    setup.write_bytes(b"x")
    Path(str(setup) + ".sig").write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        m.build("v0.1", setup, "o/r", "v0.1")
    with pytest.raises(ValueError):
        m.build("0.1.1", setup, "o/r", "v0.1.1")
