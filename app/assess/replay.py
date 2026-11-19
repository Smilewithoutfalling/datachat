"""单节点回放（阶段 7.5 第 1 步，phase75-assess.md §2 第 1 步验收 ①②）。

给定快照文件和节点名（可指定第几次出现），用快照里该节点的输入 AgentState 重建 state，只跑这一个节点：

- 模型节点（planner / codegen / reviewer / summarizer）：重建出的 prompt 与原运行比 sha256，**逐字节一致**才算过。
  模型响应两种模式：默认现调模型（LLMConfig.from_env()，需要 Key）；`recorded=True` 用快照里录下的原始响应，
  这时 updates 也必须与原运行一致。网关在 temp 0 下也不确定（BACKLOG N7），所以「输出一致」只对 recorded 模式判。
- executor：从快照记录的数据集路径重新读表（先核对 sha256 指纹，不一致直接报错，不回放），
  执行同一段代码，按 `results_equal` 的口径比结果，报错文本逐字比较。

today：一律取快照 run 行里的 today，**不读当天日期**；快照里没有 today 就拒绝回放。截至本步图里的节点都不读
today（读它的是图之前的问题改写，结果已在 input_state.question 里），这里把它带进 ReplayReport，
后续步骤若有节点开始读 today，从 `ReplayReport.today` / `replay_context` 取，不得自行取日期。
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd

from app.assess import snapshot as snap
from app.assess.snapshot import LLM_NODES, decode_state, decode_value, sha256_text

REL_TOL = 1e-9
ABS_TOL = 1e-12
# executor 每次执行都新开一个图表文件，路径必然不同：只比「有没有图」
_VOLATILE = {"chart_path"}


# ------------------------------------------------------------------ 结果比较
def _is_missing(v) -> bool:
    if v is None or v is pd.NaT or v is pd.NA:
        return True
    try:
        return isinstance(v, (float, np.floating)) and math.isnan(v)
    except TypeError:
        return False


def _num(v) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))


def cell_equal(a, b) -> bool:
    if _is_missing(a) and _is_missing(b):
        return True
    if _is_missing(a) or _is_missing(b):
        return False
    if _num(a) and _num(b):
        a, b = float(a), float(b)
        if math.isinf(a) or math.isinf(b):
            return a == b
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
        return isinstance(a, (bool, np.bool_)) and isinstance(b, (bool, np.bool_)) and bool(a) == bool(b)
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return repr(a) == repr(b)


def _seq_equal(xs, ys, what: str) -> tuple[bool, str]:
    xs, ys = list(xs), list(ys)
    if len(xs) != len(ys):
        return False, f"{what}长度不同：{len(xs)} vs {len(ys)}"
    for i, (x, y) in enumerate(zip(xs, ys)):
        if not cell_equal(x, y):
            return False, f"{what}第 {i} 个不同：{x!r} vs {y!r}"
    return True, ""


def results_equal(a, b) -> tuple[bool, str]:
    """executor 回放的「一致」口径（写死，评估里没有放宽规则）：

    - DataFrame：列名一致（含顺序）、行数一致、索引逐个一致、逐单元格相等；
    - Series：name 一致、长度一致、索引逐个一致、逐值相等；
    - 单元格：数值在 rel 1e-9 / abs 1e-12 容差内相等（math.isclose）；NaN / None / NaT / NA 互相视为相等；
      inf 只与同号 inf 相等；bool 不按数值比；其他类型（字符串、时间戳）要求 ==；
    - **行序必须一致**：executor 是确定性的，同一段代码同一份数据不该换行序，换了就算不一致；
    - dict：键集合与顺序一致、逐值递归比较；list / tuple：长度一致、逐项递归比较；标量按单元格口径。

    返回 (是否一致, 不一致时的一句原因)。"""
    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        if not (isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame)):
            return False, f"类型不同：{type(a).__name__} vs {type(b).__name__}"
        if [str(c) for c in a.columns] != [str(c) for c in b.columns]:
            return False, f"列名不同：{list(a.columns)} vs {list(b.columns)}"
        if len(a) != len(b):
            return False, f"行数不同：{len(a)} vs {len(b)}"
        ok, why = _seq_equal(a.index.tolist(), b.index.tolist(), "索引")
        if not ok:
            return ok, why
        for j, col in enumerate(a.columns):
            ok, why = _seq_equal(a.iloc[:, j].tolist(), b.iloc[:, j].tolist(), f"列 {col!r} ")
            if not ok:
                return ok, why
        return True, ""
    if isinstance(a, pd.Series) or isinstance(b, pd.Series):
        if not (isinstance(a, pd.Series) and isinstance(b, pd.Series)):
            return False, f"类型不同：{type(a).__name__} vs {type(b).__name__}"
        if not cell_equal(a.name, b.name):
            return False, f"Series name 不同：{a.name!r} vs {b.name!r}"
        ok, why = _seq_equal(a.index.tolist(), b.index.tolist(), "索引")
        if not ok:
            return ok, why
        return _seq_equal(a.tolist(), b.tolist(), "值")
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False, f"类型不同：{type(a).__name__} vs {type(b).__name__}"
        if list(a.keys()) != list(b.keys()):
            return False, f"dict 键不同：{list(a)} vs {list(b)}"
        for k in a:
            ok, why = results_equal(a[k], b[k])
            if not ok:
                return False, f"[{k!r}] {why}"
        return True, ""
    if isinstance(a, (list, tuple, np.ndarray, pd.Index)) or isinstance(b, (list, tuple, np.ndarray, pd.Index)):
        xs = list(a) if isinstance(a, (list, tuple, np.ndarray, pd.Index)) else None
        ys = list(b) if isinstance(b, (list, tuple, np.ndarray, pd.Index)) else None
        if xs is None or ys is None or type(a) is not type(b):
            return False, f"类型不同：{type(a).__name__} vs {type(b).__name__}"
        if len(xs) != len(ys):
            return False, f"长度不同：{len(xs)} vs {len(ys)}"
        for i, (x, y) in enumerate(zip(xs, ys)):
            ok, why = results_equal(x, y)
            if not ok:
                return False, f"[{i}] {why}"
        return True, ""
    return (True, "") if cell_equal(a, b) else (False, f"值不同：{a!r} vs {b!r}")


# ------------------------------------------------------------------ 回放
@dataclasses.dataclass
class ReplayReport:
    node: str
    occurrence: int
    today: str
    mode: str                                # recorded / live / exec
    prompt_match: bool | None = None         # 模型节点：重建 prompt 的 sha256 是否与原运行一致；无模型调用时 None
    prompt_sha256: str | None = None
    recorded_prompt_sha256: str | None = None
    output_match: bool | None = None         # recorded / exec 模式判；live 模式 None（模型输出本就不确定）
    output_reason: str = ""
    updates: dict = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.prompt_match is not False and self.output_match is not False


@dataclasses.dataclass(frozen=True)
class ReplayContext:
    """回放时的环境值，全部来自快照 run 行。"""
    today: str
    dataset: object
    encoding: str | None


def replay_context(run: dict) -> ReplayContext:
    today = run.get("today")
    if not today:
        raise ValueError("快照里没有 today，拒绝回放（回放不得取当天日期）")
    ds = run.get("dataset_abs") or run.get("dataset")
    return ReplayContext(today=today, dataset=ds, encoding=run.get("encoding"))


class _PromptCapture:
    def __init__(self, client):
        self.prompts = []
        orig = client.invoke_message

        def invoke_message(prompt):
            self.prompts.append(prompt)
            return orig(prompt)
        client.invoke_message = invoke_message


def _recorded_client(calls: list):
    from langchain_core.messages import AIMessage
    from app.core.llm import LLMClient, LLMConfig
    from app.core.testing import ScriptedChatModel
    replies = [AIMessage(content=c["response"],
                         response_metadata={"finish_reason": "length"} if c.get("truncated") else {})
               for c in calls]
    return LLMClient(LLMConfig(api_key="replay", max_retries=0),
                     model=ScriptedChatModel(replies=replies, calls=[], tokens_per_call=None))


def _live_client():
    from app.core.llm import LLMClient, LLMConfig
    return LLMClient(LLMConfig.from_env())


def load_dataset(ctx: ReplayContext, run: dict):
    """按快照读表；指纹不一致就报错（数据变了，回放没有意义）。"""
    from app.tools.dataset import load_data
    fp = snap.dataset_fingerprint(ctx.dataset)
    want = (run.get("dataset_fingerprint") or {}).get("sha256")
    if want and fp["sha256"] != want:
        raise ValueError(f"数据集指纹与快照不一致（{fp['sha256'][:12]} ≠ {want[:12]}），拒绝回放")
    return load_data(ctx.dataset, ctx.encoding)[0]


def _node_fn(node: str):
    from app.nodes.codegen import generate_code
    from app.nodes.executor import execute
    from app.nodes.planner import plan
    from app.nodes.reviewer import review_and_fix
    from app.nodes.summarizer import summarize
    return {"planner": plan, "codegen": generate_code, "executor": execute,
            "reviewer": review_and_fix, "summarizer": summarize}[node]


def _updates_equal(got: dict, want: dict) -> tuple[bool, str]:
    keys = list(dict.fromkeys(list(want) + list(got)))
    for k in keys:
        if k not in got or k not in want:
            return False, f"updates 键不同：{k!r}"
        a, b = got[k], want[k]
        if k in _VOLATILE:
            if bool(a) != bool(b):
                return False, f"{k} 有无不同：{a!r} vs {b!r}"
            continue
        ok, why = results_equal(a, b)
        if not ok:
            return False, f"{k}：{why}"
    return True, ""


def replay_node(path: str, node: str, occurrence: int = 1, *, recorded: bool = False,
                client=None) -> ReplayReport:
    """只跑快照里的这一个节点。client 只给测试注入（live 模式下代替 LLMConfig.from_env()）。"""
    s = snap.load(path)
    ctx = replay_context(s.run)
    rec = s.find(node, occurrence)
    state = decode_state(rec["input_state"])
    want = {k: decode_value(v) for k, v in (rec.get("updates") or {}).items()}
    fn = _node_fn(node)

    if node in LLM_NODES:
        calls = rec.get("llm_calls") or []
        llm = _recorded_client(calls) if recorded else (client or _live_client())
        cap = _PromptCapture(llm)
        got = fn(state, {"configurable": {"llm": llm}})
        rpt = ReplayReport(node, occurrence, ctx.today, "recorded" if recorded else "live", updates=got)
        if calls or cap.prompts:
            rpt.recorded_prompt_sha256 = calls[0]["prompt_sha256"] if calls else None
            rpt.prompt_sha256 = sha256_text(cap.prompts[0]) if cap.prompts else None
            rpt.prompt_match = rpt.prompt_sha256 == rpt.recorded_prompt_sha256
            if len(cap.prompts) != len(calls):
                rpt.prompt_match = False
        if recorded:
            rpt.output_match, rpt.output_reason = _updates_equal(got, want)
        return rpt

    df = load_dataset(ctx, s.run)
    got = fn(state, {"configurable": {"df": df}})
    rpt = ReplayReport(node, occurrence, ctx.today, "exec", updates=got)
    rpt.output_match, rpt.output_reason = _updates_equal(got, want)
    return rpt
