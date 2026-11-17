"""出境审计的历史版：给 analyze 喂一段**带数值的历史**，看 planner 的快照通道会不会漏值。

为什么单独一个脚本而不是改 `app/eval/egress.py`：`egress.audit()` 没有 history 入口，
而 C-022 之后 planner 会看到最近两轮的「问 + 答案摘要 + 结果形态」—— 那里面**有数**。
改 `egress.py` 会动 `code_sha12`（它在 A 组），所以审计的入口放在 scripts/ 里，
四条断言的实现仍然复用 `app.eval.egress`，不另写一套判据。

用法：
    python scripts/egress_audit_history.py data/eval/sales.csv
    python scripts/egress_audit_history.py data/eval/employees.csv --agent workflow --json out.json

判读：`--history` 里的数如果出现在 findings 的 detail 里，就是**设计内** —— 用户上一轮问到的
答案必须回灌给 planner，否则它解不了「那这个呢」。真正要红的是：结构段样例行超 3、单值超 40 字、
整列值出境、本机路径。脚本把这些分开打印。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.eval import egress  # noqa: E402

DEFAULT_CODE = "result = len(df)"


def _history(numbers):
    """构造两轮历史：第 1 轮给一个聚合结论，第 2 轮给一个带两位小数的比值。"""
    from app.memory.snapshots import TurnSnapshot

    return [
        TurnSnapshot(q="华东地区的销售记录有几条？", a_brief=f"共 {numbers['n']} 条",
                     result_digest=f"int = {numbers['n']}"),
        TurnSnapshot(q="这些记录的总销售额是多少元？", a_brief=f"合计 {numbers['amount']} 元",
                     result_digest=f"float = {numbers['amount']}"),
    ]


def audit_with_history(dataset, question, *, agent, history, code=DEFAULT_CODE,
                       use_dictionary=True, forbidden=(), max_attempts=3):
    from app.core.service import analyze
    from app.core.testing import oracle_model, prompt_text
    from app.tools.dataset import load_data

    model = oracle_model(code, agent)
    res = analyze(dataset, question, agent=agent, chat_model=model,
                  use_dictionary=use_dictionary, max_attempts=max_attempts,
                  history=history, memory_mode="state")
    prompts = [egress.Prompt(i, prompt_text(msgs)) for i, msgs in enumerate(model.calls)]
    out = egress.Audit(agent=agent, prompts=prompts, executed=bool(res.executed), error=res.error)
    text = out.text()
    data, _desc = load_data(dataset)
    out.findings += [egress.Finding("sample_rows", p) for p in egress.check_sample_rows(data, text)]
    out.findings += [egress.Finding("cell_chars", p) for p in egress.check_cell_chars(data, text)]
    out.findings += [egress.Finding("column_values", p)
                     for p in egress.check_column_values(data, text, out.notes)]
    out.findings += [egress.Finding("local_path", p)
                     for p in egress.check_local_path(text, egress.own_paths(dataset))]
    return out, res


def main(argv=None):
    ap = argparse.ArgumentParser(description="带历史的出境审计（C-022 planner 快照通道）")
    ap.add_argument("dataset")
    ap.add_argument("-q", "--question", default="这些记录里销量最高的是哪个产品？")
    ap.add_argument("--agent", default="workflow", choices=["workflow", "react", "both"])
    ap.add_argument("--n", default="7", help="第 1 轮答案里的整数（会进快照）")
    ap.add_argument("--amount", default="486213.55", help="第 2 轮答案里的金额（会进快照）")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    numbers = {"n": args.n, "amount": args.amount}
    history = _history(numbers)
    agents = ["workflow", "react"] if args.agent == "both" else [args.agent]
    payload, bad = [], 0
    for agent in agents:
        out, res = audit_with_history(args.dataset, args.question, agent=agent, history=history)
        print(f"\nagent={agent}  {len(out.prompts)} 次模型调用，合计 {len(out.text())} 字符"
              f"  executed={res.executed} memory_mode={getattr(res, 'memory_mode', '?')}")
        # 快照真的进了 prompt 吗 —— 没进去的话"没扫到值"是假绿
        snap_in = f"答：共 {numbers['n']} 条" in out.text()
        print(f"  快照出现在 prompt 里：{snap_in}"
              f"{'' if snap_in else '  ← 注意：这种情况下空的 findings 不算通过'}")
        if not snap_in:
            bad = 2
        for f in out.findings:
            hit = any(v in f.detail for v in numbers.values())
            print(f"  [{f.rule}] {'历史答案里的数（设计内）' if hit else '需要人看'}：{f.detail[:160]}")
        if out.findings:
            bad = max(bad, 1)
        payload.append({
            "agent": agent, "calls": len(out.prompts),
            "snapshot_in_prompt": snap_in,
            "history_numbers": numbers,
            "findings": [{"rule": f.rule, "detail": f.detail,
                          "from_history": any(v in f.detail for v in numbers.values())}
                         for f in out.findings],
            "notes": out.notes,
            "executed": res.executed, "error": res.error,
        })

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"dataset": args.dataset, "question": args.question,
                       "agents": payload}, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON 写到 {args.json_out}")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
