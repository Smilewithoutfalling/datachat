"""保留与删除（阶段 6.6 M0，memory-system-spec.md M0）。

- 删会话 / 数据集 / 单条消息时，连带删掉它们产出的图表 PNG（图表文件名不带归属，归属从 result_json 与事件里找）。
- SQLite 回收空间：新库建表前设 auto_vacuum=INCREMENTAL；旧库（auto_vacuum=NONE）只在启动、开始监听之前、
  空闲页占比超过阈值时转换一次（这时没有并发写；不放退出路径：壳的退出宽限只有 3 s）；退出时只跑有上限的
  incremental_vacuum。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger("datachat.retention")

_CHART_NAME = re.compile(r"^chart_[A-Za-z0-9_\-]+\.png$")

VACUUM_FREELIST_RATIO = 0.25          # 旧库转换的触发条件：空闲页 / 总页数
VACUUM_MAX_BYTES = 512 * 1024 * 1024  # 超过这个大小的旧库不在启动时转换（START_TIMEOUT 20 s，见 DEVLOG 实测）
SHUTDOWN_VACUUM_PAGES = 2000          # 退出时一次最多回收的页数（默认页 4 KB ≈ 8 MB）


def _pngs(obj) -> list:
    out = []
    if isinstance(obj, str):
        if obj.lower().endswith(".png"):
            out.append(obj)
    elif isinstance(obj, dict):
        for k in ("png", "chart", "chart_path"):
            v = obj.get(k)
            if isinstance(v, str):
                out += _pngs(v)
        for c in obj.get("charts") or []:
            out += _pngs(c)
    return out


def chart_files_of(result_json: str | None, chart_dir: str, event_data: list | None = None) -> list:
    """result_json（charts[].png、chart_path）与事件 data（exec 事件的 chart）里引用的 PNG → chart_dir 下的绝对路径。
    只认图表命名（chart_*.png）的文件名，按文件名落到 chart_dir：路径里带 ../ 或指向别处的一律丢掉不删。"""
    found = []
    try:
        if result_json:
            found += _pngs(json.loads(result_json))
    except (ValueError, TypeError):
        pass
    for d in event_data or []:
        try:
            found += _pngs(json.loads(d) if isinstance(d, str) else d)
        except (ValueError, TypeError):
            pass
    base = os.path.abspath(chart_dir)
    out = []
    for p in found:
        norm = p.replace("\\", "/")
        name = norm.rsplit("/", 1)[-1]
        if not _CHART_NAME.match(name):
            continue
        if os.path.isabs(p) and os.path.dirname(os.path.abspath(p)) != base:
            continue                              # 绝对路径但不在图表目录：不是我们的文件
        if not os.path.isabs(p) and "/" in norm and not norm.startswith("/charts/"):
            continue                              # 相对路径带目录（../../x）：拒绝
        full = os.path.join(base, name)
        if full not in out:
            out.append(full)
    return out


def message_chart_files(messages, chart_dir: str) -> list:
    out = []
    for m in messages:
        if m.role != "assistant":
            continue
        for p in chart_files_of(m.result_json, chart_dir, [e.data_json for e in m.events]):
            if p not in out:
                out.append(p)
    return out


def remove_files(paths) -> int:
    n = 0
    for p in paths:
        try:
            os.remove(p)
            n += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("删除图表失败 %s: %s", p, e)
    return n


# ------------------------------------------------------------------ SQLite 空间回收
def prepare_auto_vacuum(dbapi_conn, db_path: str) -> str:
    """建表之前调用（make_sessionmaker）。新库在连接时已设好（db._pragmas），这里只处理旧库。
    返回 already / converted / skipped_ratio / skipped_size。"""
    cur = dbapi_conn.cursor()
    try:
        mode = cur.execute("PRAGMA auto_vacuum").fetchone()[0]
        if mode == 2:
            return "already"
        pages = cur.execute("PRAGMA page_count").fetchone()[0] or 0
        free = cur.execute("PRAGMA freelist_count").fetchone()[0] or 0
        size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        if not pages or free / pages <= VACUUM_FREELIST_RATIO:
            return "skipped_ratio"
        if size > VACUUM_MAX_BYTES:
            logger.warning("数据库 %.0f MB 超过启动时整理的上限，跳过（空闲页 %d/%d）", size / 2 ** 20, free, pages)
            return "skipped_size"
        t0 = time.perf_counter()
        cur.execute("PRAGMA auto_vacuum=INCREMENTAL")
        cur.execute("VACUUM")
        logger.info("旧库转换为 auto_vacuum=INCREMENTAL：%.0f KB，空闲页 %d/%d，耗时 %.2f s",
                    size / 1024, free, pages, time.perf_counter() - t0)
        return "converted"
    finally:
        cur.close()


def incremental_vacuum(engine, pages: int = SHUTDOWN_VACUUM_PAGES) -> int:
    """退出前回收最多 pages 页；auto_vacuum 不是 INCREMENTAL 时什么也不做。返回回收前的空闲页数。出错只记日志。"""
    try:
        with engine.connect() as c:
            raw = c.connection.driver_connection
            cur = raw.cursor()
            if cur.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
                return 0
            free = cur.execute("PRAGMA freelist_count").fetchone()[0]
            if free:
                cur.execute(f"PRAGMA incremental_vacuum({int(pages)})").fetchall()
            cur.close()
            return free
    except Exception as e:  # noqa: BLE001
        logger.warning("退出前回收空间失败：%s", e)
        return 0
