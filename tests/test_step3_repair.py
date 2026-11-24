"""阶段 7.5 第 3 步修复回路（docs/roadmap/phase75-step3.md）：S3-1 能力注入、S3-2 口径闸、S3-3 REPLAN 边。

fake_llm 走真 HTTP 的场景测试在 tests/test_fake_llm.py（replan-scope / replan-exhaust / replan-twice / 超预算）；
这里是单元测试和脚本化假模型（ScriptedChatModel）跑的图测试。
"""
import datetime as dt
import re

import pandas as pd
import pytest

from app import graph as G
from app.assess import contracts as C
from app.assess import replay as rp
from app.assess import snapshot as snap
from app.core import LLMConfig, analyze, analyze_stream
from app.core.llm import LLMClient, UsageTracker
from app.core.testing import ScriptedChatModel, prompt_text
from app.nodes import codegen, planner, reviewer
from app.nodes.summarizer import REPLAN_FAILED_PREFIX
from app.tools import code_scope as S
from app.tools.sandbox_caps import CAPS, PROMPT_FORBIDDEN_EXAMPLES, prompt_lines, prompt_vars

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=0)
COLS = {"": ["date", "region", "product", "units", "price"]}


# =============================================================== S3-1 能力注入
def test_prompt_imports_is_subset_without_private_and_runtime_only():
    pi = CAPS.prompt_imports
    assert set(pi) <= CAPS.allowed_imports and len(set(pi)) == len(pi)
    assert not any(n.startswith("_") for n in pi)
    assert not {"time", "locale", "warnings"} & set(pi)
    # 其余 allowed_imports 全部列出（只去掉上面两类）
    assert set(pi) == {n for n in CAPS.allowed_imports if not n.startswith("_")} - {"time", "locale", "warnings"}


@pytest.mark.parametrize("multi", [False, True])
def test_prompt_lines_names_all_come_from_caps(multi):
    text = prompt_lines(multi)
    lines = text.split("\n")
    assert len(lines) == 3 and all(ln.startswith("- ") for ln in lines)
    # 第一句：已就绪变量（括号里是说明，名字本身反查 CAPS）
    vars_part = re.search(r"已就绪的变量：(.*?)。", lines[0]).group(1)
    names = [re.sub(r"（.*?）", "", x) for x in vars_part.split("、")]
    assert tuple(names) == prompt_vars(multi)
    assert set(names) <= CAPS.injected_names(multi) and CAPS.result_var not in names
    other = CAPS.single_data_vars if multi else CAPS.multi_data_vars
    assert not set(names) & set(other)                     # 多表不出 df，单表不出 dfs
    # 第二句：可以 import 的包 = prompt_imports，且注明只能用这些
    pkgs = re.search(r"可以 import 的包：(.*?)；", lines[1]).group(1).split("、")
    assert tuple(pkgs) == CAPS.prompt_imports and set(pkgs) <= CAPS.allowed_imports
    assert "只能用这些" in lines[1]
    # 第三句：不给的内建 = 固定示例子集 + 「等」
    shown = re.search(r"没有 (.*?) 等内置函数", lines[2]).group(1).split(" / ")
    assert tuple(shown) == PROMPT_FORBIDDEN_EXAMPLES
    for n in shown:
        assert n in CAPS.forbidden_builtins or n == "__import__"
    assert set(PROMPT_FORBIDDEN_EXAMPLES) >= {"globals", "locals", "eval", "exec", "open", "getattr", "__import__"}


def test_prompt_lines_pinned_text():
    """逐字钉住单表渲染结果：改 CAPS 或渲染措辞都要回来改这里（并重立 P8 哈希）。"""
    assert prompt_lines(False) == (
        "- 已就绪的变量：df（数据表）、pd（pandas）、np（numpy）、plt（matplotlib.pyplot）、chart（出图函数，见绘图要求）、"
        "chart_path（图表文件路径）。直接使用，无需 import；df 等数据变量一定已就绪，不要判断变量是否存在。\n"
        "- 可以 import 的包：numpy、pandas、matplotlib、math、statistics、datetime、calendar、re、collections、itertools、"
        "functools、decimal、json；只能用这些，导入其他库会被沙箱拒绝。\n"
        "- 代码在受限沙箱里执行：没有 globals / locals / eval / exec / open / getattr / __import__ 等内置函数。")


class _Capture:
    """最小的 node_llm 替身：记下 prompt，回一段固定文本。"""
    def __init__(self, reply="result = 1"):
        self.prompts, self.reply = [], reply

    def invoke_checked(self, prompt):
        self.prompts.append(prompt)
        return self.reply, False

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def _rendered(monkeypatch, multi=False):
    from app.tools.dataset import access_rule, review_access_rule
    data = {"a": pd.DataFrame({"x": [1]}), "b": pd.DataFrame({"y": [1]})} if multi else pd.DataFrame({"x": [1]})
    st = {"schema": "s", "question": "q", "plan": "p", "code": "result = 1", "error": "E",
          "data_access": access_rule(data), "data_access_review": review_access_rule(data)}
    cap = _Capture()
    monkeypatch.setattr(codegen, "node_llm", lambda cfg: cap)
    monkeypatch.setattr(reviewer, "node_llm", lambda cfg: cap)
    codegen.generate_code(st)
    reviewer.review_and_fix(st)
    return cap.prompts


OLD_HANDWRITTEN = (
    "pd（pandas）、np（numpy）、plt（matplotlib.pyplot）、chart（出图函数，见绘图要求）已就绪，无需 import；不要导入其他库。",
    "pd、np、plt、chart 已就绪，无需 import，不要导入其他库。",
    "没有 globals / locals / eval / exec / open 等内置函数。",
    "不要导入其他库",
)


@pytest.mark.parametrize("multi", [False, True])
def test_codegen_and_reviewer_use_rendered_lines_not_handwritten(monkeypatch, multi):
    for p in _rendered(monkeypatch, multi):
        assert prompt_lines(multi) in p
        for old in OLD_HANDWRITTEN:
            assert old not in p
        assert f"变量 {CAPS.result_var}" in p or f"赋给 {CAPS.result_var}" in p
    for tpl in (codegen._PROMPT, reviewer._PROMPT):
        for old in OLD_HANDWRITTEN:
            assert old not in tpl
        assert "import" not in tpl.split("{chart_guide}")[0].replace("{sandbox_lines}", "")   # 模板里不再手写包名清单


def test_rendered_codegen_prompt_is_stable(monkeypatch):
    a, b = _rendered(monkeypatch), _rendered(monkeypatch)
    assert a == b


# =============================================================== S3-2 口径闸（判定）
def _cmp(before, after, empty=False, cols=COLS, multi=False):
    return S.compare_scope(before, after, cols, multi, empty_before=empty)


def test_compare_scope_rejects_column_filter_denominator_changes():
    assert _cmp("result = df['units'].sum()", "result = (df['units'] * df['price']).sum()").changed       # 加真实列
    assert _cmp("result = df.groupby('region')['units'].sum()", "result = df['units'].sum()").changed  # 删真实列
    assert _cmp("result = df[df['region'] == '华东']['units'].sum()", "result = df['units'].sum()").changed  # 删过滤
    chk = _cmp("result = df[df.units > 0].units.mean()", "result = df.units.sum() / len(df)")        # 换分母
    assert chk.changed and "过滤条件" in chk.summary()
    chk = _cmp("result = df[df['region'] == '华东']['units'].sum()", "result = df[df['region'] == '华东区']['units'].sum()")
    assert chk.changed and chk.details["filters_added"] == ["region == '华东区'"]                      # 非空结果下换字面量


def test_compare_scope_allows_typo_fix_and_literal_swap_on_empty():
    chk = _cmp("result = df.groupby('regin')['units'].sum()", "result = df.groupby('region')['units'].sum()")
    assert chk.status == S.SCOPE_OK and chk.details["columns_added"] == ["region"]
    chk = _cmp("result = df[df['region'] == '华东']['units'].sum()",
               "result = df[df['region'] == '华东区']['units'].sum()", empty=True)
    assert chk.status == S.SCOPE_OK and chk.details["literal_swaps"] == [["region == '华东'", "region == '华东区'"]]
    chk = _cmp("result = df.query('product == \"a\"')['units'].sum()",
               "result = df.query('product == \"A\"')['units'].sum()", empty=True)
    assert chk.status == S.SCOPE_OK


def test_literal_exemption_is_narrow():
    base = "result = df[df['region'] == '华东']['units'].sum()"
    assert _cmp(base, "result = df[df['region'] != '华东区']['units'].sum()", empty=True).changed      # 换了运算符
    assert _cmp(base, "result = df[df['product'] == '华东区']['units'].sum()", empty=True).changed     # 换了列
    assert _cmp(base, "result = df[(df['region'] == '华东区') & (df.units > 0)]['units'].sum()", empty=True).changed  # 多一条
    assert _cmp(base, "result = df['units'].sum()", empty=True).changed                              # 删条件
    assert _cmp(base, "result = df[df['region'] == '华东区']['price'].sum()", empty=True).changed      # 同时换了指标列
    assert _cmp("result = df[df.region.isna()]['units'].sum()", "result = df[df.region.notna()]['units'].sum()",
                empty=True).changed                                                                   # 没有比较值的条件不豁免


def test_compare_scope_parse_and_not_code():
    assert _cmp("按地区，求和", "result = 1").status == S.SCOPE_NOT_CHECKED
    assert _cmp("result = 1", "result = (").status == S.SCOPE_UNPARSED_AFTER
    assert S.compare_scope("x", "y", COLS, False, not_code=True).status == S.SCOPE_NOT_CHECKED
    assert S.compare_scope("x", "y", COLS, False, truncated=True).status == S.SCOPE_NOT_CHECKED


def test_assess_reviewer_scope_keeps_step1_semantics_without_literal_exemption():
    """评估层 reviewer.scope 不开字面量豁免：产品闸放行的「空结果下换字面量」在评估层仍记 fail（看得出闸放过了什么）。"""
    ctx = C.Context(columns=COLS)
    v = C.reviewer_scope({"code": "result = df[df['region'] == '华东']['units'].sum()", "sanity_issue": "结果是空的（0 行）"},
                         {"code": "result = df[df['region'] == '华东区']['units'].sum()"}, ctx)
    assert v.status == C.FAIL


# =============================================================== S3-2 口径闸（图里的节点）
def _gate(before, after, **st):
    df = pd.read_csv("data/sample.csv")
    state = {"code_before_fix": before, "code": after, **st}
    return G.scope_gate(state, {"configurable": {"df": df}})


def test_scope_gate_rolls_back_rejected_fix():
    out = _gate("result = df['units'].sum()", "result = df['price'].sum()")
    assert out["code"] == "result = df['units'].sum()" and "列" in out["scope_rejected"]


def test_scope_gate_passes_unparsed_after_truncated_and_no_base():
    assert _gate("result = df['units'].sum()", "result = (") == {"scope_rejected": ""}       # 交给 executor 报错
    assert _gate("result = df['units'].sum()", "result = df['price'].sum()", truncated=True) == {"scope_rejected": ""}
    assert _gate("", "result = df['price'].sum()") == {"scope_rejected": ""}                 # 修复前不是完整代码
    assert _gate("按地区，求和", "result = df['price'].sum()") == {"scope_rejected": ""}       # 修复前解析不了


def test_scope_gate_literal_exemption_only_when_empty():
    a, b = "result = df[df['region'] == '东'].units.sum()", "result = df[df['region'] == '华东'].units.sum()"
    assert _gate(a, b, sanity_issue="结果是空的（0 行）") == {"scope_rejected": ""}
    assert _gate(a, b, sanity_issue="result['x']：结果是空的（0 行）") == {"scope_rejected": ""}
    assert _gate(a, b, sanity_issue="结果里的值全是空值（NaN）")["scope_rejected"]
    assert _gate(a, b)["scope_rejected"]


def test_reviewer_records_code_before_fix(monkeypatch):
    cap = _Capture("result = 2")
    monkeypatch.setattr(reviewer, "node_llm", lambda cfg: cap)
    st = {"schema": "s", "question": "q", "code": "result = 1", "error": "E"}
    assert reviewer.review_and_fix(st)["code_before_fix"] == "result = 1"
    assert reviewer.review_and_fix({**st, "not_code": True})["code_before_fix"] == ""
    assert reviewer.review_and_fix({**st, "truncated": True})["code_before_fix"] == ""


# =============================================================== S3-3 路由
class _T:
    def __init__(self, over):
        self.over, self.hit = over, False

    def over_budget(self):
        return self.over

    def mark_budget_hit(self):
        self.hit = True


def _cfg(over=False):
    t = _T(over)

    class L:
        tracker = t
    return {"configurable": {"llm": L()}}, t


@pytest.mark.parametrize("state,expected", [
    ({"error": "KeyError", "attempts": 0, "max_attempts": 3}, "fix"),                 # 第一次报错 / 列缺失 → reviewer
    ({"error": "x", "attempts": 3, "max_attempts": 3}, "replan"),                     # 次数用尽仍报错
    ({"error": "", "sanity_issue": "结果是空的（0 行）", "attempts": 3, "max_attempts": 3}, "replan"),   # 用尽仍可疑
    ({"error": "x", "attempts": 3, "max_attempts": 3, "replanned": True}, "done"),     # 每轮最多一次
    ({"error": "x", "attempts": 0, "max_attempts": 0}, "done"),                       # reviewer 一次没修过：第一次报错不 replan
    ({"error": "", "attempts": 2, "max_attempts": 3}, "done"),
])
def test_route_after_exec_replan(state, expected):
    cfg, _ = _cfg()
    assert G._route_after_exec(state, cfg) == expected


def test_no_replan_when_over_budget():
    cfg, t = _cfg(over=True)
    assert G._route_after_exec({"error": "x", "attempts": 3, "max_attempts": 3}, cfg) == "done" and t.hit
    cfg, t = _cfg(over=True)
    assert G._route_after_gate({"scope_rejected": "列：+price"}, cfg) == "done" and t.hit


def test_route_after_gate():
    cfg, _ = _cfg()
    assert G._route_after_gate({"scope_rejected": ""}, cfg) == "run"
    assert G._route_after_gate({"scope_rejected": "列：+price"}, cfg) == "replan"
    assert G._route_after_gate({"scope_rejected": "列：+price", "replanned": True}, cfg) == "done"


# =============================================================== S3-3 replan 节点
def test_replan_prompt_appends_last_attempt_and_forbids_clarify(monkeypatch):
    cap = _Capture("CLARIFY: 您想按销售额还是订单数看？")
    monkeypatch.setattr(planner, "node_llm", lambda cfg: cap)
    long_code = "x = 1\n" * 1000
    st = {"schema": "s", "question": "帮我看看这批数据", "plan": "旧计划：按地区求和", "code": long_code,
          "error": "Traceback\n...\nKeyError: 'nope'", "attempts": 3, "max_attempts": 3}
    out = planner.replan(st)
    p = cap.prompts[0]
    assert p.startswith(planner._prompt(st))                                  # 同一份 planner prompt，末尾追加
    tail = p[len(planner._prompt(st)):]
    assert planner.REPLAN_MARK in tail and "旧计划：按地区求和" in tail and "KeyError: 'nope'" in tail
    assert "已截断" in tail and len(tail) < planner.REPLAN_CODE_CHARS + 1500
    assert "换一条思路" in tail and "口径保持不变" in tail
    # may_clarify 强制为 False：模型反问也不短路，换成可执行的兜底计划
    assert out["clarify"] == "" and out["plan"] == planner.VETO_PLAN
    assert out["replanned"] is True and out["replan_reason"].startswith("执行报错")
    assert out["max_attempts"] == 4 and "attempts" not in out             # reviewer 预算 1 次；attempts 不清零


def test_replan_reason_priority():
    assert planner.replan_reason({"scope_rejected": "列：+price", "error": "E"}).startswith("修复改了口径")
    assert planner.replan_reason({"error": "E"}) == "执行报错：E"
    assert planner.replan_reason({"sanity_issue": "结果是空的（0 行）"}).startswith("代码执行成功，但结果可疑")


# =============================================================== 图测试（脚本化假模型）
def _wf(codes, fixes, plan="计划", replan_plan="新计划", answer="结论"):
    codes, fixes = list(codes), list(fixes)
    seen = []

    def respond(messages):
        t = prompt_text(messages)
        seen.append(t)
        if "数据分析规划助手" in t:
            return replan_plan if planner.REPLAN_MARK in t else plan
        if "请修正它" in t:
            return fixes.pop(0)
        if "写一段 pandas 代码" in t:
            return codes.pop(0)
        return answer
    return ScriptedChatModel(responder=respond, calls=[]), seen


def _names(r):
    return [s.name for s in r.steps if s.name != "load"]       # 第一步 load 是读数据，不是图节点


def test_reviewer_scope_change_goes_to_replan_not_executor(sample_path):
    m, seen = _wf(["result = df['nope'].sum()", "result = int(df['units'].sum())"],
                  ["result = int(df[df['region'] == '华东']['units'].sum())"])
    evs = list(analyze_stream(sample_path, "总销量", chat_model=m, llm_config=FAST))
    r = evs[-1].result
    names = _names(r)
    assert names[names.index("reviewer") + 1:names.index("reviewer") + 3] == ["scope_gate", "replan"]
    assert names.count("executor") == 2                                      # 被拒的修复没有执行
    assert r.ok and r.result == 1685 and r.plan == "新计划" and r.attempts == 1
    plans = [e.data for e in evs if e.type == "plan"]
    assert plans == [{"text": "计划"}, {"text": "新计划", "source": "replan"}]
    replan_prompt = next(t for t in seen if planner.REPLAN_MARK in t)
    assert "修复改了口径，已拒收" in replan_prompt and "region == '华东'" in replan_prompt


def test_rejected_fix_keeps_pre_fix_result_when_cannot_replan(sample_path, monkeypatch):
    """可疑（全 NaN）→ reviewer 改了口径 → 拒收；预算不够 replan → 带着修复前的结果去总结，被拒的代码没执行。"""
    nan_code = "result = df['units'].where(df['units'] < 0).mean()"
    m, _ = _wf([nan_code], ["result = df['price'].mean()"])
    monkeypatch.setattr(UsageTracker, "over_budget", lambda self: self.usage.calls >= 3)
    r = analyze(sample_path, "平均销量", chat_model=m, llm_config=FAST)
    assert _names(r) == ["planner", "codegen", "executor", "reviewer", "scope_gate", "summarizer"]
    assert r.code == nan_code and r.executed and pd.isna(r.result) and r.sanity_issue
    assert r.usage.budget_hit


def test_literal_swap_on_empty_result_is_executed_not_rejected(sample_path):
    """N9 形态：筛选值写错 → 空结果 → reviewer 只换比较值 → 放行执行，不 replan。"""
    m, _ = _wf(["result = df[df['region'] == '华东区']"], ["result = df[df['region'] == '华东']"])
    r = analyze(sample_path, "华东的记录", chat_model=m, llm_config=FAST)
    assert "replan" not in _names(r) and "scope_gate" not in _names(r)    # 放行的闸不进报告
    assert r.ok and len(r.result) > 0


def test_exhausted_then_replan_then_success_and_once_only(sample_path):
    bad = "result = df['nope']"
    m, _ = _wf([bad, "result = int(df['units'].sum())"], [bad] * 3)
    r = analyze(sample_path, "总销量", chat_model=m, llm_config=FAST)
    assert r.ok and r.result == 1685 and _names(r).count("replan") == 1 and r.attempts == 3
    m, _ = _wf([bad, bad], [bad] * 4)
    r = analyze(sample_path, "总销量", chat_model=m, llm_config=FAST)
    assert not r.ok and _names(r).count("replan") == 1 and r.attempts == 4
    assert r.error.startswith(REPLAN_FAILED_PREFIX) and "KeyError" in r.error
    assert len(m.calls) == 9


def test_first_error_with_missing_column_goes_to_reviewer_not_replan(sample_path):
    m, _ = _wf(["result = df.groupby('regin')['units'].sum()"], ["result = df.groupby('region')['units'].sum()"])
    r = analyze(sample_path, "各地区总销量", chat_model=m, llm_config=FAST)
    assert _names(r) == ["planner", "codegen", "executor", "reviewer", "executor", "summarizer"]
    assert r.ok


# =============================================================== 快照 / 契约 / 回放
def test_snapshot_replan_node_checked_by_planner_contracts_and_replayable(sample_path, tmp_path):
    m, _ = _wf(["result = df['nope'].sum()", "result = int(df['units'].sum())"],
               ["result = int(df[df['region'] == '华东']['units'].sum())"],
               replan_plan="1. 对 `units` 求和")
    analyze(sample_path, "总销量", chat_model=m, llm_config=FAST, snapshot_dir=str(tmp_path), today=dt.date(2024, 3, 9))
    f = snap.list_snapshots(str(tmp_path))[0]
    s = snap.load(f)
    nodes = [r["node"] for r in s.nodes]
    assert nodes == ["planner", "codegen", "executor", "reviewer", "scope_gate", "replan", "codegen", "executor",
                     "summarizer"]
    rec = s.find("replan")
    ctx = C.Context.from_run(s.run)
    vs = C.check("replan", snap.decode_state(rec["input_state"]),
                 {k: snap.decode_value(v) for k, v in rec["updates"].items()}, ctx)
    assert [v.contract for v in vs] == ["planner.length", "planner.columns"]
    assert vs[1].status == C.OK
    assert "replan" in snap.LLM_NODES
    r = rp.replay_node(f, "replan", recorded=True)
    assert r.prompt_match is True and r.output_match is True, r.output_reason
    g = rp.replay_node(f, "scope_gate")
    assert g.output_match is True, g.output_reason
    assert snap.decode_value(s.find("scope_gate")["updates"]["scope_rejected"])
