"""生成自动更新用的 latest.json（phase6-desktop.md §4 第 3 条，issue #149；release.yml 调用）。

格式见 tauri-plugin-updater「Static JSON File」：version、notes、pub_date、platforms.windows-x86_64.{signature, url}。
signature 是 .sig 文件的**内容**（不是路径），url 指向同一个 Release 里的安装包。

    python scripts/desktop/make_latest_json.py --version 0.1.1 --setup <setup.exe> --repo owner/name --tag v0.1.1 \
        [--notes "..."] --out latest.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def build(version: str, setup: Path, repo: str, tag: str, notes: str = "", now: datetime | None = None) -> dict:
    if not SEMVER.match(version):
        raise ValueError(f"版本号不是 SemVer：{version}")
    sig = Path(str(setup) + ".sig")
    signature = sig.read_text(encoding="utf-8").strip()
    if not signature:
        raise ValueError(f"签名文件是空的：{sig}")
    url = f"https://github.com/{repo}/releases/download/{quote(tag)}/{quote(setup.name)}"
    pub = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": version,
        "notes": notes,
        "pub_date": pub,
        "platforms": {"windows-x86_64": {"signature": signature, "url": url}},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--setup", required=True, type=Path)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    data = build(a.version, a.setup, a.repo, a.tag, a.notes)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
