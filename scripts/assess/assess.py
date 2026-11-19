"""评估命令（阶段 7.5 第 1 步，docs/roadmap/phase75-assess.md §0、§2 第 1 步）。

用法：
    python scripts/assess/assess.py <快照目录> [--json OUT] [--md OUT]
    python scripts/assess/assess.py --diff <before_dir> <after_dir> [--json OUT] [--md OUT]

功能一：对目录里每个快照（DATACHAT_SNAPSHOT_DIR 写出的 *.jsonl）跑全部节点契约，输出 JSON 与 markdown。
功能二：--diff 逐题、逐环列出两份快照集之间四态（ok / warn / fail / not_checked）的任意变化与环的出现 / 消失；
一边整题缺快照的报 snapshot_missing（写明缺 before 还是 after）。只列不判。

两种模式退出码都恒为 0：评估回答的是「哪一环变了」，不是「过没过」（§0）；它的数字不是准确率，不进对外报告。
markdown 默认打到标准输出；--json / --md 给了路径就写文件。
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
    ap.add_argument("directory", nargs="?", help="快照目录")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"), help="差分两份快照目录")
    ap.add_argument("--json", help="JSON 输出路径")
    ap.add_argument("--md", help="markdown 输出路径（默认打印到标准输出）")
    args = ap.parse_args(argv)

    from app.assess import runner
    if args.diff:
        data = runner.diff(runner.assess_dir(args.diff[0]), runner.assess_dir(args.diff[1]))
        md = runner.diff_markdown(data)
    elif args.directory:
        data = runner.assess_dir(args.directory)
        md = runner.report_markdown(data)
    else:
        ap.print_usage(sys.stderr)
        print("需要一个快照目录，或 --diff BEFORE AFTER", file=sys.stderr)
        return 0
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
