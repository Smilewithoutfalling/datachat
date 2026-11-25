"""假模型服务（tests/fake_llm.py）自己的测试：解析器严格、认不出就 400、两条链路走真 HTTP 跑通。

真链路那两条也是提示词漂移的守卫：app/nodes/* 或 app/react_agent.py 的提示词一改，假服务认不出步骤 → 400 →
分析失败 → 这里红，而不是让 e2e 在某个场景下静默假绿。"""
import threading
import time

import pytest

from app.core import analyze
from app.core.llm import LLMConfig
from app.core.result import CHART_NONE_WARNING, CHART_PARTIAL_WARNING
from app.tools.charts import KINDS, MAX_POINTS, validate_spec
from tests.fake_llm import (ANSWER, CODE, FAIL_CODES, INJECT_ANSWER, INJECT_COLUMNS, INJECT_ORDER, INJECT_PAYLOADS,
                            INJECT_ROWS,
                            inject_csv, MARK_ANSWER_FAIL, MARK_CODEGEN, MARK_PING, MARK_PLAN, MARK_REACT, PING_REPLY, PLAN,
                            REACT_STEPS, WORKFLOW_STEPS, FakeError, Scenario, handle, make_server, parse_model)

WF_PLAN = [{"role": "user", "content": MARK_PLAN + "……"}]
WF_CODEGEN = [{"role": "user", "content": MARK_CODEGEN + "……"}]
RE_ACT = [{"role": "system", "content": MARK_REACT}, {"role": "user", "content": "q"}]
RE_FINAL = RE_ACT + [{"role": "assistant", "content": "", "tool_calls": []}, {"role": "tool", "content": "15"}]


@pytest.mark.parametrize("name,sc", [
    ("ok", Scenario("ok")),
    ("hang-30s", Scenario("hang", 30)),
    ("hang-5s@codegen", Scenario("hang", 5, "codegen")),
    ("fail-500", Scenario("fail", 500)),
    ("fail-429@final", Scenario("fail", 429, "final")),
    ("slow-2s", Scenario("slow", 2)),
    ("chart-bar", Scenario("chart", chart="bar")),
    ("chart-scatter", Scenario("chart", chart="scatter")),
    ("inject-bar", Scenario("inject", chart="bar")),
    ("inject-pie", Scenario("inject", chart="pie")),
    ("inject-error", Scenario("inject", chart="error")),
])
def test_parse_valid(name, sc):
    assert parse_model(name) == sc


@pytest.mark.parametrize("name", [
    "", "deepseek-chat", "hang-30", "hang30s", "hang-30m", "hang-0s", "hang-601s", "hang", "fail", "fail-500s",
    "fail-418", "ok-1s", "ok@plan", "slow-2s@plan", "hang-5s@codgen", "hang-5s@", "HANG-5s", " ok", "ok ",
    "chart", "chart-", "chart-heatmap", "chart-Bar", "chart-bar@codegen", "chart-bar@act", "chart-bar@", "chart-bar-1s",
    "chart-bar ",
    "inject", "inject-", "inject-heatmap", "inject-Bar", "inject-bar@codegen", "inject-bar@act", "inject-bar@",
    "inject-error@final", "inject-bar-1s", "chart-error",
])
def test_parse_rejects_everything_else(name):
    code, body = handle({"model": name, "messages": WF_PLAN}, sleep=lambda s: pytest.fail("不该睡"))
    assert code == 400 and body["error"]["message"].startswith("[fake_llm]")


def test_unrecognized_prompt_is_400_not_default_script():
    for model in ("ok", "slow-1s", "hang-1s", "fail-500"):
        code, body = handle({"model": model, "messages": [{"role": "user", "content": "随便什么提示词"}]},
                            sleep=lambda s: pytest.fail("认不出时不该先睡"))
        assert code == 400 and "无法识别当前步骤" in body["error"]["message"]


def test_step_from_other_chain_is_400():
    for model, msgs in (("hang-1s@codegen", RE_ACT), ("fail-500@plan", RE_FINAL), ("hang-1s@act", WF_PLAN),
                        ("fail-500@final", WF_CODEGEN)):
        code, body = handle({"model": model, "messages": msgs}, sleep=lambda s: pytest.fail("不该睡"))
        assert code == 400 and "不属于" in body["error"]["message"], model


def test_stream_requests_are_rejected():
    code, body = handle({"model": "ok", "stream": True, "messages": WF_PLAN})
    assert code == 400 and "stream" in body["error"]["message"]


def test_targets_first_call_by_default_and_named_step_otherwise():
    slept = []
    assert handle({"model": "hang-7s", "messages": WF_PLAN}, sleep=slept.append)[0] == 200
    assert handle({"model": "hang-7s", "messages": WF_CODEGEN}, sleep=slept.append)[0] == 200
    assert handle({"model": "hang-7s", "messages": RE_ACT}, sleep=slept.append)[0] == 200
    assert handle({"model": "hang-7s", "messages": RE_FINAL}, sleep=slept.append)[0] == 200
    assert slept == [7, 7]                                            # plan、act 各一次
    slept.clear()
    assert handle({"model": "hang-3s@codegen", "messages": WF_PLAN}, sleep=slept.append)[0] == 200
    assert handle({"model": "hang-3s@codegen", "messages": WF_CODEGEN}, sleep=slept.append)[0] == 200
    assert slept == [3]
    assert handle({"model": "fail-503", "messages": WF_PLAN})[0] == 503
    assert handle({"model": "fail-503", "messages": WF_CODEGEN})[0] == 200
    assert handle({"model": "fail-503@final", "messages": RE_FINAL})[0] == 503
    slept.clear()
    for msgs in (WF_PLAN, WF_CODEGEN, RE_ACT, RE_FINAL):
        handle({"model": "slow-2s", "messages": msgs}, sleep=slept.append)
    assert slept == [2, 2, 2, 2]


def test_same_request_same_response():
    """无状态：同样的 model + 提示词 → 同样的回复（除 id / created）。"""
    strip = lambda b: {k: v for k, v in b.items() if k not in ("id", "created")}  # noqa: E731
    for msgs in (WF_PLAN, WF_CODEGEN, RE_ACT, RE_FINAL, [{"role": "user", "content": MARK_ANSWER_FAIL}]):
        a, b = handle({"model": "ok", "messages": msgs}), handle({"model": "ok", "messages": msgs})
        assert a[0] == b[0] == 200 and strip(a[1]) == strip(b[1])


def test_chart_scenario_only_changes_the_code_steps():
    """chart-<kind>：写代码的那一步（codegen / fix / act）带 chart() 调用，其余步骤与 ok 完全相同；每个 KINDS 都能解析。"""
    assert {parse_model(f"chart-{k}").chart for k in KINDS} == set(KINDS)
    strip = lambda b: {k: v for k, v in b.items() if k not in ("id", "created", "model")}  # noqa: E731
    fix = [{"role": "user", "content": "之前生成的 pandas 代码执行出错了，请修正它……"}]
    for msgs in (WF_PLAN, RE_FINAL, [{"role": "user", "content": MARK_ANSWER_FAIL}]):
        assert strip(handle({"model": "chart-pie", "messages": msgs})[1]) == strip(handle({"model": "ok", "messages": msgs})[1])
    for msgs in (WF_CODEGEN, fix):
        content = handle({"model": "chart-pie", "messages": msgs})[1]["choices"][0]["message"]["content"]
        assert "chart('pie', df, x=cat[0], y=num[0]" in content and CODE in content
    args = handle({"model": "chart-scatter", "messages": RE_ACT})[1]["choices"][0]["message"]["tool_calls"][0]
    assert "chart('scatter', df, x=num[0], y=num[1]" in args["function"]["arguments"]


def test_step_vocabulary_is_closed():
    assert set(WORKFLOW_STEPS) == {"plan", "codegen", "fix", "answer"} and set(REACT_STEPS) == {"act", "final"}
    assert 500 in FAIL_CODES and 401 in FAIL_CODES


# ---------------------------------------------------------------- 真 HTTP、真产品链路
@pytest.fixture(scope="module")
def fake_url():
    srv = make_server()
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def cfg(url, model):
    return LLMConfig(model=model, api_key="fake-key", base_url=url, max_retries=0, timeout=20)


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_ok(agent, fake_url, sample_path):
    r = analyze(sample_path, "有多少行", agent=agent, llm_config=cfg(fake_url, "ok"))
    assert r.ok and r.answer == ANSWER and r.result == 15, (r.error_kind, r.error)
    if agent == "workflow":
        assert r.plan == PLAN and r.usage.calls == 3


@pytest.mark.parametrize("agent,model", [("workflow", "hang-1s@codegen"), ("react", "hang-1s@final")])
def test_real_chain_hang_delays_the_named_call(agent, model, fake_url, sample_path):
    t = time.monotonic()
    r = analyze(sample_path, "有多少行", agent=agent, llm_config=cfg(fake_url, model))
    assert r.ok and time.monotonic() - t >= 1.0


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_fail_loud(agent, fake_url, sample_path):
    """拼错的场景名在真链路上也是立刻失败（400 不重试），不是走默认剧本成功。"""
    r = analyze(sample_path, "有多少行", agent=agent, llm_config=cfg(fake_url, "hang-30"))
    assert not r.ok and r.error_kind == "llm" and "[fake_llm]" in r.error
    # T11 判定表：上游 message 照常透出（[fake_llm] 还在）；行为变化是不再带 "BadRequestError: " 之类的类型名前缀，
    # 末尾追加编号（trace_id 前 8 位）
    assert "Error" not in r.error and r.error.endswith(f"（编号 {r.trace_id[:8]}）")


def test_real_chain_fail_code_goes_through_product_classification(fake_url, sample_path):
    """fail-CODE 在真链路上的语义：500 是可重试的 server 错误（被退避重试，次数可见），401 是 auth 不重试。
    和"认不出 → 400 bad_request 不重试"是两回事：fail-500 本来就是要测重试路径。"""
    c = LLMConfig(model="fail-500@codegen", api_key="k", base_url=fake_url, max_retries=2, timeout=20,
                  backoff_base=0.01, backoff_max=0.02)
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=c)
    # T11 判定表：分类不变（kind=server / auth），界面文案换成中文映射（LLM_KIND_TEXT），内部枚举不再进界面
    assert not r.ok and r.error_kind == "llm" and r.error.startswith("模型服务出错，共尝试 3 次")
    assert r.plan == PLAN                                    # plan 正常，挂在 codegen
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=c.with_(model="fail-401"))
    assert not r.ok and r.error.startswith("鉴权失败，请检查 API Key，共尝试 1 次")


def test_real_chain_slow_delays_every_call(fake_url, sample_path):
    t = time.monotonic()
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=cfg(fake_url, "slow-1s"))
    took = time.monotonic() - t
    assert r.ok and r.usage.calls == 3 and 3.0 <= took < 10.0   # 三次调用各慢 1 秒


@pytest.mark.parametrize("agent", ["workflow", "react"])
@pytest.mark.parametrize("kind", KINDS)
def test_real_chain_chart_kind(agent, kind, fake_url, sample_path):
    """chart-<kind> 走真链路：沙箱里的 chart() 真出图，主进程复检通过，result.charts 里是这一种图。"""
    r = analyze(sample_path, "画个图", agent=agent, llm_config=cfg(fake_url, f"chart-{kind}"))
    assert r.ok and r.result == 15, (r.error_kind, r.error)
    opts = [c["option"] for c in r.charts if c.get("option")]
    assert len(opts) == 1 and opts[0]["kind"] == kind and validate_spec(opts[0]) == []
    assert opts[0]["truncated"] is False and not any("数据点超过" in w for w in r.warnings)


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_chart_matplotlib(agent, fake_url, sample_path):
    """chart-matplotlib（F3 第六步）：不调 chart()，plt 画的图落成 png 项，没有 option 项。"""
    assert parse_model("chart-matplotlib") == Scenario("chart", chart="matplotlib")
    r = analyze(sample_path, "画个图", agent=agent, llm_config=cfg(fake_url, "chart-matplotlib"))
    assert r.ok and r.result == 15, (r.error_kind, r.error)
    assert [bool(c.get("png")) for c in r.charts] == [True] and not any(c.get("option") for c in r.charts)


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_truncated_chart_warns(agent, fake_url, tmp_path):
    """5001 行 → 图截到 5000 点、truncated=true，两条链路的 result.warnings 里都有截断警告（只有一条，不重复）。"""
    p = tmp_path / "big.csv"
    p.write_text("k,v\n" + "".join(f"k{i},{i}\n" for i in range(MAX_POINTS + 1)), encoding="utf-8")
    r = analyze(str(p), "画个图", agent=agent, llm_config=cfg(fake_url, "chart-bar"))
    assert r.ok, (r.error_kind, r.error)
    spec = next(c["option"] for c in r.charts if c.get("option"))
    assert spec["truncated"] is True and len(spec["option"]["series"][0]["data"]) == MAX_POINTS
    want = f"图表「fake bar」数据点超过 {MAX_POINTS}，只显示了前面的部分"
    assert r.warnings.count(want) == 1, r.warnings


# ---------------------------------------------------------------- F3 第二步：注入场景
def test_inject_payloads_fit_and_csv_round_trips_through_pandas():
    """载荷都短于 NAME_MAX（不被截断，攻击串完整到达）；csv.writer 生成的 CSV 用 pandas 读回，列名、单元格逐个等于载荷。"""
    import io

    import pandas as pd

    from app.tools.charts import NAME_MAX
    assert all(len(v) < NAME_MAX for v in INJECT_PAYLOADS.values())
    df = pd.read_csv(io.StringIO(inject_csv()))
    assert list(df.columns) == INJECT_COLUMNS
    assert df.values.tolist() == INJECT_ROWS
    assert set(df.iloc[:, 0]) == set(df.iloc[:, 1]) == set(INJECT_PAYLOADS.values())


def test_inject_scenario_only_changes_code_and_answer():
    strip = lambda b: {k: v for k, v in b.items() if k not in ("id", "created", "model")}  # noqa: E731
    assert strip(handle({"model": "inject-bar", "messages": WF_PLAN})[1]) == strip(handle({"model": "ok", "messages": WF_PLAN})[1])
    ok_answer = [{"role": "user", "content": "根据分析结果，用中文简洁、直接地回答用户问题……"}]
    assert handle({"model": "inject-bar", "messages": ok_answer})[1]["choices"][0]["message"]["content"] == INJECT_ANSWER
    assert handle({"model": "inject-bar", "messages": RE_FINAL})[1]["choices"][0]["message"]["content"] == INJECT_ANSWER
    fail = [{"role": "user", "content": MARK_ANSWER_FAIL}]
    assert strip(handle({"model": "inject-pie", "messages": fail})[1]) == strip(handle({"model": "ok", "messages": fail})[1])
    code = handle({"model": "inject-bar", "messages": WF_CODEGEN})[1]["choices"][0]["message"]["content"]
    assert code.count("chart('bar'") == 2 and repr(INJECT_PAYLOADS["P1"]) in code and CODE in code
    code = handle({"model": "inject-pie", "messages": WF_CODEGEN})[1]["choices"][0]["message"]["content"]
    assert code.count("chart(") == 1
    args = handle({"model": "inject-error", "messages": RE_ACT})[1]["choices"][0]["message"]["tool_calls"][0]
    assert f"x={INJECT_PAYLOADS['P1']!r}" in __import__("json").loads(args["function"]["arguments"])["code"]


@pytest.fixture
def inject_path(tmp_path):
    p = tmp_path / "inject.csv"
    # newline="" 原样写字节：文本模式在 Windows 会把单元格里的 \n 写成 \r\n（P7 在 windows CI 上变成 "上\r 下"）
    p.write_text(inject_csv(), encoding="utf-8", newline="")
    return str(p)


@pytest.mark.parametrize("agent", ["workflow", "react"])
@pytest.mark.parametrize("kind", KINDS)
def test_real_chain_inject_kind(agent, kind, fake_url, inject_path):
    """inject-<kind> 走真链路：载荷经真 builder 进标题、轴名、类目（饼图扇区名）、系列名两种来源（列名 / 单元格值），结论含载荷。"""
    from app.tools.charts import _display_safe
    P = _display_safe(INJECT_PAYLOADS)             # option 里是渲染面规范化之后的串（F3 第三步）；结论原样
    r = analyze(inject_path, "画个图", agent=agent, llm_config=cfg(fake_url, f"inject-{kind}"))
    assert r.ok and r.result == len(INJECT_ROWS), (r.error_kind, r.error)
    assert r.answer == INJECT_ANSWER and all(INJECT_PAYLOADS[k] in r.answer for k in ("P1", "P2", "P3"))
    specs = [c["option"] for c in r.charts if c.get("option")]
    assert all(s["kind"] == kind and validate_spec(s) == [] for s in specs)
    assert specs[0]["option"]["title"]["text"] == P["P1"]
    if kind == "pie":
        assert len(specs) == 1
        assert [d["name"] for d in specs[0]["option"]["series"][0]["data"]] == [P[k] for k in INJECT_ORDER]
        return
    assert len(specs) == 2
    wide, long_ = (s["option"] for s in specs)
    assert long_["title"]["text"] == f"{P['P4']} {P['P5']}"
    assert [s["name"] for s in wide["series"]] == ([P["P2"], P["P3"]])                 # 列名 → series.name
    assert [s["name"] for s in long_["series"]] == [P[k] for k in INJECT_ORDER[1:] + INJECT_ORDER[:1]]  # 单元格值 → series.name
    if kind == "scatter":
        assert wide["xAxis"]["name"] == P["P2"] and long_["yAxis"]["name"] == P["P3"]
    else:
        assert wide["xAxis"]["data"] == [P[k] for k in INJECT_ORDER] and wide["xAxis"]["name"] == P["P4"]
        assert long_["yAxis"]["name"] == P["P2"]


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_inject_error_reaches_model_not_warnings(agent, fake_url, inject_path):
    """inject-error：chart() 传不存在的列名 P1，没有图。P1-17（判定表改动，原名 ..._reaches_warnings）：chart_error 原文
    （带载荷和可用列）只回到模型（chart_errors_shown），给用户的警告是固定文案、不含任何载荷。"""
    r = analyze(inject_path, "画个图", agent=agent, llm_config=cfg(fake_url, "inject-error"))
    assert r.ok and not [c for c in r.charts if c.get("option")], (r.error_kind, r.error)
    assert CHART_NONE_WARNING in r.warnings, r.warnings
    assert not any(p in w for w in r.warnings for p in INJECT_PAYLOADS.values()), r.warnings
    e = r.chart_errors_shown[-1]
    assert INJECT_PAYLOADS["P1"] in e and all(c in e for c in INJECT_COLUMNS), r.chart_errors_shown


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_real_chain_partial_chart_error_reported(agent, fake_url, sample_path):
    """[43] chart-partial：一次成功执行里一张 bar 成功、一张列名错 → 1 张图 + 「另有 1 张图没画出来」（P1-17 起是固定文案）。"""
    r = analyze(sample_path, "画个图", agent=agent, llm_config=cfg(fake_url, "chart-partial"))
    assert r.ok and len([c for c in r.charts if c.get("option")]) == 1, (r.error_kind, r.error)
    w = [x for x in r.warnings if "没画出来" in x]
    # P1-17（判定表改动）：固定文案，列名 __nope__ 不进警告，只回到模型
    assert w == [CHART_PARTIAL_WARNING.format(n=1)] and "__nope__" in r.chart_errors_shown[-1], r.warnings


# ---------------------------------------------------------------- T11：上游回显用户问题（真链路）
ECHO_Q = "请按城市统计二零二五年每个季度的销量并画出柱状图"


@pytest.mark.parametrize("agent", ["workflow", "react"])
@pytest.mark.parametrize("echo", ["echo", "echocut"])
def test_real_chain_upstream_echo_is_stripped(agent, echo, fake_url, sample_path):
    r = analyze(sample_path, ECHO_Q, agent=agent, llm_config=cfg(fake_url, f"fail-{echo}-400"))
    assert not r.ok and r.error_kind == "llm" and "[fake_llm] 按场景返回 400" in r.error, r.error
    assert ECHO_Q[:12] not in r.error and "…" in r.error
    assert r.error.endswith(f"（编号 {r.trace_id[:8]}）")


def test_echo_scenario_parse():
    assert parse_model("fail-echo-400").echo == "echo"
    assert parse_model("fail-echocut-500@codegen") == Scenario("fail", 500, "codegen", echo="echocut")
    with pytest.raises(FakeError):
        parse_model("hang-echo-3s")


# ---------------------------------------------------------------- 设置页「测试连接」的 ping（阶段 5 收尾 C）
PING = [{"role": "user", "content": MARK_PING}]


def test_ping_recognized_and_scenarios_apply():
    code, body = handle({"model": "ok", "messages": PING}, sleep=lambda s: pytest.fail("不该睡"))
    assert code == 200 and body["choices"][0]["message"]["content"] == PING_REPLY
    assert handle({"model": "chart-bar", "messages": PING})[0] == 200
    assert handle({"model": "fail-401", "messages": PING})[0] == 401
    slept = []
    assert handle({"model": "hang-3s", "messages": PING}, sleep=slept.append)[0] == 200 and slept == [3]


def test_ping_is_exact_message_only():
    # 带 @step 的场景对 ping 一律 400；ping 不是子串匹配，多一条消息、多一个字都认不出
    code, body = handle({"model": "fail-401@plan", "messages": PING})
    assert code == 400 and "不属于 ping" in body["error"]["message"]
    for msgs in ([{"role": "user", "content": MARK_PING + " "}], [{"role": "system", "content": "s"}] + PING,
                 [{"role": "system", "content": MARK_PING}]):
        code, body = handle({"model": "ok", "messages": msgs})
        assert code == 400 and "无法识别当前步骤" in body["error"]["message"]
