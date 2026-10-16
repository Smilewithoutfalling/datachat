"""假模型服务（tests/fake_llm.py）自己的测试：解析器严格、认不出就 400、两条链路走真 HTTP 跑通。

真链路那两条也是提示词漂移的守卫：app/nodes/* 或 app/react_agent.py 的提示词一改，假服务认不出步骤 → 400 →
分析失败 → 这里红，而不是让 e2e 在某个场景下静默假绿。"""
import threading
import time

import pytest

from app.core import analyze
from app.core.llm import LLMConfig
from tests.fake_llm import (ANSWER, FAIL_CODES, MARK_ANSWER_FAIL, MARK_CODEGEN, MARK_PLAN, MARK_REACT, PLAN,
                            REACT_STEPS, WORKFLOW_STEPS, Scenario, handle, make_server, parse_model)

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
])
def test_parse_valid(name, sc):
    assert parse_model(name) == sc


@pytest.mark.parametrize("name", [
    "", "deepseek-chat", "hang-30", "hang30s", "hang-30m", "hang-0s", "hang-601s", "hang", "fail", "fail-500s",
    "fail-418", "ok-1s", "ok@plan", "slow-2s@plan", "hang-5s@codgen", "hang-5s@", "HANG-5s", " ok", "ok ",
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


def test_real_chain_fail_code_goes_through_product_classification(fake_url, sample_path):
    """fail-CODE 在真链路上的语义：500 是可重试的 server 错误（被退避重试，次数可见），401 是 auth 不重试。
    和"认不出 → 400 bad_request 不重试"是两回事：fail-500 本来就是要测重试路径。"""
    c = LLMConfig(model="fail-500@codegen", api_key="k", base_url=fake_url, max_retries=2, timeout=20,
                  backoff_base=0.01, backoff_max=0.02)
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=c)
    assert not r.ok and r.error_kind == "llm" and "server" in r.error and "共尝试 3 次" in r.error
    assert r.plan == PLAN                                    # plan 正常，挂在 codegen
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=c.with_(model="fail-401"))
    assert not r.ok and "auth" in r.error and "共尝试 1 次" in r.error


def test_real_chain_slow_delays_every_call(fake_url, sample_path):
    t = time.monotonic()
    r = analyze(sample_path, "有多少行", agent="workflow", llm_config=cfg(fake_url, "slow-1s"))
    took = time.monotonic() - t
    assert r.ok and r.usage.calls == 3 and 3.0 <= took < 10.0   # 三次调用各慢 1 秒
