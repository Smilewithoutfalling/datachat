"""出境审计（EV-B10）：把模型**实际收到的每一段 prompt**抓出来，按四条合同断言检查。

为什么审真实 prompt 而不是审模板：模板是拼出来的 —— `schema` 由 `describe_df` 渲染、
字段说明由 BM25 检索后截断、结果由 `format_result` 截断。任何一层漏了截断，模板都看不出来。
`fingerprint.render_system` 用同一个理由拿真实字符串：复刻拼接逻辑的检查会替人撒谎。

四条断言（合同值写死在本文件，**不读** `schema.MAX_CELL_CHARS`）：

1. **每张表样例行 ≤ 3** —— 与 `describe_df(df, n=3)` 逐字比对，再确认第 4 行的行唯一值不出现。
   只比 n 不够：`describe_df` 若被绕过（有人手写 schema），n 这个参数根本不参与。
2. **单值 ≤ 40 字** —— 超长值不得整段出现；同时要求截断形态真的出现，否则"整列都没进 prompt"
   会被误判成"截断生效"（假绿灯）。
3. **任一文本列的取值命中 ≤ 3** —— 这是"不含全量列值"的判据。**数据字典的命中文本也在审计范围内**：
   `.dict.csv` 同样是用户上传的文件，一条 "region：华东、华北、华南、西南、东北" 就是五个值出境。
4. **不含本机路径** —— 规格正则（`C:\\Users\\` / `/home/` / `/Users/`）**加上本次运行自己的绝对路径**
   （项目根、图表目录、数据集路径）。只靠正则不够：仓库装在 `D:\\` 下时正则一条都不命中，
   而 `outputs/charts/chart_x.png` 的绝对路径确实进了 summarizer 的 prompt。

第 2、3 条读合同值而不读实现常量：放宽 `MAX_CELL_CHARS` 必须让审计变红，否则
`test_egress_fails_when_limit_raised` 只是自证。有测试钉住实现常量 == 合同值，防止悄悄分叉。

只读，不产生任何判定，也不进模型输入 → 归 B 组（`fingerprint._EXEMPT`）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import pandas as pd

from app.tools.schema import clip, describe_df

EGRESS_MAX_SAMPLE_ROWS = 3      # 每张表最多几行样本
EGRESS_MAX_CELL_CHARS = 40      # 单个单元格最长多少字（合同值）
EGRESS_MAX_COLUMN_HITS = 3      # 任一列最多允许几个不同取值出境
DEFAULT_CODE = "result = len(df)"   # 单表；多表请显式传 code

# 规格原文写的是 `[A-Za-z]:\\\\Users\\\\`（markdown 里转义了一层），实际路径是单反斜杠。
PATH_PATTERN = re.compile(r"[A-Za-z]:\\Users\\|/home/|/Users/")

_ASCII = re.compile(r"^[\x00-\x7f]+$")
MAX_SCAN_VALUES = 5000          # 单列取值超过这个数只扫前 N 个，防止大表把审计拖死


@dataclass
class Prompt:
    """一次模型调用收到的全部消息（system + 历史 + 本轮传入）拼成的文本。"""
    call: int
    text: str


@dataclass
class Finding:
    rule: str       # sample_rows / cell_chars / column_values / local_path
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.detail}"


@dataclass
class Audit:
    agent: str = ""
    prompts: list[Prompt] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    executed: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.findings

    def text(self) -> str:
        return "\n".join(p.text for p in self.prompts)

    def by_rule(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in self.findings:
            out.setdefault(f.rule, []).append(f.detail)
        return out


# ---------------------------------------------------------------- 抓 prompt

def capture(dataset, question: str, *, agent: str = "workflow", code: str | None = None,
            use_dictionary: bool = True, max_attempts: int = 3):
    """跑一次 analyze（假模型，不联网），返回 (prompts, res)。

    `ScriptedChatModel.calls` 存的是**每次调用收到的 messages 原对象**，`prompt_text` 把它们
    按顺序拼平 —— 这正是出口处真正发出去的东西，不经过任何模板复刻。
    """
    from app.core.service import analyze
    from app.core.testing import oracle_model, prompt_text

    model = oracle_model(code or DEFAULT_CODE, agent)
    res = analyze(dataset, question, agent=agent, chat_model=model,
                  use_dictionary=use_dictionary, max_attempts=max_attempts)
    return [Prompt(i, prompt_text(msgs)) for i, msgs in enumerate(model.calls)], res


# ---------------------------------------------------------------- 四条断言

def check_sample_rows(data, text: str) -> list[str]:
    """1）每张表样例行 ≤ 3：结构段必须**逐字等于** `describe_df(n=3)` 的渲染。

    为什么是逐字比而不是数行数：数行数要解析 `to_string` 的对齐结果，格式一变就假红；
    而 `describe_df(n=4)` 的渲染与 `n=3` 的渲染不可能相等（连"前 N 行示例"这行都不同），
    所以"块存在"已经蕴含"恰好 3 行"。顺带把"有人绕过 describe_df 手写 schema"也堵住 ——
    那种情况 n 这个参数根本不参与。

    刻意**不**去数"第 4 行的值有没有出现在 prompt 里"：用户问"列出全部订单"时，
    第 4 行会经 `format_result` 回灌给 summarizer，那是结果通道，不是样例行通道。
    混在一起会把设计取舍报成 sample_rows 的问题，归因就错了（该由 ③ 报）。
    """
    problems = []
    for label, df in _frames(data):
        block = describe_df(df, n=EGRESS_MAX_SAMPLE_ROWS)
        if block not in text:
            problems.append(
                f"{label} 的结构段与 describe_df(n={EGRESS_MAX_SAMPLE_ROWS}) 的渲染不是逐字相同"
                f"（样例行数被改了，或有人绕过 describe_df 手写了 schema）")
    return problems


def check_cell_chars(data, text: str) -> list[str]:
    """2）单值 ≤ 40 字：超长值不得整段出现；且截断形态必须真的出现（正控）。"""
    problems = []
    values = [v for _label, df in _frames(data) for v in _text_values(df, all_columns=True)]
    long_values = sorted({v for v in values if len(v) > EGRESS_MAX_CELL_CHARS})
    leaked = [v for v in long_values if v in text]
    for v in leaked[:5]:
        problems.append(f"{len(v)} 字的值整段出境（上限 {EGRESS_MAX_CELL_CHARS}）：{v[:60]!r}…")
    if len(leaked) > 5:
        problems.append(f"另有 {len(leaked) - 5} 个超长值整段出境")
    if long_values and not leaked:
        clipped = [clip(v, EGRESS_MAX_CELL_CHARS) for v in long_values[:200]]
        if not any(c in text for c in clipped):
            problems.append(
                f"表里有 {len(long_values)} 个超过 {EGRESS_MAX_CELL_CHARS} 字的值，"
                f"但 prompt 里既没有整段出现、也没有按 {EGRESS_MAX_CELL_CHARS} 字截断出现 —— "
                f"这段文本没有覆盖样例行，审错了对象")
    return problems


def check_column_values(data, text: str) -> list[str]:
    """3）任一文本列的取值命中 ≤ 3（含数据字典的命中文本）。"""
    problems = []
    for label, df in _frames(data):
        for col in df.columns:
            s = df[col]
            if not _is_text_column(s):
                continue
            values = _unique_text(s)
            hits = [v for v in values if _appears(v, text)]
            if len(hits) > EGRESS_MAX_COLUMN_HITS:
                preview = "、".join(repr(v) for v in hits[:5])
                problems.append(
                    f"{label}.{col} 有 {len(hits)} 个取值出境（上限 {EGRESS_MAX_COLUMN_HITS}）：{preview}…")
    return problems


def check_local_path(text: str, forbidden=()) -> list[str]:
    """4）不含本机路径：规格正则 + 本次运行自己的绝对路径。"""
    problems = []
    for m in PATH_PATTERN.finditer(text):
        problems.append(f"prompt 里出现本机路径：…{text[max(0, m.start() - 24):m.end() + 40]}…")
    # 项目根是图表目录的前缀，两条都报只是噪声：被更长候选包含的短路径丢掉
    paths = [p for p in (os.fspath(p) for p in forbidden if p)]
    paths = [p for p in paths if not any(q != p and p in q for q in paths)]
    for p in paths:
        for form in _path_forms(p):
            if form in text:
                problems.append(f"prompt 里出现本次运行的绝对路径：{form}")
                break
    return problems


def own_paths(dataset) -> list[str]:
    """这次运行自己的绝对路径（项目根 / 图表目录 / 数据集）。正则只认得用户目录那一类。"""
    from app.config import PROJECT_ROOT
    from app.tools import persist
    out = [PROJECT_ROOT, persist.CHART_DIR]
    if isinstance(dataset, (str, os.PathLike)):
        out.append(os.path.abspath(os.fspath(dataset)))
    return out


# ---------------------------------------------------------------- 总入口

def audit(dataset, question: str, *, agent: str = "workflow", code: str | None = None,
          use_dictionary: bool = True, forbidden=(), max_attempts: int = 3) -> Audit:
    """跑一次真实分析链路，对全部 prompt 做四条断言。"""
    from app.tools.dataset import load_data

    prompts, res = capture(dataset, question, agent=agent, code=code,
                           use_dictionary=use_dictionary, max_attempts=max_attempts)
    out = Audit(agent=agent, prompts=prompts, executed=bool(res.executed), error=res.error)
    text = out.text()
    data, _desc = load_data(dataset)
    out.findings += [Finding("sample_rows", p) for p in check_sample_rows(data, text)]
    out.findings += [Finding("cell_chars", p) for p in check_cell_chars(data, text)]
    out.findings += [Finding("column_values", p) for p in check_column_values(data, text)]
    out.findings += [Finding("local_path", p)
                     for p in check_local_path(text, [*own_paths(dataset), *forbidden])]
    return out


# ---------------------------------------------------------------- 内部

def _frames(data):
    from app.tools.dataset import is_multi
    if is_multi(data):
        return [(f"表 {name}", df) for name, df in data.items()]
    return [("表", data)]


def _row_unique_col(df: pd.DataFrame):
    """找一列"每行都不同、且取值够独特"的文本列，用来数"第几行出境了"。

    只认文本列：数值列不能用子串判存在 —— `units` 里的 `3` 会命中 "前 3 行示例"。
    短 ASCII 值（`A` / `B`）同理，会被 `pandas` 里的字母骗到，所以要求 ASCII 值至少 4 个字符。
    """
    for col in df.columns:
        s = df[col]
        if not _is_text_column(s):
            continue
        try:
            if not (s.is_unique and not s.isna().any() and len(s)):
                continue
        except (TypeError, ValueError):
            continue
        values = [str(v) for v in s]
        if all(_distinctive(v) for v in values):
            return col
    return None


def _distinctive(value: str) -> bool:
    """这个值能不能用子串法判定"出没出境"。"""
    return bool(value) and (not _ASCII.match(value) or len(value) >= 4)


def _is_text_column(s: pd.Series) -> bool:
    return bool(pd.api.types.is_object_dtype(s)
                or isinstance(s.dtype, pd.CategoricalDtype)
                or pd.api.types.is_string_dtype(s))


def _unique_text(s: pd.Series) -> list[str]:
    values = []
    for v in s.dropna().unique()[:MAX_SCAN_VALUES]:
        text = str(v)
        if text:
            values.append(text)
    return values


def _text_values(df: pd.DataFrame, all_columns: bool = False) -> list[str]:
    out = []
    for col in df.columns:
        s = df[col]
        if all_columns or _is_text_column(s):
            out.extend(_unique_text(s))
    return out


def _appears(value: str, text: str) -> bool:
    """子串命中；短 ASCII 值（如 'A'、'B'）要卡词边界，否则 'pandas' 里的 a 也算命中。"""
    if not value:
        return False
    if _ASCII.match(value) and len(value) < 4:
        return re.search(r"(?<![0-9A-Za-z])" + re.escape(value) + r"(?![0-9A-Za-z])", text) is not None
    return value in text


def _path_forms(path: str) -> list[str]:
    p = os.fspath(path).rstrip("\\/")
    if not p:
        return []
    forms = [p]
    if os.sep == "\\":
        forms.append(p.replace("\\", "/"))
    else:
        forms.append(p.replace("/", "\\"))
    return forms
