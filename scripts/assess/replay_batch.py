"""目录级全量回放（7.5b B2，phase75b-eval-assess.md §B2 验收 ②）。

用法：
    python scripts/assess/replay_batch.py <快照目录> [--recorded] [--json]

对目录里每个快照 .jsonl 逐节点回放（app/assess/replay.py::replay_node，与单节点 CLI
scripts/assess/replay_node.py 同一实现）：

- 模型节点：重建 prompt 与快照里的 sha256 比对；--recorded 时用录下的原始响应，updates 也必须一致
  （CI 用这条：免 Key，验证的是**管线不变性** —— 同一份输入重建出逐字节相同的 prompt、同一段代码
  在同一份数据上算出相同结果；不验证答案质量）。
- executor：核对数据集指纹后重执行代码，按 results_equal 口径比结果。
- react 快照只有 run/end 两行，没有 node 行，跳过并计数。

退出码：全部一致 0；任何不一致（或目录里没有快照）1。--json 输出机器可读报告。
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
    ap.add_argument("directory", help="快照 .jsonl 所在目录")
    ap.add_argument("--recorded", action="store_true", help="用快照里录下的模型响应（免 Key，CI 用）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = ap.parse_args(argv)

    from app.assess.replay import replay_node
    from app.assess.snapshot import list_snapshots, load

    paths = list_snapshots(args.directory)
    if not paths:
        print(f"[replay_batch] 目录里没有快照：{args.directory}")
        return 1

    replays, no_nodes, failures = 0, 0, []
    for p in paths:
        snap = load(p)
        if not snap.nodes:
            no_nodes += 1        # react / 没进图的运行：回放不了也不算失败，计数报出来
            continue
        for row in snap.nodes:
            replays += 1
            r = replay_node(p, row["node"], row["occurrence"], recorded=args.recorded)
            if not r.ok:
                why = r.output_reason or ("prompt 不一致" if r.prompt_match is False else "")
                failures.append({"snapshot": os.path.basename(p), "node": r.node,
                                 "occurrence": r.occurrence, "why": why,
                                 "output_match": r.output_match, "prompt_match": r.prompt_match})

    ok = replays - len(failures)
    if args.json:
        print(json.dumps({"directory": args.directory, "recorded": args.recorded,
                          "snapshots": len(paths), "replays": replays, "ok": ok,
                          "failures": failures, "snapshots_without_nodes": no_nodes},
                         ensure_ascii=False, indent=2))
    else:
        mode = "recorded" if args.recorded else "live"
        print(f"[replay_batch] {mode}: 快照 {len(paths)} 个，节点回放 {replays} 次，"
              f"一致 {ok}，失败 {len(failures)}，无 node 行（react/未进图）{no_nodes} 个")
        for f in failures:
            print(f"  FAIL {f['snapshot']} {f['node']}#{f['occurrence']}: {f['why']}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
