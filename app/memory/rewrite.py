"""M7 指代 / 时间改写（docs/roadmap/memory-batch4.md §3.1；规格 M7）。

一次独立的便宜调用，把「刚才那个」「上个月」改写成不依赖上下文的完整问题。由 service._run 调用
（不放 app.py：评测的多轮 runner 直接调 analyze()，放在 API 层评测测不到）。

- 只在 memory_mode != off、改写开关开着、有 Key（或注入了假模型）、本轮之前有轮次时调用；
- 独立的 LLMClient，自带 UsageTracker：**不算进本轮 usage**，成本单独记在 result_json.rewrite；
- temperature=0、超时 min(cfg.timeout, 5)、max_tokens=200、SDK 与 LLMClient 都不重试；
- 「最近对话」「当前问题」都包 data_block（防止用户在问题里写「忽略上面的规则」）；
- 任何意外都回落原问题，不报错：超时 / 网关错误 / JSON 解析失败 / 空串 / 超过 4000 字 /
  needs_clarify=true / 数字守卫不通过；
- 数字守卫：改写结果里的每个数字都必须出现在「原问题 + 最近 3 轮 + 由 today 推出的年月日」里，
  否则视为「补了用户没说的条件」，回落。确定性检查，不再调模型。
"""
from __future__ import annotations

import calendar
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date

from app.memory.snapshots import TurnSnapshot, _local_ts, status_line

RECENT_TURNS = 3
MAX_CHARS = 4000
MAX_TOKENS = 200
TIMEOUT_S = 5.0

logger = logging.getLogger("datachat.memory")

PROMPT = """你是问题改写器。把"当前问题"改写成不依赖上下文、可以单独交给分析师的问题。
规则：
1. 不改变用户意图；不补充用户没说的过滤条件。
2. 只有在能确定指代时才替换；不能确定时 needs_clarify=true，rewritten 保留原问题。
3. 不回答问题，只改写。
今天：{today}
最近对话：
{recent}
当前问题：
{question}
只输出 JSON：{{"rewritten": "...", "needs_clarify": false, "reason": ""}}"""

_NUM = re.compile(r"\d+(?:\.\d+)?")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class RewriteResult:
    rewritten: str
    changed: bool
    needs_clarify: bool
    reason: str


def recent_text(snaps: list[TurnSnapshot], tz=None) -> str:
    """最近 3 轮的 问 / 答摘要（时间转本地时区，编号与历史块一致）；失败轮只给问 + 状态。"""
    snaps = list(snaps or [])
    start = max(0, len(snaps) - RECENT_TURNS)
    lines = []
    for n, s in enumerate(snaps[start:], start + 1):
        lines.append(f"[第{n}轮 · {_local_ts(s.ts, tz)}]")
        lines.append(f"问：{s.q}")
        lines.append(f"答：{s.a_brief}" if s.status == "ok" else status_line(s))
    return "\n".join(lines)


def build_prompt(question: str, snaps: list[TurnSnapshot], today: date, tz=None) -> str:
    from app.tools.schema import data_block
    return PROMPT.format(today=today.isoformat(), recent=data_block(recent_text(snaps, tz)),
                         question=data_block(question))


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    s = s.lstrip("0") or "0"
    return s


def numbers(text: str) -> set[str]:
    return {_norm_num(m.group(0)) for m in _NUM.finditer((text or "").replace(",", ""))}


def date_numbers(today: date) -> set[str]:
    """由 today 推出来的数字：今年 / 去年、本月 / 上个月（及其年份）、今天、1 号、本月与上月的天数。"""
    y, m = today.year, today.month
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    vals = {y, y - 1, py, m, pm, today.day, 1,
            calendar.monthrange(y, m)[1], calendar.monthrange(py, pm)[1]}
    return {str(v) for v in vals}


def guard_ok(rewritten: str, question: str, snaps: list[TurnSnapshot], today: date) -> tuple[bool, list[str]]:
    """数字守卫：改写里新出现的数字必须有出处。返回 (是否通过, 没有出处的数字)。"""
    allowed = numbers(question) | date_numbers(today)          # 不收最近对话里的时间戳：那是程序写的，不是用户说的
    for s in list(snaps or [])[-RECENT_TURNS:]:
        allowed |= numbers(s.q) | numbers(s.a_brief)
    bad = sorted(numbers(rewritten) - allowed)
    return not bad, bad


def parse(text: str) -> dict | None:
    t = _FENCE.sub("", (text or "").strip())
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(t[i:j + 1])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def rewrite(question: str, snaps: list[TurnSnapshot], today: date, client) -> tuple[RewriteResult, int, int]:
    """返回 (结果, tokens, ms)。client 是独立的 LLMClient（自带 tracker，不进本轮 usage）。
    回落时 rewritten=原问题、changed=False；调用失败 tokens=0，调用成功但内容不可用时照实记。"""
    t0 = time.perf_counter()
    keep = RewriteResult(question, False, False, "")

    def ms():
        return int(round((time.perf_counter() - t0) * 1000))

    def tokens():
        u = client.tracker.snapshot()
        return int(u.total_tokens or u.estimated_tokens or 0)

    try:
        msg = client.invoke(build_prompt(question, snaps, today))
    except Exception as e:  # noqa: BLE001  超时 / 网关错误 / 任何异常：回落，不报错
        logger.info("rewrite fallback: call failed (%s)", type(e).__name__)
        keep.reason = "call_failed"
        return keep, 0, ms()
    tok = tokens()
    d = parse(msg)
    if d is None or not isinstance(d.get("rewritten", ""), str):
        keep.reason = "bad_json"
        return keep, tok, ms()
    rewritten = (d.get("rewritten") or "").strip()
    needs = bool(d.get("needs_clarify"))
    keep.needs_clarify = needs
    if needs:
        keep.reason = "needs_clarify"
        return keep, tok, ms()
    if not rewritten or len(rewritten) > MAX_CHARS:
        keep.reason = "empty" if not rewritten else "too_long"
        return keep, tok, ms()
    ok, bad = guard_ok(rewritten, question, snaps, today)
    if not ok:
        logger.info("rewrite fallback: unsupported numbers %s", bad)
        keep.reason = "guard"
        return keep, tok, ms()
    changed = rewritten != question.strip()
    return RewriteResult(rewritten, changed, False, str(d.get("reason") or "")), tok, ms()


def record(original: str, r: RewriteResult, tokens: int, ms: int) -> dict:
    """result_json.rewrite（规格 §14.3 的六个键，字段名写死）。"""
    return {"original": original, "rewritten": r.rewritten, "changed": bool(r.changed),
            "needs_clarify": bool(r.needs_clarify), "tokens": int(tokens), "ms": int(ms)}
