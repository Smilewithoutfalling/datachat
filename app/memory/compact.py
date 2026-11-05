"""M4 压缩：只做遮罩（docs/roadmap/memory-batch4.md §3.3）。

只在 full 档、且完整历史超过本轮历史上限（cap）时生效，由 context.state_context 调用。
不调模型、不建表：遮罩是历史的纯函数（与批 1「工作状态不建表」同理），删一轮后自动跟着变，
哪一轮被遮了什么随时可以用 explain() 从同一份快照重算出来。

遮罩只动**输出**，不动用户原话：
- 最近 keep_last 轮（默认 2）逐字保留；
- 更早的成功轮：a_brief → 第一句（到第一个 。！？，最多 80 字）+ 原有的「（关键数字：…）」；
  result_digest 只留类型和形状（去掉 列= / 索引= / 键=）；chart_ref 只留图型；
- 更早的轮次里，用户问题超过 200 字（长粘贴）时才截，截到 200 字后注明可用 get_turn(N) 取回；
- a_full / code 不动（get_turn 和工作状态读的是原始快照，不经过这里）。

遮罩后仍超，才走 snapshots.render_block 原来的「从最早一轮开始丢」。只遮罩不丢轮时不算裁剪。
"""
from __future__ import annotations

import re
from dataclasses import replace

from app.memory.budget import estimate_tokens
from app.memory.snapshots import TurnSnapshot, render_block

KEEP_LAST = 2
SENTENCE_CHARS = 80
LONG_Q_CHARS = 200

_KEYNUM = re.compile(r"（关键数字：[^（）]*）$")
_SENTENCE_END = re.compile(r"[。！？]")
_DIGEST_DETAIL = re.compile(r"\s*(?:列|索引|键)=.*$", re.S)


def long_q_note(n: int) -> str:
    return f"…（原文较长已省略，可用 get_turn({n}) 取回）"


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    m = _SENTENCE_END.search(text)
    s = text[: m.end()] if m else text
    return s if len(s) <= SENTENCE_CHARS else s[: SENTENCE_CHARS - 1] + "…"


def mask_brief(a_brief: str) -> str:
    """'首段（关键数字：…）' → '第一句（关键数字：…）'。没有关键数字后缀时只留第一句。"""
    a = (a_brief or "").strip()
    if not a:
        return ""
    m = _KEYNUM.search(a)
    suffix = m.group(0) if m else ""
    body = a[: m.start()] if m else a
    return _first_sentence(body) + suffix


def mask_digest(d: str) -> str:
    """'DataFrame(3x2) 列=a,b' → 'DataFrame(3x2)'；'Series(3) 索引=region' → 'Series(3)'。"""
    return _DIGEST_DETAIL.sub("", d or "")


def mask_chart(ref: str) -> str:
    """'bar「各地区销售额」' → 'bar'；'PNG chart_x.png' → 'PNG'；'图表' 不变。"""
    r = (ref or "").strip()
    if not r:
        return ""
    if r.startswith("PNG "):
        return "PNG"
    return r.split("「", 1)[0] or "图表"


def mask_q(q: str, n: int) -> str:
    q = q or ""
    return q if len(q) <= LONG_Q_CHARS else q[:LONG_Q_CHARS] + long_q_note(n)


def mask(snaps: list[TurnSnapshot], keep_last: int = KEEP_LAST) -> list[TurnSnapshot]:
    """返回遮罩后的新快照列表（长度、顺序不变，所以 [第N轮] 编号不变）；不修改入参。"""
    snaps = list(snaps or [])
    cut = len(snaps) - max(0, keep_last)
    out = []
    for i, s in enumerate(snaps):
        if i >= cut:
            out.append(s)
            continue
        n = i + 1
        upd = {"q": mask_q(s.q, n)}
        if s.status == "ok":
            upd.update(a_brief=mask_brief(s.a_brief), result_digest=mask_digest(s.result_digest),
                       chart_ref=mask_chart(s.chart_ref))
        out.append(replace(s, **upd))
    return out


def fit(snaps: list[TurnSnapshot], cap: int, tz=None) -> tuple[str, int, list[int]]:
    """full 档的历史块：完整历史 ≤ cap 时与 state 完全相同；超过时先遮罩，遮罩后仍超才丢最早的轮次。
    返回 (块, 丢掉的轮数, 被遮罩且仍在块里的轮次编号)。"""
    snaps = list(snaps or [])
    whole, _ = render_block(snaps, 10 ** 9, tz)
    if estimate_tokens(whole) <= cap:
        block, dropped = render_block(snaps, cap, tz)
        return block, dropped, []
    masked = mask(snaps)
    block, dropped = render_block(masked, cap, tz)
    changed = [i + 1 for i, (a, b) in enumerate(zip(snaps, masked)) if a != b and i >= dropped]
    return block, dropped, changed


def explain(snaps: list[TurnSnapshot], cap: int) -> dict:
    """排查 / 测试用：full 档在上限 cap 下，哪些轮被遮罩、哪些轮被丢（含 12 轮窗口外的），编号与历史块一致。"""
    _, dropped, masked = fit(snaps, cap)
    return {"masked": masked, "dropped": list(range(1, dropped + 1))}
