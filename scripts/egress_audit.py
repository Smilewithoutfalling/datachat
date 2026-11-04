"""人工排查用的出境审计：把一次分析真正发给模型的每段 prompt 抓出来，逐条查四条断言。

不联网、不花 token：模型是脚本化的假模型（`app.core.testing.oracle_model`），
`code` 参数决定它"写"什么代码。**默认代码只回 `len(df)`**，这样 summarizer 那一步
不会把结果表回灌进来 —— 审的是"结构描述这条通道"。

想看结果回灌通道有多少内容出境，传一条会返回大表的 code（例如 `result = df`），
看 `column_values` 这条会不会红 —— 那不是误报，是设计取舍：用户要"列出全部订单"时，
结果必须回灌给 summarizer。审计的职责是把它量出来，不是替产品决定。

用法：
    python scripts/egress_audit.py data/sample.csv -q "哪个地区销量最高？"
    python scripts/egress_audit.py data/sample.csv -q "画图看各地区销量" \
        --code "g = df.groupby('region')['units'].sum(); plt.bar(g.index, g.values); plt.title('销量'); plt.savefig(chart_path); result = float(g.max())"
    python scripts/egress_audit.py data/sample.csv -q "..." --agent both --json outputs/egress.json

退出码：0 = 四条断言全过；1 = 有发现；2 = 跑不起来（数据集读不了 / 代码执行失败）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.eval import egress  # noqa: E402

_RULE_NAMES = {
    "sample_rows": "① 样例行 ≤ 3",
    "cell_chars": "② 单值 ≤ 40 字",
    "column_values": "③ 不含全量列值",
    "local_path": "④ 不含本机路径",
}


def _print_one(a: egress.Audit, verbose: bool) -> None:
    print(f"agent={a.agent}  {len(a.prompts)} 次模型调用，"
          f"合计 {sum(len(p.text) for p in a.prompts)} 字")
    if a.error:
        print(f"  ⚠ 分析没跑通：{str(a.error).splitlines()[0][:120]}")
        print("    （契约 ① ② 仍可判；③ 的分母不完整，④ 只覆盖已发出的 prompt）")
    if verbose:
        for p in a.prompts:
            print(f"    call {p.call}: {len(p.text)} 字")
    if a.ok:
        print("  ✓ 四条断言全过")
        return
    for f in a.findings:
        print(f"  ✗ {_RULE_NAMES.get(f.rule, f.rule)}  {f.detail}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="出境审计：审模型实际收到的 prompt")
    ap.add_argument("dataset", help="CSV 路径，或目录 / 多个 CSV（多表）")
    ap.add_argument("-q", "--question", required=True, help="用户问题")
    ap.add_argument("--agent", default="workflow", choices=["workflow", "react", "both"])
    ap.add_argument("--code", default=None,
                    help=f"假模型写出的代码（默认 {egress.DEFAULT_CODE!r}）")
    ap.add_argument("--no-dict", action="store_true", help="不挂数据字典（默认挂，因为字典也是出境通道）")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--forbidden", action="append", default=[],
                    help="额外禁止出现的字符串（可重复）")
    ap.add_argument("--json", dest="json_out", default=None, help="把结果写成 JSON")
    ap.add_argument("-v", "--verbose", action="store_true", help="逐个模型调用打印长度")
    args = ap.parse_args(argv)

    agents = ["workflow", "react"] if args.agent == "both" else [args.agent]
    audits, code = [], 0
    print(f"数据集 {args.dataset}")
    print(f"问题   {args.question}")
    for agent in agents:
        a = egress.audit(args.dataset, args.question, agent=agent, code=args.code,
                         use_dictionary=not args.no_dict, forbidden=tuple(args.forbidden),
                         max_attempts=args.max_attempts)
        audits.append(a)
        _print_one(a, args.verbose)
        code = max(code, 0 if a.ok else 1)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({
                "dataset": args.dataset,
                "question": args.question,
                "max_cell_chars": egress.EGRESS_MAX_CELL_CHARS,
                "agents": [{
                    "agent": a.agent,
                    "calls": len(a.prompts),
                    "chars": sum(len(p.text) for p in a.prompts),
                    "ok": a.ok,
                    "executed": a.executed,
                    "error": a.error,
                    "findings": [{"rule": f.rule, "detail": f.detail} for f in a.findings],
                } for a in audits],
            }, fh, ensure_ascii=False, indent=2)
        print(f"JSON 写到 {args.json_out}")

    if any(a.error and not a.prompts for a in audits):
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
