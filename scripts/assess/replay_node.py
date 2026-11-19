"""单节点回放（阶段 7.5 第 1 步，docs/roadmap/phase75-assess.md §2 第 1 步验收 ①②）。

用法：
    python scripts/assess/replay_node.py <快照.jsonl> <节点> [--occurrence N] [--recorded] [--json]

节点：planner / codegen / executor / reviewer / summarizer。--occurrence 选第几次出现（reviewer 之后
executor 会跑第二次），默认 1。

- 模型节点：重建 prompt，与快照里原 prompt 的 sha256 比对（必须逐字节一致）。默认现调模型（读环境变量里的
  Key）；--recorded 用快照里录下的原始响应，这时 updates 也必须与原运行一致。
- executor：先核对数据集指纹，再执行同一段代码，按 app/assess/replay.py::results_equal 的口径比结果。
- today 一律取快照里的值，不读当天日期。

退出码：一致 0，不一致 1（这是回放验收，不是评估差分）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot")
    ap.add_argument("node", choices=["planner", "codegen", "executor", "reviewer", "summarizer"])
    ap.add_argument("--occurrence", type=int, default=1)
    ap.add_argument("--recorded", action="store_true", help="用快照里录下的模型响应，不调模型")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = ap.parse_args(argv)

    from app.assess.replay import replay_node
    r = replay_node(args.snapshot, args.node, args.occurrence, recorded=args.recorded)
    out = {"node": r.node, "occurrence": r.occurrence, "today": r.today, "mode": r.mode, "ok": r.ok,
           "prompt_match": r.prompt_match, "prompt_sha256": r.prompt_sha256,
           "recorded_prompt_sha256": r.recorded_prompt_sha256,
           "output_match": r.output_match, "output_reason": r.output_reason}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for k, v in out.items():
            print(f"{k}: {v}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
