"""服务商预设（阶段 6.5 §2b）：app/core/providers.json 只放数据，这里负责读和合并怪癖。

三层：协议（4 种，app/core/llm.py build_chat_model 分发）→ 服务商（预设数据）→ 连接（用户命名、存在 connections 表）。
预设的 schema 由 tests/test_providers.py 校验（字段齐全、协议合法、URL 是 https，本地服务商可以是 http://localhost）。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Optional

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.json")
# 怪癖开关（§2c）：三个布尔 + thinking_param（None 不发 / "enable_thinking"（Qwen 一类）/ "thinking"（GLM、方舟一类））
BOOL_QUIRKS = ("no_stream_options", "no_array_content", "reasoning_replay")
THINKING_PARAMS = ("enable_thinking", "thinking")
QUIRK_KEYS = BOOL_QUIRKS + ("thinking_param",)
CUSTOM = "custom"
DEEPSEEK = "deepseek"


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def catalog() -> dict:
    """GET /providers 的内容：协议表、自定义可选的协议、分组、服务商列表（去掉 _comment）。"""
    d = _load()
    return {k: v for k, v in d.items() if not k.startswith("_")}


def providers() -> list[dict]:
    return list(_load()["providers"])


def protocols() -> tuple[str, ...]:
    return tuple(_load()["protocols"])


def custom_protocols() -> tuple[str, ...]:
    return tuple(_load()["custom_protocols"])


def get(provider_id: str) -> Optional[dict]:
    for p in _load()["providers"]:
        if p["id"] == provider_id:
            return p
    return None


def effective_quirks(provider_id: str, override: Optional[dict] = None) -> dict[str, Any]:
    """预设怪癖 + 连接上的覆盖（覆盖里写了的键才算数，写 false / null 就是显式关掉）。未知键丢弃。"""
    p = get(provider_id) or {}
    out: dict[str, Any] = {k: False for k in BOOL_QUIRKS}
    out["thinking_param"] = None
    for src in (p.get("quirks") or {}, override or {}):
        for k, v in src.items():
            if k in BOOL_QUIRKS:
                out[k] = bool(v)
            elif k == "thinking_param":
                out[k] = v if v in THINKING_PARAMS else None
    return out
