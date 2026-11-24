"""结果卡的关键数字（阶段 7.6 U3-2，docs/roadmap/phase76-u3u5.md §1.2 做法 K3）。

server 层确定性产出 `result.key_numbers = [{value, label}]`，前端 `ui/web/src/turn.ts` keyNumbers 只认这个字段。
不调模型、不改 app/core：只 import grounding 的三个私有函数和 ambiguity.METRIC_MARKERS，只读（§4 已定 6）。

规则（写死）：
1. 只在 r.ok、r.executed、not r.clarify、r.result 不是拒答字符串时产出；其余情况返回 None，调用方不写这个键。
2. 候选数（值，口径）全部取自 r.result 原对象，按 result 自己的顺序：
   - 标量（数字，不含 bool）：口径取问题里的第一个指标词（METRIC_MARKERS）；问题里没有指标词就不出（§4 已定 5）。
   - dict：数值项，口径是键。
   - 数值 Series：≤ 3 项全取；> 3 项时只有值单调（已排序，Top-N 一类）才取前 3 项，否则不出。
     口径「索引 · Series 名」，没有名字只用索引；零点时刻的 Timestamp 索引写成日期。
   - 单行 DataFrame：数值列，口径是列名。多行 DataFrame 不出。
3. 和结论对上才出：结论按 grounding 的规则切出有分量的数字（_tokens + _significant），每个候选数找第一个按
   _candidates 的容差对得上、还没用过的结论数字；value 取结论里的原文写法，label 取候选数的口径。最多 3 个。
   value 在 r.unverified_numbers 里的跳过（双保险）。
4. 小整数（< 100、不带单位）不出：_significant 本来就不核它们。
5. 旧消息不回填（原对象没落库）。
"""
from __future__ import annotations

import math
import numbers
from typing import Any, Optional

from app.core.ambiguity import METRIC_MARKERS
from app.core.grounding import _candidates, _significant, _tokens
from app.core.result import is_refusal

MAX = 3


def _num(v: Any) -> Optional[float]:
    """数字（含 numpy 标量），不含 bool、NaN、inf；其余返回 None。"""
    if isinstance(v, bool) or type(v).__name__ == "bool_":
        return None
    if not isinstance(v, numbers.Number) or isinstance(v, complex):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _index_label(x: Any) -> str:
    try:
        import pandas as pd
        if isinstance(x, pd.Timestamp) and x == x.normalize():
            return x.strftime("%Y-%m-%d")
    except ImportError:  # pragma: no cover - pandas 是硬依赖
        pass
    return str(x)


def _candidates_of(result: Any, question: str) -> list[tuple[float, str]]:
    """r.result → [(值, 口径)]，按 result 自己的顺序。"""
    import pandas as pd

    v = _num(result)
    if v is not None:
        m = METRIC_MARKERS.search(question or "")
        return [(v, m.group(0))] if m else []
    if isinstance(result, dict):
        return [(f, str(k)) for k, x in result.items() if (f := _num(x)) is not None]
    if isinstance(result, pd.Series):
        if not pd.api.types.is_numeric_dtype(result) or pd.api.types.is_bool_dtype(result):
            return []
        s = result
        if len(s) > MAX:
            if not (s.is_monotonic_increasing or s.is_monotonic_decreasing):
                return []
            s = s.iloc[:MAX]
        name = "" if s.name is None else str(s.name).strip()
        out = []
        for idx, x in s.items():
            f = _num(x)
            if f is not None:
                out.append((f, f"{_index_label(idx)} · {name}" if name else _index_label(idx)))
        return out
    if isinstance(result, pd.DataFrame):
        if len(result) != 1:
            return []
        row = result.iloc[0]
        return [(f, str(c)) for c, x in row.items() if (f := _num(x)) is not None]
    return []


def key_numbers_of(r) -> Optional[list[dict]]:
    """AnalysisResult → [{value, label}]（最多 3 个）；不该产出时返回 None。"""
    if not (r.ok and r.executed and not r.clarify) or is_refusal(r.result):
        return None
    cands = _candidates_of(r.result, r.question)
    if not cands:
        return []
    toks = [(raw, v, dec, unit) for raw, v, dec, unit, after in _tokens(r.answer or "")
            if _significant(v, dec, unit, after)]
    bad = {str(x).strip() for x in (r.unverified_numbers or [])}
    used: set[int] = set()
    out: list[dict] = []
    for val, label in cands:
        if len(out) >= MAX:
            break
        for i, (raw, v, dec, unit) in enumerate(toks):
            if i in used:
                continue
            if any(abs(abs(val) - abs(c)) <= t for c, t in _candidates(v, dec, unit)):
                used.add(i)
                if raw not in bad:
                    out.append({"value": raw, "label": label})
                break
    return out


def attach_key_numbers(record: dict, r) -> None:
    """done 分支用：把 key_numbers 写进将要落库、也将要外发的同一个 result 字典（不该产出时不写这个键）。"""
    kn = key_numbers_of(r)
    if kn is not None:
        record["key_numbers"] = kn
