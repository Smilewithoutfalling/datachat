"""批 4b M2 口径库：校验、检索、渲染、注入位置、拒答补句、档位（docs/roadmap/memory-batch4.md §3.4）。

只用假模型；P8 / state 哈希的对照数据来自 tests/test_memory_p8.py。
"""
import pytest
from langchain_core.messages import AIMessage

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel, prompt_text
from app.memory import metrics as M
from app.memory.budget import estimate_tokens
from app.memory.snapshots import BLOCK_HEAD as HISTORY_HEAD
from app.memory.working_state import STATE_HEAD
from tests.test_core_analyze import wf_model
from tests.test_memory_p8 import BASELINE, HISTORY, STATE_BASELINE, digest, run_all, run_state_all

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)


def note(kind, name, body, unit="", synonyms=""):
    n = M.clean({"kind": kind, "name": name, "body": body, "unit": unit, "synonyms": synonyms})
    return {**n, "sha": M.note_sha(n)}


PROFIT = note("metric", "利润", "units * price - 成本", "元", "净利,净利润")
MARGIN = note("metric", "利润率", "利润 / 销售额", "%", "")
SALES = note("metric", "销售额", "units * price", "元", "营收;收入")
REFUND = note("rule", "退款不计", "退款单不计入销售额")


def tc(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": f"c{i}"}])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)


# ------------------------------------------------------------------ 校验
def test_notes_clean_validation_unit():
    n = M.clean({"kind": "指标", "name": " 利润\x1b ", "body": "收入\r\n- 成本", "unit": "元",
                 "synonyms": "净利；净利润, 净利 ;、"})
    assert n == {"kind": "metric", "name": "利润", "body": "收入\n- 成本", "unit": "元", "synonyms": "净利,净利润"}
    for bad, why in [({"kind": "x", "name": "a", "body": "b"}, "类型"), ({"kind": "rule", "name": " ", "body": "b"}, "名称"),
                     ({"kind": "rule", "name": "a", "body": ""}, "公式"),
                     ({"kind": "rule", "name": "a" * 65, "body": "b"}, "64"),
                     ({"kind": "rule", "name": "a", "body": "b" * 2001}, "2000"),
                     ({"kind": "metric", "name": "a", "body": "b", "unit": "u" * 17}, "16"),
                     ({"kind": "metric", "name": "a", "body": "b", "synonyms": "s" * 201}, "200")]:
        with pytest.raises(M.NoteError, match=why):
            M.clean(bad)


def test_note_sha_definition():
    import hashlib
    n = M.clean({"kind": "metric", "name": "利润", "body": "收入-成本", "unit": "元", "synonyms": "净利"})
    assert M.note_sha(n) == hashlib.sha256("metric|利润|收入-成本|元|净利".encode()).hexdigest()[:12]
    assert M.note_sha({**n, "body": "收入-成本-税"}) != M.note_sha(n)


# ------------------------------------------------------------------ 检索
def test_search_notes_matches_synonym():
    hits = M.search("今年净利润是多少", [PROFIT, SALES, MARGIN])
    assert [n["name"] for _, n in hits][:1] == ["利润"]
    assert M.search("各地区营收", [PROFIT, SALES])[0][1]["name"] == "销售额"


def test_search_longest_match_first():
    """问题里只有「利润率」：「利润」不能被串成命中（规格陷阱）。两个都出现时两个都命中，长的在前。"""
    names = [n["name"] for _, n in M.search("各产品的利润率", [PROFIT, MARGIN])]
    assert names == ["利润率"]
    names = [n["name"] for _, n in M.search("利润和利润率分别是多少", [PROFIT, MARGIN])]
    assert names == ["利润率", "利润"]


def test_search_top5_and_bm25_fill():
    many = [note("metric", f"指标{i}号", f"col{i}", synonyms=f"别名{i}") for i in range(8)]
    hits = M.search("指标1号 指标2号 指标3号 指标4号 指标5号 指标6号", many)
    assert len(hits) == M.TOP_K
    # 没有精确命中时，BM25 在分词上补
    fill = M.search("看看 毛利 情况", [note("metric", "毛利 金额", "a - b")])
    assert [n["name"] for _, n in fill] == ["毛利 金额"]


def test_notes_block_empty_when_no_hit():
    assert M.build_block("各地区销量", [PROFIT, MARGIN]) == ("", [], 0)
    assert M.build_block("各地区销量", []) == ("", [], 0)
    assert M.build_block("各地区销量", None) == ("", [], 0)


def test_rules_always_injected_within_budget():
    """规则不靠检索：问题里一个字都没提，在用的规则也全部进块（§8-9A）。"""
    block, used, omitted = M.build_block("各地区销量", [PROFIT, REFUND])
    assert omitted == 0 and [u["name"] for u in used] == ["退款不计"]
    assert block.startswith(M.BLOCK_HEAD) and block.endswith(M.BLOCK_TAIL)
    assert "规则：\n- 规则「退款不计」：退款单不计入销售额" in block and "利润" not in block


def test_render_notes_capped_at_budget():
    """超过 2000 token 按得分从低到高丢：先丢 BM25 补进来的指标、再丢规则，精确命中的指标最后丢；末尾写已省略。"""
    big_rules = [note("rule", f"规则{i}", "长" * 1500) for i in range(4)]
    block, used, omitted = M.build_block("利润是多少", [PROFIT] + big_rules)
    assert estimate_tokens(block) <= 2000
    assert omitted >= 1 and M.OMITTED.format(n=omitted) in block
    assert used[0]["name"] == "利润" and len(used) == 5 - omitted
    assert block.index("- 利润 = ") < block.index("规则：")


def test_render_line_format():
    block, used, _ = M.build_block("利润", [PROFIT])
    assert "- 利润 = units * price - 成本（单位：元；别名：净利、净利润）" in block
    assert used == [{"name": "利润", "sha": PROFIT["sha"]}]


def test_formula_is_never_evaled(tmp_path, monkeypatch, sample_path):
    """body 写恶意代码：原样作为文本返回 / 进 prompt，没有任何副作用；eval / exec 一次都没被调用。"""
    import builtins
    marker = tmp_path / "pwned"
    evil = f"__import__('os').system('touch {marker}')"
    calls = []
    real_eval, real_exec = builtins.eval, builtins.exec
    monkeypatch.setattr(builtins, "eval", lambda *a, **k: (calls.append("eval"), real_eval(*a, **k))[1])
    monkeypatch.setattr(builtins, "exec", lambda *a, **k: (calls.append("exec"), real_exec(*a, **k))[1])
    n = note("metric", "利润", evil)
    block, used, _ = M.build_block("利润", [n])
    assert evil in block and used[0]["sha"] == n["sha"]
    monkeypatch.setattr(builtins, "eval", real_eval)
    monkeypatch.setattr(builtins, "exec", real_exec)
    assert calls == [] and not marker.exists()
    # 走完整分析：只进 system 文本，沙箱只执行模型给的代码
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    r = analyze(sample_path, "利润是多少", agent="react", chat_model=m, llm_config=FAST, memory_mode="state",
                dataset_notes=[n])
    assert r.ok and evil in m.calls[0][0].content and not marker.exists()


# ------------------------------------------------------------------ 注入
def test_notes_block_position_in_react_system(sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    r = analyze(sample_path, "利润是多少", agent="react", chat_model=m, llm_config=FAST, history=HISTORY,
                memory_mode="state", dataset_notes=[PROFIT, REFUND])
    sys_text = m.calls[0][0].content
    i_schema, i_notes = sys_text.index("数据表结构："), sys_text.index(M.BLOCK_HEAD)
    i_hist, i_dict = sys_text.index(HISTORY_HEAD), sys_text.index("与本轮问题相关的字段说明")
    assert i_schema < i_notes < i_hist < i_dict          # 表结构 > 口径 > 记忆块 > 字段说明
    assert r.memory_notes == [{"name": "利润", "sha": PROFIT["sha"]}, {"name": "退款不计", "sha": REFUND["sha"]}]
    assert r.to_record()["memory_notes"] == r.memory_notes


def test_refusal_line_only_with_notes(sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    analyze(sample_path, "利润是多少", agent="react", chat_model=m, llm_config=FAST, memory_mode="state",
            dataset_notes=[PROFIT])
    sys_text = m.calls[0][0].content
    assert M.REACT_REFUSAL_LINE in sys_text
    assert sys_text.index("（不要写成'无法直接回答''无法计算'等其他说法）。") < sys_text.index(M.REACT_REFUSAL_LINE)
    # 有口径但本轮没命中、也没有规则 → 块不出现，补句也不出现
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    analyze(sample_path, "各地区销量", agent="react", chat_model=m, llm_config=FAST, memory_mode="state",
            dataset_notes=[PROFIT])
    assert M.REACT_REFUSAL_LINE not in m.calls[0][0].content and M.BLOCK_HEAD not in m.calls[0][0].content


def test_planner_gets_notes_block(sample_path):
    seen = {}
    m = wf_model(["result = 1"])
    inner = m.responder

    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            seen["planner"] = t
        elif "写一段 pandas 代码" in t:
            seen["codegen"] = t
        return inner(messages)
    m.responder = respond
    hist = [("华北卖了多少", "华北 540 件", "result = df[df.region == '华北']['units'].sum()")]
    r = analyze(sample_path, "利润是多少", chat_model=m, llm_config=FAST, history=hist, memory_mode="state",
                dataset_notes=[PROFIT])
    p = seen["planner"]
    assert r.ok and M.BLOCK_HEAD in p and M.PLANNER_REFUSAL_LINE in p
    assert p.index(M.BLOCK_HEAD) < p.index(STATE_HEAD) < p.index("相关字段说明（来自数据字典）：")
    assert p.endswith(M.PLANNER_REFUSAL_LINE)
    assert M.BLOCK_HEAD not in seen["codegen"]          # 只给 planner（规格陷阱：别一次把 codegen 都改了）


def test_planner_unchanged_without_notes():
    from app.nodes import planner

    class Echo:
        def invoke(self, msg):
            return msg
    base = {"schema": "S", "question": "Q", "field_notes": "F"}
    cfg = {"configurable": {"llm": Echo()}}
    plain = planner.plan(base, cfg)["plan"]
    assert planner.plan({**base, "metrics_block": ""}, cfg)["plan"] == plain
    with_state = planner.plan({**base, "memory_state": "ST"}, cfg)["plan"]
    assert with_state == plain.replace("\n\n相关字段说明", "\n\nST\n\n相关字段说明", 1)
    both = planner.plan({**base, "memory_state": "ST", "metrics_block": "MB"}, cfg)["plan"]
    assert both == plain.replace("\n\n相关字段说明", "\n\nMB\n\nST\n\n相关字段说明", 1) + "\n" + M.PLANNER_REFUSAL_LINE


def test_notes_not_injected_when_off(sample_path):
    """off：传了口径也什么都不变（P8），memory_notes 为 []。"""
    got, results = run_all(sample_path, dataset_notes=[PROFIT, REFUND])
    assert got == BASELINE
    assert all(r.memory_notes == [] and r.to_record()["memory_notes"] == [] for r in results.values())


def test_state_hash_unchanged_without_notes(sample_path, monkeypatch):
    """硬规则 3：state、没有口径（None / []）、没开改写 → 与 f39753c 逐字节一致。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    for notes in (None, []):
        got, results = run_state_all(sample_path, dataset_notes=notes)
        assert got == STATE_BASELINE
        assert all(r.memory_notes == [] for r in results.values())


def test_state_with_notes_changes_prompt(sample_path, monkeypatch):
    """反面：有口径命中时 state 的 prompt 必须变（不然说明没注入）；只在规则存在时 react_single 也变。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    got, _ = run_state_all(sample_path, dataset_notes=[REFUND])
    assert all(got[k] != STATE_BASELINE[k] for k in STATE_BASELINE)


def test_notes_trimmed_reported(sample_path):
    big_rules = [note("rule", f"规则{i}", "长" * 1500) for i in range(4)]
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    r = analyze(sample_path, "利润", agent="react", chat_model=m, llm_config=FAST, memory_mode="state",
                dataset_notes=[PROFIT] + big_rules)
    assert "notes" in r.memory_trimmed and len(r.memory_notes) < 5


def test_numbers_in_notes_count_as_evidence(sample_path):
    """口径里写的数字（税率 13%）被结论复述时不算编出来的。"""
    tax = note("rule", "含税", "金额一律按 13% 税率含税")
    m = ScriptedChatModel(replies=[tc("result = 1685"), "总销量 1685，金额按 13% 含税"], calls=[])
    r = analyze(sample_path, "总销量", agent="react", chat_model=m, llm_config=FAST, memory_mode="state",
                dataset_notes=[tax])
    assert r.ok and r.unverified_numbers == []


# ------------------------------------------------------------------ 反向回归：有口径但缺字段，仍然拒答（闸门 m10 一字不动）
REFUSAL_RULE = ("问题里的指标（如利润、毛利、成本、年龄、性别）在表里没有对应字段、也不能按通行定义由现有字段算出时，"
                "就属于回答不了，不要自己给指标另下定义")


def test_refusal_still_holds_when_note_uses_missing_field(sample_path):
    """sample.csv 没有成本列，口径写「利润 = units * price - cost」：原拒答规则一字不少、另补一句，
    模型按契约拒答时结果就是拒答（不因为有口径而被当成可以算）。"""
    m = ScriptedChatModel(replies=[tc("result = '无法回答：数据中没有成本字段'"), "无法回答：数据中没有成本字段"], calls=[])
    r = analyze(sample_path, "各产品的利润分别是多少？", agent="react", chat_model=m, llm_config=FAST,
                memory_mode="state", dataset_notes=[PROFIT])
    sys_text = m.calls[0][0].content
    assert REFUSAL_RULE in sys_text and M.REACT_REFUSAL_LINE in sys_text and "units * price - 成本" in sys_text
    assert r.ok and r.result_text.startswith("无法回答") and r.answer.startswith("无法回答")
    assert r.memory_notes == [{"name": "利润", "sha": PROFIT["sha"]}] and r.unverified_numbers == []


def test_refusal_still_holds_in_workflow_with_note(sample_path):
    seen = {}

    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            seen["planner"] = t
            return "数据不足以回答：表里没有成本字段"
        if "写一段 pandas 代码" in t:
            return "result = '无法回答：数据中没有成本字段'"
        return "无法回答：数据中没有成本字段"
    m = ScriptedChatModel(responder=respond, calls=[])
    r = analyze(sample_path, "各产品的利润分别是多少？", chat_model=m, llm_config=FAST, memory_mode="state",
                dataset_notes=[PROFIT])
    p = seen["planner"]
    assert "若表里没有回答问题所需的字段或信息，直接写明\"数据不足以回答\"以及缺少什么，不要用其他字段替代。" in p
    assert M.PLANNER_REFUSAL_LINE in p
    assert r.ok and r.result_text.startswith("无法回答") and r.memory_notes[0]["name"] == "利润"


def test_gate_m10_untouched():
    """闸门 m10 一个字不动（方案 §1-1）：仍是拒答题、题面不变。"""
    from scripts.gate.questions import QUESTIONS
    m10 = [q for q in QUESTIONS if q["id"] == "m10"]
    assert m10 == [{"id": "m10", "group": "multi", "category": "拒答", "dataset": "data/gate/olist",
                    "expect_refusal": True, "question": "各商品类别的利润分别是多少？"}]
