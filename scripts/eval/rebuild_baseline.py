"""全量重建基线：按分片顺序跑，独立落盘、可断点续跑。

为什么需要它：`eval-v5` 之后有两处变了，`GATE_KEYS` 里的两个字段都不再命中台账 ——
题集 183 → 202（`evalset_sha12` 4270d57adf72 → 5748a13bdefc），
`schema.py` 被 [154][156] 改过两次（`code_sha12` 也变了）。
**这两处任何一处变，旧读数就不能和新读数直接比**，所以不是"恢复 v5"，是重立一把尺子。

四个分片，口径与 `eval-v5` 的 `n=[150,33]` 逐条对应：

| 分片 | 题数 | 与 v5 的关系 |
|---|---|---|
| `single_off` | 161 | v5 是 150，多出的 11 道是 v5 之后新增的题 |
| `mul_off` | 34 | v5 是 33，多出的 1 道同上 |
| `mul_state` | 34 | 同上 |
| `mem_state` | 7 | **v5 没有这一类**（`requires_memory`），新增 |

每片 `--repeat 3`：单点读数分不清"模型退步"和"这一次运气差"，`pass^3` 才给得出区间。
`--no-fail`：判错不进退出码。跑批脚本关心的是"跑得完"，准确率由报告说话；
真崩溃（连接失败、Key 失效）仍走异常路径退出非零。

用法：
    python scripts/eval/rebuild_baseline.py --dry-run
    python scripts/eval/rebuild_baseline.py
    python scripts/eval/rebuild_baseline.py --only mul_state
    python scripts/eval/rebuild_baseline.py --force          # 忽略已有报告，重跑
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_DIR = os.path.join(REPO, "docs", "eval", "runs")

# (分片名, 期望题数, run_eval.py 的参数)
SHARDS: list[tuple[str, int, list[str]]] = [
    ("single_off", 161, ["-c", "agg,filt,corr,ts,refusal,ambiguity", "--memory", "off"]),
    ("mul_off", 34, ["-c", "mul", "--memory", "off"]),
    ("mul_state", 34, ["-c", "mul", "--memory", "state"]),
    ("mem_state", 7, ["-c", "memory", "--memory", "state"]),
]

REPEAT = 3


def out_base(shard: str) -> str:
    return os.path.join(RUNS_DIR, f"eval_v6_{shard}.json")


def run_files(shard: str) -> list[str]:
    base = out_base(shard)[:-5]
    return [f"{base}_run{k}.json" for k in range(1, REPEAT + 1)]


def shard_done(shard: str, expect: int) -> tuple[bool, str]:
    """三份报告都在、题数都对上，才算这一片跑完了。

    只看文件存在不够：连接失败时 `run_eval.py` 仍会写出报告（n 对但 execution 全红，
    或干脆 n=0）。那种报告进了台账比没有更坏，所以这里连 `n` 一起核。
    """
    for path in run_files(shard):
        if not os.path.exists(path):
            return False, f"缺 {os.path.basename(path)}"
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            return False, f"{os.path.basename(path)} 读不了：{type(e).__name__}"
        n = d.get("n") or len(d.get("per_case") or {})
        if n != expect:
            return False, f"{os.path.basename(path)} 题数 {n} ≠ {expect}"
        rate = d.get("execution_success_rate")
        if isinstance(rate, (int, float)) and rate <= 0:
            return False, f"{os.path.basename(path)} 执行成功率 {rate}（整批没跑通）"
    return True, "已完成"


def command(shard: str, extra: list[str]) -> list[str]:
    return [sys.executable, os.path.join(REPO, "run_eval.py"),
            "--agent", "react", "--repeat", str(REPEAT),
            "--out", out_base(shard), "--no-fail", *extra]


def summarize(shard: str) -> str:
    rows = []
    for path in run_files(shard):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            rows.append("—")
            continue
        rows.append(f"{d.get('correct')}/{d.get('n')}"
                    f" ({100 * (d.get('correctness_rate') or 0):.1f}%)")
    return "  ".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="eval-v6 全量重建（四片 × 3 跑）")
    ap.add_argument("--only", default=None, help="只跑某一片，如 single_off")
    ap.add_argument("--force", action="store_true", help="忽略已有报告，重跑")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令与题次，不执行")
    ap.add_argument("--retries", type=int, default=2, help="单片失败重试次数（默认 2）")
    args = ap.parse_args()

    picked = [s for s in SHARDS if args.only is None or s[0] == args.only]
    if not picked:
        print(f"未知分片：{args.only}，可选 {' / '.join(s[0] for s in SHARDS)}")
        return 2

    total = sum(n for _, n, _ in picked) * REPEAT
    print(f"分片 {len(picked)} 个，合计 {total} 题次（每片 {REPEAT} 跑）")
    for name, expect, extra in picked:
        done, why = shard_done(name, expect) if not args.force else (False, "force")
        mark = "跳过" if done else "待跑"
        print(f"  [{mark}] {name:11s} {expect:3d} 题  {why}")
        if args.dry_run or not done:
            print("         " + " ".join(command(name, extra)))
    if args.dry_run:
        return 0

    t_all = time.time()
    failed = []
    for name, expect, extra in picked:
        done, why = shard_done(name, expect) if not args.force else (False, "force")
        if done:
            print(f"\n=== {name}：已有完整报告，跳过（--force 可重跑）")
            continue
        for attempt in range(1, args.retries + 2):
            print(f"\n=== {name}：第 {attempt} 次（{expect} 题 × {REPEAT}）===", flush=True)
            t0 = time.time()
            r = subprocess.run(command(name, extra), cwd=REPO)
            print(f"--- {name} 退出码 {r.returncode}，耗时 {(time.time() - t0) / 60:.1f} 分钟")
            ok, why = shard_done(name, expect)
            if ok:
                print(f"--- {name} 结果：{summarize(name)}")
                break
            print(f"--- {name} 未通过：{why}")
        else:
            failed.append((name, why))

    print(f"\n===== 汇总（总耗时 {(time.time() - t_all) / 60:.1f} 分钟）=====")
    for name, expect, _ in picked:
        ok, why = shard_done(name, expect)
        print(f"  {'✓' if ok else '✗'} {name:11s} {why if not ok else summarize(name)}")
    if failed:
        print(f"\n失败分片：{'、'.join(n for n, _ in failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
