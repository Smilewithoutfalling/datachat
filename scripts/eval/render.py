"""把一份评测报告渲染成五段式 Markdown（规格 §EV-D1）。

用法：
    python scripts/eval/render.py docs/eval/gate_xxx.json
    python scripts/eval/render.py docs/eval/gate_xxx.json --md /tmp/r.md

只读 JSON，不重跑 gold、不调模型、不 import 被测系统。

**刻意不接受两份报告。** 比两份报告是 `compare.py` 的事，两个入口各管一件事；
把比较塞进来会让这个脚本同时承担"渲染"和"配对"两种失败模式，出错时分不清
是渲染坏了还是配对坏了。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval import report_adapter as adapter  # noqa: E402
from app.eval.report_md import render  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把评测报告渲染成五段式 Markdown")
    ap.add_argument("report", help="报告 JSON 路径")
    ap.add_argument("--md", metavar="OUT", help="写进这个文件；不给就打到 stdout")
    args = ap.parse_args(argv)

    try:
        text = render(args.report)
    except adapter.ReportError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {args.md}（{len(text.splitlines())} 行）")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
