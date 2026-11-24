"""会话标题（阶段 7.6 U5，docs/roadmap/phase76-u3u5.md §2.3；已定规则 S 2026-11-19，phase76-ui.md:44、:80）。

不再直接用用户原话；本地规则、确定性、不调模型、不读数据集：
1. 预处理：NFKC，去控制字符，连续空白合成一个，strip；为空返回空串（界面显示「未命名会话」）。
2. 取第一个分句：在第一个 `：:，,。？?！!；;` 处截断，得到 head。
3. 在 head 里找指标词：METRIC_MARKERS（app/core/ambiguity.py，只 import 不改）的第一个命中；
   紧挨着的后续命中并成一段（「离职」+「人数」→「离职人数」）。
4. 名词短语：jieba.posseg 标注 head，在指标词之前找第一段连续的名词（词性以 n 开头，或 vn / an / eng），
   跳过泛词（GENERIC）；前面没有再到指标词之后找。名词跨过指标词边界时截在边界处。
5. 有指标词也有名词短语时按原文语序拼接，截到 12 字；否则 head 截 12 字。不加省略号。

标题不许为了好看去改 METRIC_MARKERS（它管 clarify 放行，属 A 组）；要补词在这里另加本地补充表
（§4 已定 2：先不补）。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from app.core.ambiguity import METRIC_MARKERS
from app.core.text import CONTROL_CHARS

TITLE_MAX = 12
_CLAUSE_END = re.compile(r"[：:，,。？?！!；;]")
_SPACES = re.compile(r"\s+")
_NOUN_FLAGS = ("vn", "an", "eng")
# 泛词：不算名词短语（「这份数据」「分析图表」这类说不出主题的词）
GENERIC = frozenset({"数据", "这份", "表", "图", "图表", "情况", "结果", "分析", "表格", "数据集", "字段", "内容", "信息"})


def _clean(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = CONTROL_CHARS.sub("", s)
    return _SPACES.sub(" ", s).strip()


def _head(s: str) -> str:
    for part in _CLAUSE_END.split(s):
        if part.strip():
            return part.strip()
    return ""


def _metric_span(head: str) -> tuple[int, int] | None:
    spans = [m.span() for m in METRIC_MARKERS.finditer(head)]
    if not spans:
        return None
    start, end = spans[0]
    for a, b in spans[1:]:
        if a != end:
            break
        end = b
    return start, end


def _is_noun(word: str, flag: str) -> bool:
    return (flag.startswith("n") or flag in _NOUN_FLAGS) and word.strip() != "" and word not in GENERIC


def _tagged(head: str) -> list[tuple[int, int, str, str]]:
    """[(起, 止, 词, 词性)]，字符偏移。"""
    import jieba
    import jieba.posseg as pseg
    jieba.setLogLevel(60)
    out, pos = [], 0
    for w in pseg.cut(head):
        i = head.find(w.word, pos)
        if i < 0:            # jieba 不会改字，兜底而已
            continue
        out.append((i, i + len(w.word), w.word, w.flag))
        pos = i + len(w.word)
    return out


def _first_run(tokens: Iterable[tuple[int, int, str, str]], lo: int, hi: int) -> tuple[int, int] | None:
    """[lo, hi) 区间里第一段连续名词（逐字相邻），跨界的词截在边界处。"""
    run: tuple[int, int] | None = None
    for a, b, word, flag in tokens:
        a2, b2 = max(a, lo), min(b, hi)
        if a2 >= b2:
            if run:
                break
            continue
        if _is_noun(word, flag):
            if run is None:
                run = (a2, b2)
            elif a2 == run[1]:
                run = (run[0], b2)
            else:
                break
        elif run:
            break
    return run


def session_title(question: str) -> str:
    """问题 → 会话标题（≤ 12 字；为空表示没有可用的字）。"""
    s = _clean(question)
    if not s:
        return ""
    head = _head(s)
    span = _metric_span(head)
    if span:
        tokens = _tagged(head)
        before = _first_run(tokens, 0, span[0])
        if before:
            return (head[before[0]:before[1]] + head[span[0]:span[1]])[:TITLE_MAX]
        after = _first_run(tokens, span[1], len(head))
        if after:
            return (head[span[0]:span[1]] + head[after[0]:after[1]])[:TITLE_MAX]
    return head[:TITLE_MAX]


def unique_title(title: str, taken: Iterable[str]) -> str:
    """同一数据集已有同名会话时追加「（2）」「（3）」……（§4 已定 4）。只给自动生成的标题用。"""
    if not title:
        return title
    used = set(taken)
    if title not in used:
        return title
    n = 2
    while f"{title}（{n}）" in used:
        n += 1
    return f"{title}（{n}）"
