"""写入门槛（M6）：检测「记住 / 以后都 / 从现在起」这类想长期生效的要求，只追加一条 warning。
docs/roadmap/memory-batch4.md §3.6。

- 不写库、不改 prompt：命中的句子照样按 B1 进本会话的前提区（会话内是用户本人的指令），这里只说明「不会跨会话」，
  并指向数据集页的「口径与规则」（M2）——跨会话生效只能由用户在那里亲手写。
- 整句模式，不按单词：「记住这个数」不命中（规格陷阱）。宁可漏，不可误报。
- 文案是用户可见的，不带正则原文。
- 判断在 service.py（memory_mode != off 时），评测和 API 走同一条路。
"""
from __future__ import annotations

import re

WARNING = ("检测到可能长期生效的要求：它只在本次会话里有效。如需让它对这个数据集的所有会话生效，"
           "请在数据集页的「口径与规则」里添加。")

_PATTERNS = [
    re.compile(r"以后都|今后都|往后都|从现在起|从今以后"),
    re.compile(r"(?<![a-z])(always|from now on)(?![a-z])", re.I),
    re.compile(r"(请)?记住[：:，,]?.*(以后|今后|每次|一律|所有|都要)"),
    re.compile(r"忽略.*(条件|过滤|筛选|要求|规则)"),
    re.compile(r"(?<![a-z])ignore .*(filter|instruction|rule)", re.I),
]


def detect(question: str) -> bool:
    text = str(question or "")
    return any(p.search(text) for p in _PATTERNS)
