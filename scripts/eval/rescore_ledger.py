"""生成历史报告的重评台账：**记录值 vs 当前尺子重评**（规格 §EV-C1 / §EV-D1 的账）。

用法：
    python scripts/eval/rescore_ledger.py                # 默认扫 docs/eval/*.json
    python scripts/eval/rescore_ledger.py --out x.md
    python scripts/eval/rescore_ledger.py docs/eval/eval_react_*.json --json x.json

## 它解决的是什么问题

报告里的 `overall.correct` 是**跑模型时那把尺子**的结论。判分器后来改过（[114] 时间归一、
[116] 规则 16），同一批模型输出在新尺子下会得到不同判定。于是"引用报告里的数"和
"引用当前代码能复现的数"是两件事，混着引就会得出错误结论 —— [114] 实测 9 份老报告
净差 24 个题次，最大一份 80% → 92%。

**不回填**。报告是证据，改判定等于改证据（[4] 的惯例）。台账把两列并排放，
让读者一眼看出"这个数过期了"，而不是替他把证据改掉。

## 三列必须分清

- **记录值**：报告里写的 `overall.correct`。
- **当前重评**：`rescore()` 用现在的判分器重算同一批输出。
- **沿用原判**：报告里没有 `actual_obj`（早于阶段 1.5），重评无法还原，只能沿用记录值。
  这部分不是"重评结果"，不单独标出来就会把旧数当成新数。

## 为什么模型不用重跑

`rescore` 只读报告里的 `actual_obj` 与 `answer`，gold 在当前数据上重算。
所以差异 100% 来自判分器或答案表达式，与模型输出无关 —— 这一点在台账页首写明，
否则读者会以为模型变好了。
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import sys
import warnings
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval import report_adapter as adapter  # noqa: E402
from app.eval.fingerprint import code_fingerprint  # noqa: E402
from app.eval.rescore import rescore  # noqa: E402

# 分组是为了让"旧结论"能和"新数"对上：一个组就是当初一条对外结论
# （react 80%、workflow 70%、nodict 74%）。顺序即台账顺序。
GROUPS = (
    ("holdout_", "holdout 63 题"),
    ("eval_react_", "react"),
    ("eval_workflow_nodict_", "workflow 无字典"),
    ("eval_workflow_", "workflow + 字典"),
)


def group_of(name: str) -> str:
    for prefix, label in GROUPS:
        if name.startswith(prefix):
            return label
    return "其他"


def _pct(ok: int, n: int) -> str:
    return f"{100.0 * ok / n:.1f}%" if n else "-"


def _pp(ok_a: int, ok_b: int, n: int) -> str:
    """两列之间的百分点差。分母相同才能直接减，n 不同时返回 `-`。"""
    if not n:
        return "-"
    d = 100.0 * (ok_b - ok_a) / n
    return f"{d:+.1f}pp"


def _why_not_eval(kind: str) -> str:
    """非逐题报告为什么进不了这张表 —— 三种原因不一样，不能都写成一句套话。"""
    return {
        adapter.KIND_GATE: "闸门报告，`correct` 全为 null（判定在 human/auto 字段里），没有对照物",
        adapter.KIND_SUMMARY: "多次运行的汇总，没有逐题行",
        adapter.KIND_NOT_A_REPORT: "不是报告，没有逐题判定",
    }.get(kind, f"{kind}，没有逐题判定")


def collect(paths: list[str]) -> tuple[list[dict], list[str]]:
    """逐份重评。返回 (行, 跳过说明)。"""
    records, skipped = [], []
    for p in paths:
        name = os.path.basename(p)
        try:
            data = adapter.load(p)
        except adapter.ReportError as e:
            skipped.append(f"{name}：{str(e).split(': ', 1)[-1]}")
            continue
        kind = adapter.kind_of(data)
        if kind != adapter.KIND_EVAL:
            # 闸门报告的 `correct` 全为 null（判定在 human/auto 两个字段里），
            # 拿它做"记录值 vs 重评"没有对照物；summary 没有逐题行。
            skipped.append(f"{name}：{_why_not_eval(kind)}")
            continue
        rec = (data.get("overall") or {}).get("correct")
        if rec is None:
            skipped.append(f"{name}：报告里没有 `overall.correct`")
            continue

        buf = io.StringIO()
        try:
            # pandas 的 DtypeWarning 会在重评时喷几十行，台账不是数据质量工具，
            # 只吞警告不吞异常：真错误照旧走下面的 except。
            with warnings.catch_warnings(), contextlib.redirect_stdout(buf):
                warnings.simplefilter("ignore")
                res = rescore(p)
        except (FileNotFoundError, ValueError) as e:
            skipped.append(f"{name}：重评失败（{str(e).splitlines()[0]}）")
            continue

        records.append({
            "report": name,
            "group": group_of(name),
            "n": res["n"],
            "recorded": int(rec),
            "current": res["correct"],
            "carried": len(res["skipped_no_obj"]),
            "changed": res["changed"],
            "bank_drift": res.get("bank_drift"),
            # rescore 的完整输出，只进 `--json`，不进展表：漂移段的要点（两边哈希 + 后果）
            # 正文已经写了，把 stdout 原样贴进来只会重复一遍，还会带出 pandas 的零碎告警。
            "drift_note": buf.getvalue().strip(),
        })
    return records, skipped


def _group_totals(records: list[dict]) -> list[tuple[str, int, int, int, int]]:
    """(组, 份数, 题次, 记录值合计, 当前合计)，按 GROUPS 顺序。"""
    order = [g for _, g in GROUPS] + ["其他"]
    out = []
    for g in order:
        items = [r for r in records if r["group"] == g]
        if not items:
            continue
        out.append((g, len(items), sum(r["n"] for r in items),
                    sum(r["recorded"] for r in items), sum(r["current"] for r in items)))
    return out


def render_md(records: list[dict], skipped: list[str]) -> str:
    fp = code_fingerprint()["affects_results_sha256"][:12]
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# 历史报告重评台账",
        "",
        f"生成：{now}　判分指纹：`{fp}`",
        "",
        "**模型一次都没有重跑。** 这张表比的是同一批模型输出、两把尺子的结论：",
        "「记录值」= 报告里写的 `overall.correct`（跑模型当时那把尺子）；",
        "「当前重评」= 现在的判分器对同一批输出重算。差异只可能来自判分器或答案表达式。",
        "",
        "**不回填。** 报告是证据，改判定等于改证据。两列并排是为了让人看出哪个数过期，",
        "不是替他把证据改掉。引用历史结论时以「当前重评」为准，并带上「记录值于何时」。",
        "",
        "## 一、分组总账",
        "",
        "| 组 | 份数 | 题次 | 记录值 | 当前重评 | 差 |",
        "|---|---|---|---|---|---|",
    ]
    for g, cnt, n, rec, cur in _group_totals(records):
        lines.append(f"| {g} | {cnt} | {n} | {rec}/{n} {_pct(rec, n)} | "
                     f"{cur}/{n} {_pct(cur, n)} | {_pp(rec, cur, n)} |")

    tot_n = sum(r["n"] for r in records)
    tot_rec = sum(r["recorded"] for r in records)
    tot_cur = sum(r["current"] for r in records)
    lines += [
        f"| **合计** | {len(records)} | {tot_n} | {tot_rec}/{tot_n} {_pct(tot_rec, tot_n)} | "
        f"{tot_cur}/{tot_n} {_pct(tot_cur, tot_n)} | {_pp(tot_rec, tot_cur, tot_n)} |",
        "",
        "## 二、逐份",
        "",
        "| 报告 | n | 记录值 | 当前重评 | 差 | 变化题 | 沿用原判 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in records:
        changed = r["changed"]
        if changed:
            up = sum(1 for c in changed if c["after"] and not c["before"])
            down = sum(1 for c in changed if c["before"] and not c["after"])
            ids = "、".join(
                f"{c['id']}{'↑' if c['after'] else '↓'}" for c in changed[:8]
            ) + (f" 等 {len(changed)} 题" if len(changed) > 8 else "")
            cell = f"{up} 涨 {down} 跌：{ids}" if down else f"{up} 题翻正：{ids}"
        else:
            cell = "-"
        lines.append(
            f"| `{r['report']}` | {r['n']} | {r['recorded']} {_pct(r['recorded'], r['n'])} | "
            f"{r['current']} {_pct(r['current'], r['n'])} | "
            f"{_pp(r['recorded'], r['current'], r['n'])} | {cell} | {r['carried']} |"
        )

    # 后两段是条件出现的，序号不能写死：没有漂移时"跳过的文件"就是第三节，
    # 写死成"四"会让人以为中间漏了一节。
    blocks: list[tuple[str, list[str]]] = []
    drifted = [r for r in records if r["bank_drift"]]
    if drifted:
        body = ["这些报告记的题库哈希与现在的 `questions.json` 对不上，重评用的是**现在的**题面与答案。",
                "它们的差异里混着「尺子变了」和「答案变了」两件事，不能都算到判分器头上。",
                "",
                "⚠️ 只有 `questions.json` 有哈希，`answers.json` 没有。所以"
                "**「没进这一节」只说明题面没变，不等于标准答案没变** —— 后者改过是看不出来的。",
                ""]
        for r in drifted:
            d = r["bank_drift"]
            body.append(f"- `{r['report']}`：报告记 `{d['report'][:12]}`，"
                        f"题库现在 `{d['bank'][:12] if d['bank'] else '(无)'}`"
                        f"{'（题库为空）' if not d['bank'] else ''}")
        blocks.append(("题库版本漂移", body))
    if skipped:
        blocks.append(("跳过的文件", [f"- {s}" for s in skipped]))

    nums = "一二三四五六七八九十"
    notes: list[str] = []
    # 一、二两段已经写在上面，条件段从"三"开始编。
    for i, (title, body) in enumerate(blocks, start=2):
        notes += ["", f"## {nums[i]}、{title}", "", *body]
    return "\n".join(lines + notes) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="历史报告重评台账（记录值 vs 当前重评）")
    ap.add_argument("paths", nargs="*", default=[os.path.join("docs", "eval", "*.json")],
                    help="报告路径或 glob，默认 docs/eval/*.json")
    ap.add_argument("--out", default=os.path.join("docs", "eval", "RESCORE-LEDGER.md"))
    ap.add_argument("--json", dest="json_out", default=None, help="另存机器可读结果")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    paths = []
    for p in args.paths:
        hits = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        paths.extend(hits or [p])

    records, skipped = collect(paths)
    if not records:
        print("没有可对照的报告（需要含 overall.correct 的逐题报告）", file=sys.stderr)
        return 1

    md = render_md(records, skipped)
    out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    if args.json_out:
        jp = args.json_out if os.path.isabs(args.json_out) else os.path.join(ROOT, args.json_out)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1, default=str)
        if not args.quiet:
            print(f"JSON: {jp}")

    if not args.quiet:
        for g, cnt, n, rec, cur in _group_totals(records):
            print(f"  {g:16s} {cnt:2d} 份  {rec}/{n} -> {cur}/{n}  {_pp(rec, cur, n)}")
        moved = sum(1 for r in records if r["changed"])
        print(f"\n{len(records)} 份报告，{moved} 份判定有变；跳 {len(skipped)} 个文件。")
        print(f"台账: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
