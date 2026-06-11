"""结果持久化：图表唯一命名 + 运行记录落盘。

每次执行生成唯一图表文件名（时间戳 + 短 uuid），避免覆盖历史图；
每次运行追加一行 JSON 到 runs.jsonl，便于回看问过什么、生成了什么。
"""
import json
import os
import time
import uuid
from datetime import datetime

from app.config import CHART_DIR, RUNS_LOG, ensure_dirs


def new_chart_path() -> str:
    """返回 CHART_DIR 下一个唯一的图表文件路径（不创建文件）。"""
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"chart_{stamp}_{uuid.uuid4().hex[:6]}.png"
    return os.path.join(CHART_DIR, name)


def log_run(record: dict) -> None:
    """把一次运行的记录追加到 runs.jsonl（每行一个 JSON）。"""
    ensure_dirs()
    record = {"ts": time.time(), **record}
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
