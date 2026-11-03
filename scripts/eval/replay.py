"""回放历史报告：逐份解析，报告结构，不判对错（规格 §EV-D1 / §6 第 3 步）。

用法：
    python scripts/eval/replay.py docs/eval/*.json --check

输出每份文件的 kind / schema_version / 行数 / 缺字段数 / 待判数 / missing_runs。

## 什么算失败

- 文件读不了、不是合法 JSON、顶层不是对象 → **失败**。
- 是逐题报告但单题行缺 `id` / `category` / `question` → **失败**（结构坏了，后续没法配对）。
- `*_summary.json` 里 `runs[].file` 指向的文件不存在 → **不算失败**，记 `missing_runs`。
  那批文件在 `outputs/`，被 `.gitignore` 排除；新克隆的仓库里本来就没有。
- `baselines.json` 这种非报告文件 → 不算失败，但要**认出来并单独列**，
  不能当成"零行报告"混进统计。

## 什么不算失败但必须显示

- `待判`（三个判定字段全空）：闸门报告人工没签字，是已知状态。
- `无match`（判对但报告没记 `match`）：18 份评测报告天生如此，规格 §1.1.1 定为 legacy。

这两列是给人看的数据质量信号，不是验收门槛。把它们算成失败会让 `--check`
在任何一份历史报告上永远红着，那样红灯就没意义了。
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval import report_adapter as adapter  # noqa: E402
from app.eval.report_md import _dw, _pad  # noqa: E402

HEADERS = ("文件", "kind", "schema", "行数", "缺字段", "待判", "无match", "missing_runs")


def _expand(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for p in patterns:
        hits = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        if not hits:
            out.append(p)          # 让 inspect 报"文件不存在"，而不是静默少一行
        out.extend(hits)
    # 去重保序
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="回放历史报告，检查结构完整性")
    ap.add_argument("paths", nargs="+", help="报告路径或 glob（记得给 shell 加引号或让它展开）")
    ap.add_argument("--check", action="store_true", help="有失败则退出码 1（验收用）")
    ap.add_argument("--quiet", action="store_true", help="只打汇总，不打逐份表")
    args = ap.parse_args(argv)

    paths = _expand(args.paths)
    if not paths:
        print("错误：没有匹配到任何文件", file=sys.stderr)
        return 1

    infos, failures, skipped = [], [], []
    for p in paths:
        try:
            info = adapter.inspect(p)
        except adapter.ReportError as e:
            failures.append((p, str(e)))
            infos.append({"path": p, "report": os.path.basename(p), "kind": "FAILED",
                          "schema_version": None, "n": 0, "missing_fields": {},
                          "pending": 0, "no_match_when_correct": 0, "missing_runs": []})
            continue

        if info["kind"] == adapter.KIND_NOT_A_REPORT:
            skipped.append(info)
            continue

        if info["missing_fields"]:
            detail = "、".join(f"{k}×{v}" for k, v in sorted(info["missing_fields"].items()))
            failures.append((p, f"单题行缺必填字段：{detail}"))
        infos.append(info)

    if not args.quiet:
        cells = []
        for i in infos:
            if i["kind"] == "FAILED":
                continue
            miss = sum(i["missing_fields"].values())
            cells.append([
                i["report"],
                i["kind"],
                str(i["schema_version"]),
                str(i["n"]),
                str(miss),
                str(i["pending"]),
                str(i["no_match_when_correct"]),
                str(len(i["missing_runs"])) if i["missing_runs"] else "-",
            ])

        widths = [_dw(h) for h in HEADERS]
        for r in cells:
            for j, c in enumerate(r):
                widths[j] = max(widths[j], _dw(c))
        fmt = lambda vals: "  ".join(_pad(v, widths[j]) for j, v in enumerate(vals))
        print(fmt(list(HEADERS)))
        print("  ".join("-" * w for w in widths))
        for r in cells:
            print(fmt(r))

        for i in infos:
            if i["missing_runs"]:
                joined = ", ".join(i["missing_runs"])
                print(f"\n  {i['report']} 缺 run 文件：{joined}")

    reports = [i for i in infos if i["kind"] not in ("FAILED", adapter.KIND_NOT_A_REPORT)]
    print()
    print(f"共 {len(paths)} 个文件：{len(reports)} 份报告解析成功，"
          f"{len(failures)} 份失败，{len(skipped)} 个非报告文件已跳过。")
    for s in skipped:
        print(f"  跳过 {s['report']}：{s['note']}")

    if failures:
        print("\n失败明细：")
        for p, why in failures:
            print(f"  ✗ {p}\n    {why}")

    if args.check and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
