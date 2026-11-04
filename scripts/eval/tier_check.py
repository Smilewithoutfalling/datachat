"""按档位校验一份报告够不够格当"跑通了"的证据。

**三档的红灯只判「能不能跑完、报告结构完不完整」，不判准确率。** 8 题里翻 1 题就是
12.5pp，任何门槛拦住的都是噪声（双侧精确 McNemar 要 6:0 才显著，EV-C2）。理由与选题
见 `docs/eval/tiers.md`。

唯一例外是 `--require-all`：PR 档的 oracle 用假模型，输出就是标准答案，判错只能说明
判分链路坏了 —— 那种情况必须红。

结构检查不在这里重写：`report_adapter.inspect()` 已经在算 `n` / `missing_fields` /
`conflicts`，本脚本只加"题数期望"与"必须全对"两条档位判据。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval import report_adapter as A  # noqa: E402


def evaluate(path: str, expect_n: int | None = None, require_all: bool = False,
             kind: str = A.KIND_EVAL) -> tuple[dict, list[str]]:
    """返回 (inspect 结果, 问题列表)。问题列表为空 = 这一档通过。"""
    info = A.inspect(path)
    problems: list[str] = []
    if info["kind"] != kind:
        note = f"（{info['note']}）" if info.get("note") else ""
        return info, [f"不是 {kind} 报告，实际 kind={info['kind']}{note}"]
    if expect_n is not None and info["n"] != expect_n:
        problems.append(f"题数 {info['n']} ≠ 期望 {expect_n}")
    if info["missing_fields"]:
        problems.append("缺字段：" + "、".join(f"{k}×{v}" for k, v in sorted(info["missing_fields"].items())))
    if info["conflicts"]:
        problems.append(f"{len(info['conflicts'])} 行判定字段互相矛盾")
    if require_all:
        rows = list(A.iter_rows(path))
        wrong = [r.id for r in rows if not r.correct]
        if wrong:
            problems.append(f"判错 {len(wrong)} 题：{'、'.join(wrong[:10])}"
                            + ("…" if len(wrong) > 10 else ""))
        # clarify 题的正确行为就是**不执行**（反问，而不是猜着算）。把它们算进
        # "没有执行成功"会让 PR 档永久红 —— 红的原因不是链路坏了，是这题本来就不该执行。
        dead = [r.id for r in rows if not r.executed and r.expect_kind != "clarify"]
        if dead:
            problems.append(f"没有执行成功 {len(dead)} 题：{'、'.join(dead[:10])}"
                            + ("…" if len(dead) > 10 else ""))
    return info, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按档位校验评测/闸门报告")
    ap.add_argument("report", nargs="+", help="一份或多份报告")
    ap.add_argument("--expect-n", type=int, default=None, help="期望题数（不给就不查）")
    ap.add_argument("--require-all", action="store_true",
                    help="要求全部判对且全部执行成功（只用于 oracle）")
    ap.add_argument("--kind", default=A.KIND_EVAL, choices=[A.KIND_EVAL, A.KIND_GATE],
                    help="报告类型：eval（默认）或 gate")
    ap.add_argument("--label", default="", help="打印前缀，例如 pr-oracle")
    a = ap.parse_args(argv)

    tag = f"[{a.label}] " if a.label else ""
    bad = 0
    for path in a.report:
        try:
            info, problems = evaluate(path, a.expect_n, a.require_all, a.kind)
        except (A.ReportError, OSError, ValueError) as e:
            print(f"❌ {tag}{path}：读不了 —— {e}")
            bad += 1
            continue
        if problems:
            print(f"❌ {tag}{path}：{info['n']} 题，{len(problems)} 个问题")
            for p in problems:
                print(f"   - {p}")
            bad += 1
        else:
            extra = ""
            if a.require_all:
                # clarify 题的正确行为是不执行（反问），所以文案不能说"全部执行成功" ——
                # 那份报告的执行率必然 <100%，按字面读会以为有题挂了。
                n_clarify = sum(1 for r in A.iter_rows(path) if r.expect_kind == "clarify")
                extra = ("，全部判对" +
                         (f"（{n_clarify} 条 clarify 按预期未执行）" if n_clarify else "且全部执行成功"))
            print(f"✅ {tag}{path}：{info['n']} 题，结构无洞{extra}")
    if len(a.report) > 1:
        print(f"\n{len(a.report) - bad}/{len(a.report)} 份通过")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
