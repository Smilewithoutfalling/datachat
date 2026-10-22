"""llm_kind：error_kind=llm 时的子类，进 error 事件和 AnalysisResult（phase5 F4 迭代 V2a「S 10-22 已定」第 1 条）。

前端只按 status / error_kind / llm_kind 分支，不看文案（turn.ts:90），所以 429 / 5xx / 鉴权 / 400 的出口靠这个字段区分。
"""
import json
import re
from pathlib import Path

import httpx
import openai
import pytest

from app.core import analyze_stream
from app.core.errors import LLM_KIND_TEXT
from app.core.events import LLM_KINDS, Emitter
from app.core.llm import LLMConfig, classify_error
from app.core.testing import ScriptedChatModel
from tests.test_core_analyze import FAST
from tests.test_t11_errors import _bad_request

REQ = httpx.Request("POST", "http://upstream/v1/chat/completions")


def _status(cls, code):
    return cls(f"Error code: {code}", response=httpx.Response(code, request=REQ), body=None)


CASES = [
    ("timeout", lambda: openai.APITimeoutError(request=REQ)),
    ("connection", lambda: openai.APIConnectionError(request=REQ)),
    ("rate_limit", lambda: _status(openai.RateLimitError, 429)),
    ("auth", lambda: _status(openai.AuthenticationError, 401)),
    ("auth", lambda: _status(openai.PermissionDeniedError, 403)),
    ("bad_request", lambda: _bad_request("too long")),
    ("server", lambda: _status(openai.InternalServerError, 500)),
    ("http_409", lambda: _status(openai.ConflictError, 409)),
]


def run(dataset, *, agent="workflow", model=None, cfg=FAST):
    evs = list(analyze_stream(dataset, "总销量", agent=agent, chat_model=model, llm_config=cfg))
    return evs, evs[-1].result


def fatal(evs):
    errs = [e for e in evs if e.type == "error" and e.data["fatal"]]
    assert len(errs) == 1
    return errs[0].data


@pytest.mark.parametrize("agent", ["workflow", "react"])
@pytest.mark.parametrize("want,make", CASES, ids=[f"{k}-{i}" for i, (k, _) in enumerate(CASES)])
def test_llm_kind_in_result_event_and_record(sample_path, agent, want, make):
    m = ScriptedChatModel(responder=lambda _: make(), calls=[])
    evs, res = run(sample_path, agent=agent, model=m)
    assert res.error_kind == "llm" and res.llm_kind == want
    d = fatal(evs)
    assert d["kind"] == "llm" and d["llm_kind"] == want
    assert evs[-1].to_dict()["data"]["result"]["llm_kind"] == want          # done.result 落库，重放时前端从这里取


def test_no_key_is_its_own_kind(sample_path):
    evs, res = run(sample_path, cfg=LLMConfig(api_key=None))
    assert res.error_kind == "llm" and res.llm_kind == "no_key"
    assert fatal(evs)["llm_kind"] == "no_key"


def test_react_gateway_error_content(sample_path):
    m = ScriptedChatModel(replies=['{"message":"prompt: must contain at least one image."}'] * 3, calls=[])
    evs, res = run(sample_path, agent="react", model=m)
    assert res.error_kind == "llm" and res.llm_kind == "gateway_error"
    nonfatal = [e.data for e in evs if e.type == "error" and not e.data["fatal"]]
    assert nonfatal and all(d["kind"] == "llm" and d["llm_kind"] == "gateway_error" for d in nonfatal)
    assert fatal(evs)["llm_kind"] == "gateway_error"


def test_non_llm_errors_have_null_llm_kind(sample_path, tmp_path):
    bad = tmp_path / "empty.csv"
    bad.write_bytes(b"")
    evs, res = run(str(bad))
    assert res.error_kind == "dataset" and res.llm_kind is None
    assert fatal(evs)["llm_kind"] is None


def test_success_has_null_llm_kind(sample_path):
    from tests.test_core_analyze import wf_model
    evs, res = run(sample_path, model=wf_model(["result = 1"]))
    assert res.ok and res.llm_kind is None and evs[-1].to_dict()["data"]["result"]["llm_kind"] is None


def test_emitter_enforces_llm_kind_iff_llm():
    from app.core.errors import user_error
    em = Emitter("t")
    msg = user_error("text", "x", trace_id="t")
    with pytest.raises(ValueError):
        em.error(msg, "llm", fatal=True)                          # llm 必须带子类
    with pytest.raises(ValueError):
        em.error(msg, "agent", fatal=True, llm_kind="timeout")    # 非 llm 不许带
    assert em.error(msg, "agent", fatal=True).data["llm_kind"] is None


def test_llm_kinds_cover_classifier_and_text_table():
    assert set(LLM_KIND_TEXT) <= set(LLM_KINDS)
    for _, make in CASES:
        k, _ = classify_error(make())
        assert k in LLM_KINDS or re.fullmatch(r"http_\d{3}", k)
    assert classify_error(ValueError("x"))[0] in LLM_KINDS


def test_generated_events_json_lists_llm_kinds():
    p = Path(__file__).resolve().parents[1] / "ui/web/src/generated/events.json"
    assert json.loads(p.read_text(encoding="utf-8"))["llm_kinds"] == list(LLM_KINDS)
