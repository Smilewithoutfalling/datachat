"""M13 第 2 步（DEVLOG [26]）：沙箱里的 chart()、exec 失败丢弃、主进程复检、结果 / 事件 / API 字段。"""
import json

import pandas as pd
import pytest

from app.core import analyze, analyze_stream
from app.core.testing import ScriptedChatModel
from app.tools.charts import MAX_CHARTS, ChartSlot, accept_worker_charts, build_option
from app.tools.sandbox import run_code
from tests.test_core_analyze import FAST, tool_call, wf_model

DF = pd.DataFrame({"r": ["华东", "华北"], "u": [1, 2]})
BAR = "chart('bar', df, x='r', y='u', title='销量')"


# ------------------------------------------------------------------ ChartSlot（进程内）
def test_slot_never_raises_and_returns_none():
    c = ChartSlot()
    assert c("bar", DF, x="r", y="u") is None
    for bad in [(), ("bar",), ("nope", DF), ("bar", DF, "r", "u", None, "t", 9)]:
        assert c(*bad) is None
    assert c("bar", DF, z=1) is None
    assert len(c.specs) == 1 and c.calls == 6 and len(c.errors) == 5 and c.internal == []


def test_slot_internal_error_is_separate(monkeypatch):
    import app.tools.charts as ch
    monkeypatch.setattr(ch, "build_option", lambda *a, **k: 1 / 0)
    c = ChartSlot()
    c("bar", DF, x="r", y="u")
    assert c.errors == [] and c.internal and c.internal[0].startswith("ZeroDivisionError")


def test_builder_bug_is_not_chart_error(monkeypatch):
    import app.tools.charts as ch
    monkeypatch.setattr(ch, "validate_spec", lambda spec: ["假装 builder 产出了禁用键"])
    with pytest.raises(ch.ChartBugError):
        build_option("bar", DF, x="r", y="u")
    c = ChartSlot()
    c("bar", DF, x="r", y="u")
    assert c.errors == [] and len(c.internal) == 1                 # 我们的 bug 单列，不算模型的错


def test_slot_cap():
    c = ChartSlot()
    for _ in range(MAX_CHARTS + 2):
        c("bar", DF, x="r", y="u")
    assert len(c.specs) == MAX_CHARTS and len(c.errors) == 2


def test_finish_discards_on_exec_failure():
    c = ChartSlot()
    c("bar", DF, x="r", y="u")
    out = c.finish(False)
    assert out["charts"] == [] and out["charts_discarded"] == 1


def test_accept_rejects_untrusted_worker_output():
    good = build_option("bar", DF, x="r", y="u")
    evil = json.loads(json.dumps(good))
    evil["option"]["tooltip"]["formatter"] = "<img src=x onerror=alert(1)>"
    res = accept_worker_charts({"charts": [good, evil, "x", None, good, good], "chart_calls": "9",
                                "chart_errors": ["a\x00b" * 1000, 3], "charts_discarded": -1})
    assert res["charts"] == [good]                               # 只看前 4 张；evil / 非 dict 拒绝
    assert len(res["chart_internal_errors"]) == 4                # 超量 1 + 三张复检不过
    assert res["chart_calls"] == 0 and res["charts_discarded"] == 0
    assert "\x00" not in res["chart_errors"][0] and len(res["chart_errors"][0]) <= 500
    assert accept_worker_charts({"charts": "nope"})["charts"] == []


def test_truncated_warning():
    big = pd.DataFrame({"x": [f"k{i}" for i in range(6000)], "y": range(6000)})
    res = accept_worker_charts({"charts": [build_option("bar", big, x="x", y="y", title="大表")]})
    assert res["chart_warnings"] == ["图表「大表」数据点超过 5000，只显示了前面的部分"]


# ------------------------------------------------------------------ 沙箱（子进程）
def _run(code, chart_path):
    cap = {}
    r, png, err = run_code(code, DF, chart_path, capture=cap)
    return r, png, err, cap


def test_sandbox_chart_ok(chart_path):
    r, png, err, cap = _run(BAR + "\nresult = 1", chart_path)
    assert err is None and r == 1 and png is None
    assert len(cap["charts"]) == 1 and cap["charts"][0]["option"]["title"]["text"] == "销量"
    assert cap["chart_calls"] == 1 and cap["chart_errors"] == [] and cap["charts_discarded"] == 0


def test_sandbox_chart_error_does_not_touch_result(chart_path):
    r, _, err, cap = _run("chart('bar', df, x='没有这列')\nresult = 2", chart_path)
    assert err is None and r == 2 and cap["charts"] == [] and "没有这列" in cap["chart_errors"][0]


def test_sandbox_exec_failure_discards_options(chart_path):
    r, png, err, cap = _run(BAR + "\nplt.plot([1]); plt.savefig(chart_path)\nraise ValueError('x')", chart_path)
    assert err and r is None and png is None
    assert cap["charts"] == [] and cap["charts_discarded"] == 1


def test_sandbox_tampered_spec_rejected_in_main_process(chart_path):
    code = BAR + "\nchart.specs[0]['option']['tooltip']['formatter'] = '<img>'\nresult = 3"
    r, _, err, cap = _run(code, chart_path)
    assert err is None and r == 3 and cap["charts"] == []
    assert any("复检未通过" in m for m in cap["chart_internal_errors"])


def test_sandbox_without_capture_still_works(chart_path):
    r, _, err = run_code(BAR + "\nresult = 4", DF, chart_path)
    assert err is None and r == 4


# ------------------------------------------------------------------ analyze / 事件
def test_workflow_result_has_option_items(sample_path):
    code = "s = df.groupby('region', as_index=False)['units'].sum()\nchart('bar', s, x='region', y='units')\nresult = 1"
    res = analyze(sample_path, "画图", chat_model=wf_model([code]), llm_config=FAST)
    assert res.ok and res.chart_calls == 1 and res.chart_path is None
    assert len(res.charts) == 1 and res.charts[0]["png"] is None and res.charts[0]["option"]["kind"] == "bar"
    json.dumps(res.to_record(), ensure_ascii=False, allow_nan=False)


def test_workflow_failed_attempt_discard_is_warned(sample_path):
    bad = "chart('bar', df, x='region', y='units')\nresult = df['nope']"
    good = "chart('bar', df.head(2), x='region', y='units')\nresult = 1"
    evs = list(analyze_stream(sample_path, "画图", chat_model=wf_model([bad], fixes=[good]), llm_config=FAST))
    execs = [e.data for e in evs if e.type == "exec"]
    assert execs[0]["options"] == [] and execs[0]["charts_discarded"] == 1
    assert len(execs[1]["options"]) == 1 and execs[1]["charts_discarded"] == 0
    res = evs[-1].result
    assert res.charts_discarded == 1 and len(res.charts) == 1
    assert any("已丢弃" in w and "成功那次" in w for w in res.warnings)


def test_react_chart_error_reaches_model_and_warnings(sample_path):
    m = ScriptedChatModel(replies=[tool_call("chart('bar', df, x='nope')\nresult = 1"), "好"], calls=[])
    res = analyze(sample_path, "画图", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 1 and res.charts == [] and res.chart_calls == 1
    assert "chart() 未出图" in str(m.calls[-1][-1].content)          # 模型看得到，能改
    assert any(w.startswith("图表未生成") for w in res.warnings)


def test_react_mixed_png_and_option(sample_path):
    code = BAR.replace("df", "df.groupby('region', as_index=False)['units'].sum()").replace("'r'", "'region'").replace("'u'", "'units'")
    code += "\nplt.plot([1, 2]); plt.savefig(chart_path)\nresult = 1"
    m = ScriptedChatModel(replies=[tool_call(code), "好"], calls=[])
    res = analyze(sample_path, "画图", agent="react", chat_model=m, llm_config=FAST)
    assert [bool(c["option"]) for c in res.charts] == [True, False]
    assert res.chart_path == res.charts[1]["png"]
    assert "（已生成 1 张图表：销量）" in str(m.calls[-1][-1].content)


def test_tool_text_unchanged_when_chart_unused(sample_path):
    """没用 chart() 时工具返回给模型的文本与 [26] 之前逐字一致。"""
    m = ScriptedChatModel(replies=[tool_call("result = 1"), "好"], calls=[])
    analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert str(m.calls[-1][-1].content) == "执行成功。result = 1"


# ------------------------------------------------------------------ 第 3 步：提示词与图表冒烟（[27]）
def test_guide_reaches_both_agents(sample_path):
    m = ScriptedChatModel(replies=[tool_call("result = 1"), "好"], calls=[])
    analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    system = str(m.calls[0][0].content)
    assert "chart(kind, df" in system and "plt.savefig(chart_path)" in system
    wf = wf_model(["result = 1"])
    analyze(sample_path, "q", chat_model=wf, llm_config=FAST)
    from app.core.testing import prompt_text
    codegen = [prompt_text(c) for c in wf.calls if "写一段 pandas 代码" in prompt_text(c)][0]
    assert "chart（出图函数" in codegen and "chart(kind, df" in codegen


def test_summarizer_sees_chart_titles(sample_path):
    code = "s = df.groupby('region', as_index=False)['units'].sum()\nchart('bar', s, x='region', y='units', title='各地区销量')\nresult = 1"
    wf = wf_model([code])
    analyze(sample_path, "画图", chat_model=wf, llm_config=FAST)
    from app.core.testing import prompt_text
    assert "已生成 1 张图表：各地区销量" in prompt_text(wf.calls[-1])


def test_react_tool_text_names_chart_titles(sample_path):
    code = "s = df.groupby('region')['units'].sum()\nchart('pie', s, title='占比')\nresult = 1"
    m = ScriptedChatModel(replies=[tool_call(code), "好"], calls=[])
    analyze(sample_path, "画图", agent="react", chat_model=m, llm_config=FAST)
    assert "（已生成 1 张图表：占比）" in str(m.calls[-1][-1].content)


def test_chart_smoke_summary():
    from app.eval.chart_smoke import summarize
    def row(calls=0, plt=False, opt=0, png=0, internal=()):
        return {"chart": {"chart_calls": calls, "used_plt": plt, "drew": bool(calls or plt), "options": opt,
                          "pngs": png, "chart_errors": [], "chart_internal_errors": list(internal),
                          "charts_discarded": 0}}
    rows = [row(), row(calls=1, opt=1), row(plt=True, png=1), row(calls=1), row(plt=True), {"chart": None}]
    s = summarize(rows, list("abcdef"))
    assert s["出图率"] == {"drew": 4, "no_chart": ["d", "e"], "pass": False, "rule": s["出图率"]["rule"]}
    assert s["chart_option"]["called"] == 2 and s["chart_option"]["fail"] == ["d"] and not s["chart_option"]["pass"]
    s = summarize([row(calls=1, opt=1, internal=["x"])], ["a"])
    assert s["出图率"]["pass"] and not s["chart_option"]["pass"] and s["internal_errors"] == ["a"]
    s = summarize([row()], ["a"])                                  # 分母为 0：无样本
    assert s["出图率"]["pass"] is None and s["chart_option"]["pass"] is None


def test_chart_row_detects_plt_in_any_attempt(sample_path):
    from app.eval.chart_smoke import chart_row
    bad = "plt.bar([1], [1])\nresult = df['nope']"
    res = analyze(sample_path, "q", chat_model=wf_model([bad], fixes=["result = 1"]), llm_config=FAST)
    c = chart_row(res)
    assert c["used_plt"] and c["drew"] and c["pngs"] == 0 and c["chart_calls"] == 0
