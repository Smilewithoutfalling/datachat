"""把后端的事件类型与图表禁用键导出成前端用的 JSON（阶段 5 F2），前端不手抄、改了后端 CI 就报。

    python scripts/gen_ui_types.py            # 写 ui/web/src/generated/{events,banned_keys}.json
    python scripts/gen_ui_types.py --check    # 只校验现有文件与重新生成的是否一致（CI 用）

来源：app/core/events.py 的 EVENT_TYPES、ERROR_KINDS 和常量文案；app/server/db.py 的 MESSAGE_STATUSES；app/tools/charts.py 的 BANNED_KEYS（前端渲染 ECharts 前再过一遍）。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "ui", "web", "src", "generated")


def build() -> dict[str, str]:
    from app.core.events import (CANCELLED_MESSAGE, DISCONNECTED_MESSAGE, ERROR_KINDS, EVENT_TYPES,
                                 INTERRUPTED_MESSAGE, STREAM_ABORTED_MESSAGE)
    from app.server.db import MESSAGE_STATUSES
    from app.tools.charts import BANNED_KEYS
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=2) + "\n"   # noqa: E731
    return {
        "events.json": dump({"_generated_by": "scripts/gen_ui_types.py", "event_types": list(EVENT_TYPES),
                             "error_kinds": list(ERROR_KINDS),
                             "message_statuses": list(MESSAGE_STATUSES),
                             "messages": {"cancelled": CANCELLED_MESSAGE, "interrupted": INTERRUPTED_MESSAGE,
                                          "disconnected": DISCONNECTED_MESSAGE,
                                          "stream_aborted": STREAM_ABORTED_MESSAGE}}),
        "banned_keys.json": dump({"_generated_by": "scripts/gen_ui_types.py", "banned_keys": sorted(BANNED_KEYS)}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    bad = []
    for name, text in build().items():
        path = os.path.join(OUT_DIR, name)
        if args.check:
            try:
                with open(path, encoding="utf-8", newline="") as f:
                    cur = f.read().replace("\r\n", "\n")
            except FileNotFoundError:
                cur = None
            if cur != text:
                bad.append(name)
        else:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    if bad:
        print("与后端不一致，运行 python scripts/gen_ui_types.py 重新生成：" + "、".join(bad))
        return 1
    print("ok" if args.check else f"已写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
