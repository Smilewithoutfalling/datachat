"""阶段 7 A3：枚举值召回（docs/roadmap/phase7-a2a3.md）。

问题里的词和文本列的实际取值做模糊匹配，命中的写进字段说明，告诉模型「华东」在 region 列里写作「华东区」。
筛选值写错（全称/简称、大小写、首尾空格、全角半角）时，结果会是空表或少算，而模型从 3 行样例里看不出来。

只在能补上新信息时才出提示：
- 匹配是模糊的（归一化后才相等、或者是包含关系），或者
- 匹配是精确的，但这个取值在样例行里看不到（模型不知道它在哪一列），或者
- 同一个词在一列里对上了好几种写法（「Basic」「basic 」）：哪怕都在样例里，也要把它们并排列出来。
问题原文和样例里已经能看到的精确匹配不提示。没有任何提示时 prompt 逐字节不变（P8 / state 哈希）。

出境合同（app/eval/egress.py 第 3 条，任一文本列的取值出境 ≤ 3）：每一列先数「样例行 + 问题原文」里
已经出现的取值，提示只能补到这一列总共 3 个为止，超出的丢掉。所以样例里已经露了 3 个不同取值的列，
这里一个都不会加。这是合同优先，代价是有些列上 A3 不起作用。
"""
import unicodedata

import jieba
import pandas as pd

from app.tools.schema import MAX_CELL_CHARS, clip, data_block

MAX_COLUMN_HITS = 3      # 与出境合同 EGRESS_MAX_COLUMN_HITS 同值；tests/test_a2a3.py 钉住二者相等
MAX_UNIQUE = 2000        # 不同取值超过这么多的列（编号、自由文本）不做召回
MAX_HINTS = 6            # 整段最多几条
MIN_TERM = 2             # 问题里的词至少 2 个字（单字太泛）


def _norm(x) -> str:
    return "".join(unicodedata.normalize("NFKC", str(x)).split()).casefold()


def _terms(question: str) -> list[str]:
    seen, out = set(), []
    for w in jieba.lcut(question or ""):
        n = _norm(w)
        # 纯数字和符号的词（「2024」「03」）不参与：它们会和日期、编号里的数字串成一片
        if len(n) >= MIN_TERM and n not in seen and any(ch.isalpha() for ch in n):
            seen.add(n)
            out.append(n)
    return out


def _close(t: str, vn: str) -> bool:
    """相等，或者一方包含另一方且短的一方至少占长的一半（「华东」对「华东区」算，「商品」对「数码商品01」不算）。"""
    if t == vn:
        return True
    short, long_ = (t, vn) if len(t) <= len(vn) else (vn, t)
    return short in long_ and len(short) * 2 >= len(long_)


def _frames(data):
    if isinstance(data, dict):
        return [(f"{name}.", df) for name, df in data.items()]
    return [("", data)]


def _text_values(s: pd.Series) -> list[str]:
    if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
        return []
    vals = s.dropna().unique()
    if len(vals) > MAX_UNIQUE:
        return []
    return [v for v in (str(x) for x in vals) if v.strip()]


def find_hints(question: str, data, visible_text: str) -> list[tuple[str, str, str]]:
    """返回 [(问题里的词, 列标签, 实际取值)]。visible_text 是模型已经能看到的文本（schema 渲染 + 问题原文）。"""
    terms = _terms(question)
    if not terms:
        return []
    qn = _norm(question)
    out = []
    for prefix, df in _frames(data):
        colnames = {_norm(c) for c in df.columns}
        for col in df.columns:
            values = _text_values(df[col])
            if not values:
                continue
            shown = {v for v in values if v in visible_text}
            budget = MAX_COLUMN_HITS - len(shown)
            by_term: dict[str, list[str]] = {}
            for v in values:
                vn = _norm(v)
                if len(vn) < MIN_TERM:
                    continue
                term = next((t for t in terms if t not in colnames and _close(t, vn)), None)
                if term is None and vn in qn and any(ch.isalpha() for ch in vn):
                    term = vn
                if term is not None:
                    by_term.setdefault(term, []).append(v)
            for term, vs in by_term.items():
                variants = len(vs) >= 2          # 同一个词对上好几种写法（大小写、空格）：全部列出来才有用
                for v in vs:
                    if not variants and v in shown and (v in (question or "") or _norm(v) == term):
                        continue                 # 只有一种写法，模型在样例里看得见，问题也写对了
                    if v not in shown:
                        if budget <= 0:
                            continue
                        budget -= 1
                    out.append((term, f"{prefix}{col}", v))
                    if len(out) >= MAX_HINTS:
                        return out
    return out


def format_hints(hints) -> str:
    if not hints:
        return ""
    lines = [f"- 问题里的「{clip(t, MAX_CELL_CHARS)}」：{clip(col, 64)} 列里的实际取值是 {clip(v, MAX_CELL_CHARS)!r}"
             for t, col, v in hints]
    return ("数据里和问题用词相近的取值（仅供对照写法：要按某个值筛选时，照这里的实际写法写，"
            "同一个词有几种写法的要都算上；这个值该不该用来筛选，按题意判断）：\n"
            + data_block("\n".join(lines)))


def value_hints(question: str, data, schema: str) -> str:
    """给 service 用：返回要附在字段说明后面的一段；没有提示返回空串。任何异常都吞掉返回空串，不影响主流程。"""
    try:
        return format_hints(find_hints(question, data, f"{schema}\n{question}"))
    except Exception:  # noqa: BLE001
        return ""
