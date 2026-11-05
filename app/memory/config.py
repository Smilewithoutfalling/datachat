"""记忆开关（spec §3.7）。

取值顺序：环境变量 DATACHAT_MEMORY（测试 / 评测 / 消融用）→ settings 表的 memory_mode（产品设置页）→ "off"。
每次调用时读，不在 import 时读成常量（pytest 的 monkeypatch.setenv 之后要立刻生效）。

返回的是**实际生效的值**。批 4a 起三档都是真的（docs/roadmap/memory-batch4.md §2）：
- off：什么都不变（P8）；
- state：批 1–3 的全部（以后加口径 M2、M6 warning）；没有口径、没开改写时 system 与 f39753c 逐字节一致；
- full：state + M4 遮罩（以后加 M9 参考写法），会改变模型看到的历史。
评测的指纹（app/eval/fingerprint.py）直接调 resolve_memory_mode()；评测进程里没有 settings 表，
结果与 analyze() 自己解析出来的一致。

改写（M7 / M8）是独立开关：resolve_rewrite()，env DATACHAT_REWRITE（1/0）→ settings memory_rewrite → False，
只在 memory_mode != off 时生效（判断在 service.py）。
"""
from __future__ import annotations

import logging
import os

MODES = ("off", "state", "full")         # 批 4a：full 不再是 state 的别名
ENV = "DATACHAT_MEMORY"
SETTING_KEY = "memory_mode"
REWRITE_ENV = "DATACHAT_REWRITE"
REWRITE_SETTING_KEY = "memory_rewrite"

_TRUE = {"1", "true", "on", "yes"}
_FALSE = {"0", "false", "off", "no"}

logger = logging.getLogger("datachat.memory")


def normalize(value) -> str | None:
    """规范化一个候选值；不认识的返回 None（落到下一个来源）。"""
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    return v if v in MODES else None


def env_override() -> str | None:
    """环境变量覆盖（规范化后）；没设或不认识时为 None。"""
    raw = os.getenv(ENV)
    v = normalize(raw)
    if raw not in (None, "") and v is None:
        logger.warning("忽略不认识的 %s=%r（可选 off / state / full）", ENV, raw)
    return v


def resolve_memory_mode(settings_value: str | None = None) -> str:
    """本轮实际生效的记忆模式：env → settings → off。"""
    return env_override() or normalize(settings_value) or "off"


def normalize_flag(value) -> bool | None:
    """开关值规范化：bool 原样；'1/true/on/yes' → True，'0/false/off/no' → False；其余（含 None、空串）→ None。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def rewrite_env_override() -> bool | None:
    raw = os.getenv(REWRITE_ENV)
    v = normalize_flag(raw)
    if raw not in (None, "") and v is None:
        logger.warning("忽略不认识的 %s=%r（可选 1 / 0）", REWRITE_ENV, raw)
    return v


def resolve_rewrite(setting=None) -> bool:
    """改写开关（M7）：env DATACHAT_REWRITE → settings memory_rewrite → False。每次调用时读。
    只表示开关本身；是否真的改写还要 memory_mode != off、有 Key、本轮之前有轮次（service._maybe_rewrite）。"""
    v = rewrite_env_override()
    if v is not None:
        return v
    v = normalize_flag(setting)
    return bool(v) if v is not None else False
