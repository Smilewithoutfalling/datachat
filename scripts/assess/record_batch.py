"""fake_llm 全管线跑批（7.5b B2，phase75b-eval-assess.md §B2 验收 ③）。

用法：
    python scripts/assess/record_batch.py <快照目录> [--ids id1,id2] [--limit N]

进程内起 tests/fake_llm.py 的假模型服务（场景 ok：planner 出计划、codegen 出
`result = int(len(df))` —— 任何单表都能执行成功；多表题 df 不在沙箱，走 fix→fail→
attempts 用尽的失败链路，照样全节点落快照），用真 EvalRunner 把全部用例过一遍工作流，
节点快照写进 <快照目录>，run 行带 case_id。

这是 CI 的第一步：跑完接着 `replay_batch.py <快照目录> --recorded`（管线不变性）和
`assess.py <快照目录>`（契约报告能产出）。**不验证答案质量** —— ok 场景的答案不是对题
的，判分列只是让 run_all 不改路径。

- memory_mode 显式 off：state 档在评测里只跑一半（历史块有、状态块没有，见 runner.py 注释），
  off 档 prompt 与历史逐字节一致，回放验收才有「不变」可言；dataset_notes 留空、rewrite 关、
  run_suffix 不传，理由相同。
- 数据表不在本地的用例（EV-B6 扰动题指向 outputs/ 下的脏表）跳过并打印：CI 没跑过
  perturb 生成，跳过是预期，不是失败。

退出码：跑 ≥1 题 0；一题没跑（或 --ids 里有未知用例）1。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("directory", help="快照输出目录")
    ap.add_argument("--ids", help="只跑这些用例（逗号分隔，测试用）")
    ap.add_argument("--limit", type=int, help="只跑前 N 条用例（冒烟用）")
    args = ap.parse_args(argv)
    os.makedirs(args.directory, exist_ok=True)
    # Windows 控制台默认 GBK：run_all 的 ✅⚠️ 打到 GBK 流会直接 UnicodeEncodeError。CI 是 UTF-8 不受影响。
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  # pytest 捕获流没有 reconfigure，无所谓
        pass

    from tests.fake_llm import make_server
    from app.core.llm import LLMConfig
    from app.eval.cases import ALL_CASES, DATASETS
    from app.eval.runner import EvalRunner

    cases = list(ALL_CASES)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        cases = [c for c in cases if c.id in want]
        missing = want - {c.id for c in cases}
        if missing:
            print(f"[record_batch] 未知用例: {', '.join(sorted(missing))}")
            return 1
    if args.limit:
        cases = cases[: args.limit]

    # 数据表缺失的用例跳过（见模块 docstring）：先探清单，别让 path_for 半路抛 KeyError。
    # DATASETS 里是相对路径，相对的是仓库根 —— 不依赖调用方的 cwd。
    def _exists(p: str) -> bool:
        return os.path.exists(p) or (not os.path.isabs(p) and os.path.exists(os.path.join(ROOT, p)))

    skipped, runnable = [], []
    for c in cases:
        path = DATASETS.get(c.dataset, c.dataset)
        if not _exists(path):
            skipped.append(c.id)
            continue
        runnable.append(c)
    if skipped:
        print(f"[record_batch] 跳过（数据表不在本地）: {', '.join(skipped)}")
    if not runnable:
        print("[record_batch] 一题没跑")
        return 1

    srv = make_server()
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        runner = EvalRunner(agent="workflow", memory_mode="off",
                            llm_config=LLMConfig(api_key="fake", model="ok",
                                                base_url=f"http://127.0.0.1:{port}/v1"),
                            snapshot_dir=args.directory)
        print(f"[record_batch] fake_llm http://127.0.0.1:{port}/v1，跑 {len(runnable)} 题 → {args.directory}")
        runner.run_all(runnable, verbose=True)
    finally:
        srv.shutdown()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
