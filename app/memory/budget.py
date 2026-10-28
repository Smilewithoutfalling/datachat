"""记忆的 token 预算（M12，spec §3.6）。

只估不算账：estimate_tokens 与 app/core/llm.py 的 _est 同一比例（EST_CHARS_PER_TOKEN=2，宁可多算），
只用来判断"该不该裁"，不当账单。
"""
from __future__ import annotations

from app.core.llm import EST_CHARS_PER_TOKEN

STATE_TOKENS = 500          # 工作状态块（M1）
DICT_TOKENS = 2000          # 口径块（M2，批 1 未用，只参与 fixed）
HISTORY_TOKENS = 6000       # 历史块（M3/M5）
HISTORY_TOKENS_TIGHT = 4000 # 投影超阈值时的历史上限
SYSTEM_TOKENS = 1500
TOOL_TOKENS = 4000
DEFAULT_EXPECTED_CALLS = 6
PROJECTION_RATIO = 0.6

TRIM_WARNING = "上下文较长，已自动省略部分较早的对话。"


def estimate_tokens(text: str) -> int:
    n = len(text or "")
    return -(-n // EST_CHARS_PER_TOKEN)


def history_cap(budget: int, expected_calls: int | None, history_tokens: int) -> int:
    """历史块上限（spec §3.6 的投影闸门）。历史每次调用都要付一遍：
    projected = min(历史 token, 6000) × 预计调用次数（上一轮 usage.calls，没有则 6），
    超过 (预算 − 固定块) 的 60% 就收紧到 4000。budget 为 0（预算关闭）时不收紧。"""
    if not budget:
        return HISTORY_TOKENS
    fixed = SYSTEM_TOKENS + STATE_TOKENS + DICT_TOKENS + TOOL_TOKENS
    calls = expected_calls if expected_calls and expected_calls > 0 else DEFAULT_EXPECTED_CALLS
    projected = min(history_tokens, HISTORY_TOKENS) * calls
    return HISTORY_TOKENS_TIGHT if projected > PROJECTION_RATIO * (budget - fixed) else HISTORY_TOKENS
