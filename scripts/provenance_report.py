"""扫描评测报告里的答案来源归因，把"要人看的清单"打出来。

用法：
    python scripts/provenance_report.py outputs/eval_v4_mul_state_run*.json
    python scripts/provenance_report.py outputs/eval_react_*.json --only literal
    python scripts/provenance_report.py outputs/xxx.json --only missing

为什么要有这个脚本：缺口 12 想防"模型没算就编答案"，但**没有可靠的自动判据**。
150 题三跑实测 481 份代码里 40 份的 `result` 是字面量，其中 **38 份判对** ——
`result = 2537.39`、`result = 850854.16` 都是模型算完再写死。任何"字面量即错"的规则
都会误杀它们。所以只能：机器把清单缩到几十条，人五分鐘看完。

老报告没有 `result_origin` 字段（该字段 2026-11-02 才加），这里现场用
`app.eval.provenance` 从 `code` 重算，所以历史报告也能扫。
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.eval.provenance import result_origin  # noqa: E402


def _paths(patterns):
    out = []
    for p in patterns:
        hit = glob.glob(p) or ([p] if os.path.exists(p) else [])
        out.extend(sorted(hit))
    return out


def _origin_of(row):
    """优先用报告里存的字段；老报告没有就从 code 重算。"""
    if "result_origin" in row:
        return row["result_origin"]
    return result_origin(row.get("code") or "")


def _last_write_line(code, name="result"):
    """取最后一次给 result 赋值的那一行源码，比"代码最后一行"准确（末行常是 print）。"""
    line = ""
    for raw in (code or "").splitlines():
        s = raw.strip()
        if s.startswith(f"{name} ") or s.startswith(f"{name}=") or s.startswith(f"{name}["):
            if "=" in s:
                line = s
    return line[:110]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", help="报告 JSON 路径，支持通配符")
    ap.add_argument("--only", choices=["literal", "missing", "all"], default="all")
    ap.add_argument("--max", type=int, default=0, help="清单最多列几条（0 = 不限）")
    args = ap.parse_args()

    paths = _paths(args.reports)
    if not paths:
        print("没有匹配到报告文件")
        return 1

    for path in paths:
        data = json.load(open(path, encoding="utf-8"))
        rows = data.get("cases") or []
        origins = collections.Counter()
        missing = collections.Counter()
        lits, miss_rows = [], []
        for r in rows:
            code = r.get("code") or ""
            if not code:
                continue
            o = _origin_of(r)
            origins[o] += 1
            if str(o).startswith("literal"):
                lits.append((r.get("id"), bool(r.get("correct")), o, _last_write_line(code)))
            m = r.get("result_missing")
            if m:
                missing[m] += 1
                miss_rows.append((r.get("id"), bool(r.get("correct")), m))

        n = sum(origins.values())
        head = f"{os.path.basename(path)}   {data.get('time', '?')}   n={len(rows)}"
        fp = data.get("fingerprints") or {}
        print(f"\n=== {head}")
        print(f"    指纹: evalset={fp.get('evalset_sha12')}  code={fp.get('code_sha12')}  "
              f"memory={fp.get('memory_mode')}  agent={fp.get('agent')}")
        print(f"    有代码 {n} 条：" + "  ".join(
            f"{k}={v}({v / max(n, 1) * 100:.1f}%)" for k, v in origins.most_common()))
        if missing:
            print("    没交卷：" + "  ".join(f"{k}={v}" for k, v in missing.most_common()))

        if args.only in ("all", "literal") and lits:
            print(f"\n    -- result 是字面量 {len(lits)} 条（判对 {sum(1 for x in lits if x[1])}）--")
            shown = sorted(lits, key=lambda x: x[1])          # 先列判错的
            if args.max:
                shown = shown[:args.max]
            for cid, ok, kind, line in shown:
                print(f"    {'✓' if ok else '✗'} {cid:<10} {kind:<18} {line}")

        if args.only in ("all", "missing") and miss_rows:
            print(f"\n    -- 没交卷 {len(miss_rows)} 条 --")
            shown = miss_rows[:args.max] if args.max else miss_rows
            for cid, ok, kind in shown:
                print(f"    {'✓' if ok else '✗'} {cid:<10} {kind}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
