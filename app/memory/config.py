"""记忆开关（spec §3.7）。

取值顺序：环境变量 DATACHAT_MEMORY（测试 / 评测 / 消融用）→ settings 表的 memory_mode（产品设置页）→ "off"。
每次调用时读，不在 import 时读成常量（pytest 的 monkeypatch.setenv 之后要立刻生效）。

返回的是**实际生效的值**：批 1 只实现了 state 一档，所以 "full" 解析为 "state"（full 的其余几张卡还没做，
报成 full 会让消融表把 state 的结果记到 full 名下）。评测的指纹（app/eval/fingerprint.py）直接调
resolve_memory_mode()；评测进程里没有 settings 表，结果与 analyze() 自己解析出来的一致。
"""
from __future__ import annotations

import logging
import os

MODES = ("off", "state")                 # 批 1 实际实现的档位
_ALIASES = {"full": "state"}             # 规格里的 full 在批 3 之前等同 state
ENV = "DATACHAT_MEMORY"
SETTING_KEY = "memory_mode"

logger = logging.getLogger("datachat.memory")


def normalize(value) -> str | None:
    """规范化一个候选值；不认识的返回 None（落到下一个来源）。"""
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    v = _ALIASES.get(v, v)
    return v if v in MODES else None


def env_override() -> str | None:
    """环境变量覆盖（规范化后）；没设或不认识时为 None。"""
    raw = os.getenv(ENV)
    v = normalize(raw)
    if raw not in (None, "") and v is None:
        logger.warning("忽略不认识的 %s=%r（可选 off / state）", ENV, raw)
    return v


def resolve_memory_mode(settings_value: str | None = None) -> str:
    """本轮实际生效的记忆模式：env → settings → off。"""
    return env_override() or normalize(settings_value) or "off"
