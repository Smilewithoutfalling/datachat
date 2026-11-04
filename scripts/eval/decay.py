"""衰减曲线（EV-B6 步骤 4）：同一道题换数据形态后掉了多少分。

用法：
    python scripts/eval/decay.py docs/eval/<报告>.json [更多报告.json ...]

对每份报告：variant_kind 非空的行按 kind 分组算 pass_rate；基线 = 同报告里被指向的
variant_of 原题（没跑原题时该组的基线记 None，只报绝对通过率）。输出：

    kind            n   pass_rate   base_rate   decay_pp
    total_row       20     85.0%       95.0%      -10.0

只读报告，不算任何新判定 —— 判对与否以报告里的 correct 为准。
多份报告会合并展示（同 kind 跨报告取并集，逐题去重按 (报告, id)）。
"""
from __future__ import annotations

import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases") or []


def decay(rows: list[dict]) -> list[dict]:
    """[(kind, n, pass_rate, base_rate, decay_pp)]，按 kind 排序。"""
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        k = r.get("variant_kind") or ""
        if k:
            by_kind.setdefault(k, []).append(r)
    by_id = {r["id"]: r for r in rows if r.get("id")}

    out = []
    for kind in sorted(by_kind):
        vs = by_kind[kind]
        n = len(vs)
        passed = sum(1 for r in vs if r.get("correct"))
        pass_rate = passed / n * 100 if n else None
        # 基线：每条变体指向的原题，在本报告里跑过才作数
        bases = [by_id[r["variant_of"]] for r in vs
                 if r.get("variant_of") in by_id and by_id[r["variant_of"]].get("correct") is not None]
        base_rate = (sum(1 for r in bases if r.get("correct")) / len(bases) * 100) if bases else None
        decay_pp = (pass_rate - base_rate) if (pass_rate is not None and base_rate is not None) else None
        out.append({"kind": kind, "n": n, "passed": passed, "pass_rate": pass_rate,
                    "base_n": len(bases), "base_rate": base_rate, "decay_pp": decay_pp})
    return out


def main():
    paths = []
    for p in sys.argv[1:]:
        paths.extend(sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p])
    if not paths:
        raise SystemExit(__doc__)
    for path in paths:
        rel = os.path.relpath(path, REPO)
        rows = load_rows(path)
        table = decay(rows)
        print(f"\n== {rel} ==")
        if not table:
            print("  （报告里没有 variant_kind 非空的行 —— 这批没跑扰动题）")
            continue
        print(f"  {'kind':<16}{'n':>4}{'pass':>6}{'pass_rate':>11}{'base_rate':>11}{'decay_pp':>10}")
        for t in table:
            pr = f"{t['pass_rate']:.1f}%" if t["pass_rate"] is not None else "N/A"
            br = f"{t['base_rate']:.1f}%" if t["base_rate"] is not None else "N/A"
            dp = f"{t['decay_pp']:+.1f}" if t["decay_pp"] is not None else "N/A"
            print(f"  {t['kind']:<16}{t['n']:>4}{t['passed']:>6}{pr:>11}{br:>11}{dp:>10}")
        fails = [r["id"] for r in rows if (r.get("variant_kind") or "") and not r.get("correct")]
        if fails:
            print(f"  未通过: {', '.join(fails)}")


if __name__ == "__main__":
    main()
