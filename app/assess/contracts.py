"""各节点的评估契约（phase75-assess.md §4，初版）。全部是确定性检查：没有模型判分，没有放宽规则（§0 规则 2）。

每条契约返回一个 Verdict：status ∈ ok / warn / fail / not_checked，外加一句原因。
**not_checked ≠ ok**：契约这次没有能判断的材料（代码解析不了、没认出任何列引用、计划里没有可核对的列名、
拒答 / 反问 / 执行出错时没有结论可核）就落 not_checked，绝不记成 ok —— 否则「全绿」里混着「根本没查」。`step` 标注它属于方案 §2 的第几步：
本文件的契约全部是**第 1 步**（只检出、只记录）。方案里两处会动流水线的地方本步都不做，留给第 3 步：

- planner 计划过长：本步只记 WARN，**不**在 codegen prompt 后追加任何句子（PR #105 待定第 1 条）；
- reviewer 改了列 / 过滤条件：本步只标 fail，**不**拒绝修复、不转 replan（PR #105 待定第 2 条）。

| 契约 id | 节点 | 判什么 |
|---|---|---|
| planner.length | planner | 计划 > 3000 字 → warn |
| planner.columns | planner | 计划里反引号 / 引号中的「列名形状」词都在 schema 里 |
| codegen.parse | codegen | 输出能被 ast 解析 |
| codegen.columns | codegen | 只引用存在的列（AST，见 code_refs.py）；多表时 dfs['表'] 的表存在 |
| codegen.result | codegen | 给 result 赋过值 |
| codegen.imports | codegen | import 都在能力对象的 allowed_imports 里，没有相对导入 |
| codegen.names | codegen | 没用沙箱不给的内建（能力对象的 forbidden_builtins）、没用另一种数据变量（多表用 df / 单表用 dfs）；其他未定义名字 → warn |
| executor.shape | executor | 有结果（类型、行数、列写进 details）；报错或没有结果 → fail |
| executor.sanity | executor | A2 的 sanity_issue 为空 |
| reviewer.scope | reviewer | 修复前后，代码引用的（schema 内）列名集合与过滤条件集合不变（修复前引用了 k 个不存在的列时，最多可新增 k 个真实列） |
| summarizer.grounding | summarizer | 结论里的数字都能在 result 里找到（app/core/grounding.py 的 unverified_numbers，证据口径与 service 一致） |
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.assess import code_refs
from app.tools.sandbox_caps import CAPS, SandboxCaps

OK, WARN, FAIL, NOT_CHECKED = "ok", "warn", "fail", "not_checked"
STATUSES = (OK, WARN, FAIL, NOT_CHECKED)
PLAN_MAX_CHARS = 3000
STEP = 1


@dataclass
class Verdict:
    contract: str
    status: str
    reason: str = ""
    step: int = STEP
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    """一次运行的固定信息（来自快照 run 行）。"""
    columns: dict                      # {表名: [列名]}；单表表名为 ""
    multi: bool = False
    question: str = ""                 # 用户原话（改写前）
    caps: SandboxCaps = CAPS

    @property
    def all_columns(self) -> set:
        return {c for cols in self.columns.values() for c in cols}

    def table_columns(self, table) -> set:
        if table in self.columns:
            return set(self.columns[table])
        return self.all_columns

    @classmethod
    def from_run(cls, run: dict) -> "Context":
        return cls(columns=run.get("columns") or {}, multi=bool(run.get("multi")),
                   question=run.get("question") or "")


# ------------------------------------------------------------------ planner
_REFUSAL_MARKS = ("数据不足以回答", "无法回答")
_QUOTED = [re.compile(p) for p in (r"`([^`\n]+)`", r"'([^'\n]+)'", r'"([^"\n]+)"', r"「([^」\n]+)」",
                                   r"“([^”\n]+)”", r"‘([^’\n]+)’")]
_COLUMN_SHAPED = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")


def planner_length(state: dict, upd: dict, ctx: Context) -> Verdict:
    plan = upd.get("plan") or ""
    if len(plan) > PLAN_MAX_CHARS:
        return Verdict("planner.length", WARN, f"计划 {len(plan)} 字，超过 {PLAN_MAX_CHARS}（本步只记录，不追加 prompt）",
                       details={"chars": len(plan)})
    return Verdict("planner.length", OK, details={"chars": len(plan)})


def planner_columns(state: dict, upd: dict, ctx: Context) -> Verdict:
    """中文散文判不可靠，只查反引号 / 引号里的词；只把「列名形状」（ASCII、带下划线的 snake_case）且不是
    pandas / numpy / Python 名字的词当列名。在表结构、字段说明、口径块、问题原文里出现过的词不算缺失
    （它可能是样例值）。拒答计划（点名缺什么字段）和反问不查。"""
    if upd.get("clarify"):
        return Verdict("planner.columns", NOT_CHECKED, "反问，没有计划可核")
    plan = upd.get("plan") or ""
    if any(m in plan for m in _REFUSAL_MARKS):
        return Verdict("planner.columns", NOT_CHECKED, "拒答计划：点名缺失字段是预期行为，不核列名")
    known = ctx.all_columns | {t for t in ctx.columns if t}
    context_text = "\n".join(str(state.get(k) or "") for k in
                             ("schema", "field_notes", "metrics_block", "memory_state", "memory_history", "question"))
    context_text += "\n" + ctx.question
    # matched：引号里正好是真实列名 / 表名（核对过、存在）；skipped：不是「列名形状」（中文、带空格……）或是库函数名，
    # 契约认不出它是不是列，跳过不核。两样都没有、也没有 missing → 计划里没有任何能核的列名 → not_checked。
    missing, matched, skipped = [], [], []
    for rx in _QUOTED:
        for tok in rx.findall(plan):
            tok = tok.strip()
            if tok in known:
                matched.append(tok)
                continue
            if not _COLUMN_SHAPED.match(tok) or tok in code_refs.library_names():
                skipped.append(tok)
                continue
            if tok in context_text:
                matched.append(tok)          # 样例值 / 口径词：在上下文里出现过，核过、不算缺失
                continue
            if tok not in missing:
                missing.append(tok)
    details = {"matched": sorted(set(matched)), "skipped": sorted(set(skipped))}
    if missing:
        return Verdict("planner.columns", FAIL, "计划引用了表里没有的列：" + "、".join(missing),
                       details={**details, "missing": missing})
    if not matched:
        why = "计划里没有可核对的列名"
        if skipped:
            why += f"（跳过 {len(set(skipped))} 个非列名形状的词，如中文列名）"
        return Verdict("planner.columns", NOT_CHECKED, why, details=details)
    return Verdict("planner.columns", OK, details=details)


# ------------------------------------------------------------------ codegen
def _code_refs(code: str, ctx: Context):
    return code_refs.analyze_code(code, multi=ctx.multi, tables=[t for t in ctx.columns if t],
                                  result_var=ctx.caps.result_var)


_UNPARSED = "代码无法解析，未检查"


def codegen_parse(state: dict, upd: dict, ctx: Context) -> Verdict:
    code = upd.get("code") or ""
    if code_refs.parse(code) is None:
        why = "输出不是可解析的 Python 代码"
        if upd.get("truncated"):
            why += "（输出被长度上限截断）"
        return Verdict("codegen.parse", FAIL, why)
    return Verdict("codegen.parse", OK)


def missing_columns(refs, ctx: Context) -> list:
    out = []
    for table, col in refs.columns:
        if col in refs.created or col in ctx.table_columns(table):
            continue
        label = f"{table}.{col}" if table else col
        if label not in out:
            out.append(label)
    return out


def codegen_columns(state: dict, upd: dict, ctx: Context) -> Verdict:
    refs = _code_refs(upd.get("code") or "", ctx)
    if refs is None:
        return Verdict("codegen.columns", NOT_CHECKED, _UNPARSED)
    problems = []
    if refs.bad_tables:
        problems.append("不存在的表：" + "、".join(dict.fromkeys(refs.bad_tables)))
    miss = missing_columns(refs, ctx)
    if miss:
        problems.append("不存在的列：" + "、".join(miss))
    if problems:
        return Verdict("codegen.columns", FAIL, "；".join(problems),
                       details={"missing": miss, "bad_tables": list(dict.fromkeys(refs.bad_tables))})
    if not refs.columns:
        # code_refs 宁漏不误报：iloc / 变量列名 / 少见写法都认不出。一个列引用都没认出时，「没有缺列」不是核过的结论。
        return Verdict("codegen.columns", NOT_CHECKED, "代码里没认出任何列引用，无从核对")
    return Verdict("codegen.columns", OK, details={"columns": sorted({c for _, c in refs.columns})})


def codegen_result(state: dict, upd: dict, ctx: Context) -> Verdict:
    refs = _code_refs(upd.get("code") or "", ctx)
    if refs is None:
        return Verdict("codegen.result", NOT_CHECKED, _UNPARSED)
    if not refs.assigns_result:
        return Verdict("codegen.result", FAIL, f"没有给 {ctx.caps.result_var} 赋值")
    return Verdict("codegen.result", OK)


def codegen_imports(state: dict, upd: dict, ctx: Context) -> Verdict:
    refs = _code_refs(upd.get("code") or "", ctx)
    if refs is None:
        return Verdict("codegen.imports", NOT_CHECKED, _UNPARSED)
    bad = []
    for mod, relative in refs.imports:
        if relative:
            bad.append(f"相对导入 {mod or '.'}")
        elif mod not in ctx.caps.allowed_imports:
            bad.append(mod)
    if bad:
        return Verdict("codegen.imports", FAIL, "沙箱不允许的 import：" + "、".join(dict.fromkeys(bad)))
    return Verdict("codegen.imports", OK)


def codegen_names(state: dict, upd: dict, ctx: Context) -> Verdict:
    refs = _code_refs(upd.get("code") or "", ctx)
    if refs is None:
        return Verdict("codegen.names", NOT_CHECKED, _UNPARSED)
    caps = ctx.caps
    injected = caps.injected_names(ctx.multi)
    other_data = set(caps.single_data_vars if ctx.multi else caps.multi_data_vars)
    free = refs.free_names
    forbidden = sorted(free & caps.forbidden_builtins)
    wrong_data = sorted(free & other_data)
    if forbidden or wrong_data:
        parts = []
        if forbidden:
            parts.append("沙箱不提供的内建：" + "、".join(forbidden))
        if wrong_data:
            parts.append(("多表" if ctx.multi else "单表") + "时没有变量：" + "、".join(wrong_data))
        return Verdict("codegen.names", FAIL, "；".join(parts),
                       details={"forbidden": forbidden, "wrong_data": wrong_data})
    unknown = sorted(free - injected - set(caps.safe_builtins) - {"__import__", "__name__"})
    if unknown:
        return Verdict("codegen.names", WARN, "未定义的名字（运行到会 NameError）：" + "、".join(unknown),
                       details={"unknown": unknown})
    return Verdict("codegen.names", OK)


# ------------------------------------------------------------------ executor
def _shape(v) -> dict:
    import pandas as pd
    if isinstance(v, pd.DataFrame):
        return {"type": "DataFrame", "rows": int(v.shape[0]), "cols": int(v.shape[1]),
                "columns": [str(c) for c in v.columns]}
    if isinstance(v, pd.Series):
        return {"type": "Series", "rows": int(len(v)), "name": None if v.name is None else str(v.name)}
    if isinstance(v, dict):
        return {"type": "dict", "keys": [str(k) for k in v]}
    if isinstance(v, (list, tuple)):
        return {"type": type(v).__name__, "rows": len(v)}
    return {"type": type(v).__name__}


def executor_shape(state: dict, upd: dict, ctx: Context) -> Verdict:
    err = upd.get("error") or ""
    if err:
        last = [ln for ln in err.strip().splitlines() if ln.strip()]
        return Verdict("executor.shape", FAIL, "执行出错：" + (last[-1] if last else err)[:200])
    res = upd.get("result")
    if res is None and not upd.get("chart_path") and not upd.get("chart_options"):
        return Verdict("executor.shape", FAIL, "执行成功但没有结果")
    from app.core.result import is_refusal
    shape = _shape(res)
    if is_refusal(res):
        return Verdict("executor.shape", OK, "拒答", details=shape)
    desc = shape["type"] + (f" {shape['rows']} 行" if "rows" in shape else "") + (
        f" × {shape['cols']} 列" if "cols" in shape else "")
    return Verdict("executor.shape", OK, desc, details=shape)


def executor_sanity(state: dict, upd: dict, ctx: Context) -> Verdict:
    if upd.get("error"):
        return Verdict("executor.sanity", NOT_CHECKED, "执行出错，无结果可判")
    issue = upd.get("sanity_issue") or ""
    if issue:
        return Verdict("executor.sanity", FAIL, issue)
    return Verdict("executor.sanity", OK)


# ------------------------------------------------------------------ reviewer
def scope_of(code: str, ctx: Context):
    """(schema 内被引用的列集合, 引用了但 schema 里没有的列集合, 过滤条件集合)；解析不了返回 None。"""
    refs = _code_refs(code, ctx)
    conds = code_refs.filter_conditions(code)
    if refs is None or conds is None:
        return None
    cols = {c for t, c in refs.columns if c in ctx.table_columns(t)}
    return cols, set(missing_columns(refs, ctx)), conds


def reviewer_scope(state: dict, upd: dict, ctx: Context) -> Verdict:
    """列集合只算 schema 里真有的列。唯一的口径规定：修复前引用了 k 个不存在的列（KeyError 那类），
    修复后最多可以新增 k 个 schema 里的列 —— 把拼错的列名改对（'regin' → 'region'）不是换口径；
    除此之外，增删任何一个真实列、增删改任何一个过滤条件都是 fail。"""
    if state.get("not_code") or state.get("truncated"):
        return Verdict("reviewer.scope", NOT_CHECKED, "修复前不是完整代码，无从比较")
    before = scope_of(state.get("code") or "", ctx)
    if before is None:
        return Verdict("reviewer.scope", NOT_CHECKED, "修复前的代码无法解析，无从比较")
    after = scope_of(upd.get("code") or "", ctx)
    if after is None:
        return Verdict("reviewer.scope", FAIL, "修复后的代码无法解析")
    (c0, miss0, f0), (c1, _miss1, f1) = before, after
    added, removed = c1 - c0, c0 - c1
    parts, details = [], {}
    if removed or len(added) > len(miss0):
        details["columns_added"], details["columns_removed"] = sorted(added), sorted(removed)
        parts.append("列：" + " ".join([f"+{c}" for c in sorted(added)] + [f"-{c}" for c in sorted(removed)]))
    if f0 != f1:
        details["filters_added"], details["filters_removed"] = sorted(f1 - f0), sorted(f0 - f1)
        parts.append("过滤条件：" + " ".join([f"+[{c}]" for c in sorted(f1 - f0)] + [f"-[{c}]" for c in sorted(f0 - f1)]))
    if parts:
        return Verdict("reviewer.scope", FAIL, "修复改了口径（本步只检出）：" + "；".join(parts), details=details)
    if added:
        return Verdict("reviewer.scope", OK, "把不存在的列改成了：" + "、".join(sorted(added)),
                       details={"fixed_missing": sorted(miss0), "columns_added": sorted(added)})
    return Verdict("reviewer.scope", OK)


# ------------------------------------------------------------------ summarizer
def summarizer_grounding(state: dict, upd: dict, ctx: Context) -> Verdict:
    """证据口径与 service._run_workflow 末尾一致：问题（改写后）、result_text、口径块，改写过时再加原话；
    反问、执行失败、拒答都不核（service 同样不核）。"""
    if state.get("clarify"):
        return Verdict("summarizer.grounding", NOT_CHECKED, "反问，不核数字")
    if state.get("error"):
        return Verdict("summarizer.grounding", NOT_CHECKED, "执行失败的说明，不核数字")
    answer = upd.get("answer") or ""
    from app.core.result import refusal_from_answer
    if not answer or refusal_from_answer(answer) is not None:
        return Verdict("summarizer.grounding", NOT_CHECKED, "拒答或空结论，不核数字")
    from app.core.grounding import unverified_numbers
    question = state.get("question") or ""
    evidence = [question, state.get("result_text") or ""]
    if state.get("metrics_block"):
        evidence.append(state["metrics_block"])
    if ctx.question and ctx.question != question:
        evidence.append(ctx.question)
    # unverified_numbers 在两种情况下返回 [] 但其实什么都没核：结论里没有「有分量」的数字；证据里一个数字都没有
    # （grounding.py:61-64）。这两种落 not_checked。这里复用 grounding 的分词口径，不改 app/core（A 组指纹不动）。
    from app.core.grounding import _significant, _tokens
    if not any(_significant(v, dec, unit, after) for _, v, dec, unit, after in _tokens(answer)):
        return Verdict("summarizer.grounding", NOT_CHECKED, "结论里没有需要核对的数字")
    if not any(_tokens(t) for t in evidence if t):
        return Verdict("summarizer.grounding", NOT_CHECKED, "证据里没有数字，无从核对")
    bad = unverified_numbers(answer, evidence)
    if bad:
        return Verdict("summarizer.grounding", FAIL, "结论里的数字在结果里找不到：" + "、".join(bad),
                       details={"unverified": bad})
    return Verdict("summarizer.grounding", OK)


CONTRACTS = {
    "planner": [planner_length, planner_columns],
    "codegen": [codegen_parse, codegen_columns, codegen_result, codegen_imports, codegen_names],
    "executor": [executor_shape, executor_sanity],
    "reviewer": [reviewer_scope],
    "summarizer": [summarizer_grounding],
}


def check(node: str, state: dict, upd: dict, ctx: Context) -> list[Verdict]:
    return [fn(state or {}, upd or {}, ctx) for fn in CONTRACTS.get(node, [])]
