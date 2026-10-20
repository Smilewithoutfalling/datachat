"""T11 错误文案脱敏：断言跑出来的串，不扫源码（规则见 phase5「T11 错误文案脱敏」）。

每个场景走 analyze_stream 的完整路径，收集所有界面文案（error 事件、done 的 res.error、经 user_error 生成的
Step.error），断言不含异常类型名 / 堆栈 / 路径 / Key / 控制符 / 用户问题回显，并且末尾正好一个编号。
"""
import os
import re

import httpx
import openai
import pytest

from app.core import analyze_stream
from app.core.errors import MAX_LEN, scrub, upstream_message, user_error
from app.core.llm import LLMConfig
from app.core.testing import ScriptedChatModel
from tests.test_core_analyze import FAST, tool_call, wf_model

QUESTION = "请按地区统计二零二五年第三季度每个门店的销售额并画柱状图"   # 26 字
KEY = "sk-abcdef0123456789XYZ"
WIN = r"C:\Users\alice\AppData\Roaming\datachat\datasets\x\sales.csv"
POSIX = "/home/alice/.datachat/datasets/x/sales.csv"
CODE_RE = re.compile(r"（编号 ([0-9a-f]{8})）$")
FORBIDDEN = re.compile(r"Error|Exception|Traceback|[A-Za-z]:\\|/home/|/Users/|sk-[A-Za-z0-9]{8}|"
                       r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
TRACE = "3f9a1c2d" + "0" * 24
# 经 user_error 生成的 Step.error 来自这些步骤；executor / observation 是沙箱 exec 原文，T9 不脱敏
SANITIZED_STEPS = {"load", "dictionary", "retry", "cancel"}


def _bad_request(message, code=400):
    req = httpx.Request("POST", "http://upstream/v1/chat/completions")
    resp = httpx.Response(code, request=req)
    cls = {400: openai.BadRequestError, 401: openai.AuthenticationError}.get(code, openai.APIStatusError)
    return cls(f"Error code: {code} - {{'error': {{'message': {message!r}}}}}", response=resp,
               body={"error": {"message": message, "type": "invalid_request_error"}})


def run(dataset, *, agent="workflow", model=None, question=QUESTION, cfg=FAST):
    evs = list(analyze_stream(dataset, question, agent=agent, chat_model=model, llm_config=cfg,
                              trace_id=TRACE))
    return evs, evs[-1].result


def ui_strings(evs, res):
    out = [e.data["message"] for e in evs if e.type == "error"]
    out += [s.error for s in res.steps if s.error and s.name in SANITIZED_STEPS]
    if res.error:
        out.append(res.error)
    return out


def assert_clean(strings, *, question=QUESTION):
    assert strings, "场景没有产生任何错误文案"
    for s in strings:
        assert not FORBIDDEN.search(s), s
        m = CODE_RE.search(s)
        assert m and m.group(1) == TRACE[:8], s
        assert s.count("（编号 ") == 1, s
        assert len(s) <= MAX_LEN + len("（编号 xxxxxxxx）"), s
        if question and len(question) >= 12:
            assert question[:12] not in s, s
        # 文案只写详情，种类由 error_kind 承担（界面渲染「{KIND}失败：」）：不重复种类前缀
        assert not re.match(r"(数据集|模型调用|代码执行|分析流程)", s) and "LLM 调用失败" not in s, s
        assert not re.search(r"\b(unknown|bad_request|http_\d+|gateway_error)\b", s), s   # 内部枚举不进界面


# ---------------------------------------------------------------- 单元：四步处理
def test_scrub_masks_key_url_paths_controls():
    t = scrub(f"bad key {KEY} at https://api.x.com/v1?key=secret&a=1 file {WIN} or {POSIX} \u202eevil\x07")
    assert KEY not in t and "sk-***" in t
    assert "secret" not in t and "https://api.x.com/v1?…" in t
    assert "alice" not in t and t.count("<路径>") == 2
    assert "\u202e" not in t and "\x07" not in t


def test_scrub_strips_question_whole_and_truncated_prefix():
    assert QUESTION not in scrub(f"invalid: {QUESTION} !", QUESTION)
    half = QUESTION[:15]                                    # 网关截断 body，只剩半句
    t = scrub(f'{{"messages":[{{"content":"{half}', QUESTION)
    assert half not in t and "…" in t
    assert scrub("短问题出现", "短问题") == "短问题出现"      # ≥4 字整串才判；这里 3 字，不剥
    assert scrub("四字问题出现", "四字问题") == "…出现"


def test_scrub_keeps_column_names_and_truncates():
    t = scrub("列 price 不存在，可用列：region, store_id, 销售额", QUESTION)
    assert t == "列 price 不存在，可用列：region, store_id, 销售额"   # 列名在屏幕上本来可见，不剥
    assert len(scrub("x" * 5000)) == MAX_LEN


def test_upstream_message_takes_error_message_only():
    e = _bad_request("model not found: deepseek-x")
    assert upstream_message(e) == "model not found: deepseek-x"
    s = user_error("llm", e, trace_id=TRACE)
    assert s == "请求被模型服务拒绝：model not found: deepseek-x（编号 3f9a1c2d）"
    assert user_error("llm", TimeoutError("x"), trace_id=TRACE) == "请求超时（编号 3f9a1c2d）"
    assert user_error("llm", ValueError("x"), trace_id=TRACE) == "模型调用出错（编号 3f9a1c2d）"   # unknown 省略


def test_user_error_logs_original(caplog):
    with caplog.at_level("WARNING", logger="datachat.errors"):
        s = user_error("agent", RuntimeError(f"boom {WIN}"), trace_id=TRACE)
    assert s == "内部错误（编号 3f9a1c2d）"
    assert "RuntimeError" in caplog.text and WIN in caplog.text and f"trace={TRACE}" in caplog.text


# ---------------------------------------------------------------- dataset 出口
def _write(p, data: bytes):
    p.write_bytes(data)
    return str(p)


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_dataset_missing_file(tmp_path, agent):
    evs, res = run(str(tmp_path / "gone.csv"), agent=agent)
    assert res.error_kind == "dataset" and res.error.startswith("数据文件不见了，请重新上传")
    assert_clean(ui_strings(evs, res))


def test_dataset_encoding_parser_empty(tmp_path):
    cases = {
        "enc.csv": (b"a,b\n\xff\xfe\xfa,1\n\x81\x30", "无法识别文件编码"),
        "parse.csv": (b'a,b\n1,2\n3,"4\n5,6,7,8\n', "CSV "),
        "empty.csv": (b"", "文件是空的"),
    }
    for name, (data, expect) in cases.items():
        evs, res = run(_write(tmp_path / name, data))
        assert res.error.startswith(expect), (name, res.error)
        assert_clean(ui_strings(evs, res))


def test_dataset_multitable_names_the_broken_table(tmp_path, sample_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "orders.csv").write_bytes(open(sample_path, "rb").read())
    (d / "stores.csv").write_bytes(b"")
    evs, res = run(str(d))
    assert res.error.startswith("表 stores.csv：文件是空的"), res.error
    assert_clean(ui_strings(evs, res))


def test_dataset_empty_dir_is_own_text_without_path(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    evs, res = run(str(d))
    assert res.error.startswith("目录里没有 CSV 文件") and str(tmp_path) not in res.error
    assert_clean(ui_strings(evs, res))


# ---------------------------------------------------------------- 字典非致命
def test_dictionary_failure_nonfatal(sample_path, monkeypatch):
    import app.tools.dictionary as dictionary

    def broken(_):
        raise OSError(f"[Errno 13] Permission denied: '{WIN}'")
    monkeypatch.setattr(dictionary, "load_retriever", broken)
    evs, res = run(sample_path, model=wf_model(["result = 1"]))
    nonfatal = [e.data["message"] for e in evs if e.type == "error" and not e.data["fatal"]]
    assert nonfatal == ["数据字典读取失败，已跳过（编号 3f9a1c2d）"]
    assert res.ok
    assert_clean(nonfatal)


# ---------------------------------------------------------------- llm 出口
@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_llm_upstream_echo_is_stripped(sample_path, agent):
    msg = f"Invalid request: '{QUESTION}' exceeds limit; key {KEY}; see {POSIX}"
    m = ScriptedChatModel(responder=lambda _: _bad_request(msg), calls=[])
    evs, res = run(sample_path, agent=agent, model=m)
    assert res.error_kind == "llm" and res.error.startswith("请求被模型服务拒绝")
    assert "exceeds limit" in res.error                      # 上游自救信息照常透出
    assert_clean(ui_strings(evs, res))


def test_llm_truncated_echo_and_long_body(sample_path):
    msg = f'{{"model":"x","messages":[{{"role":"user","content":"{QUESTION[:14]}' + "y" * 5000
    m = ScriptedChatModel(responder=lambda _: _bad_request(msg), calls=[])
    evs, res = run(sample_path, model=m)
    assert QUESTION[:14] not in res.error
    assert_clean(ui_strings(evs, res))


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_llm_timeout_keeps_kind_only(sample_path, agent):
    m = ScriptedChatModel(responder=lambda _: TimeoutError(f"read timed out {WIN}"), calls=[])
    evs, res = run(sample_path, agent=agent, model=m, cfg=LLMConfig(api_key="t", backoff_base=0, max_retries=1))
    assert res.error_kind == "llm" and res.error.startswith("请求超时") and "timed out" not in res.error
    assert_clean(ui_strings(evs, res))


# ---------------------------------------------------------------- gateway：service.py:431 / :464
def test_gateway_retry_reason_and_final(sample_path):
    bad = f'{{"message":"prompt 必须包含字符串内容：{QUESTION}"}}'
    m = ScriptedChatModel(responder=lambda _: bad, calls=[])
    evs, res = run(sample_path, agent="react", model=m)
    retry = [e.data["message"] for e in evs if e.type == "error" and not e.data["fatal"]]
    assert retry and retry[0].startswith("重跑本轮：接口返回错误内容：prompt 必须包含字符串内容")
    assert res.error.startswith("接口返回错误内容：")
    assert_clean(ui_strings(evs, res))


def test_workflow_gateway_content_via_llmclient(sample_path):
    bad = f'{{"message":"bad {KEY} {QUESTION}"}}'
    m = ScriptedChatModel(responder=lambda _: bad, calls=[])
    evs, res = run(sample_path, model=m, cfg=LLMConfig(api_key="t", backoff_base=0, max_retries=0))
    assert res.error.startswith("共尝试 1 次：接口返回错误内容：bad sk-***")
    assert_clean(ui_strings(evs, res))


# ---------------------------------------------------------------- agent 出口 / service.py:525
@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_agent_unknown_exception_constant(sample_path, agent, monkeypatch):
    # 工作流里模型抛的异常经 LLMClient 包成 LLMError（llm 出口）；节点自身代码的异常（解析、取键）不经模型，
    # 落到 service.py 的 agent 常量——这里用图本身抛异常模拟这条真实路径
    m = ScriptedChatModel(responder=lambda _: KeyError(f"boom {WIN}"), calls=[])
    if agent == "workflow":
        import app.core.service as service

        class Broken:
            def stream(self, *a, **kw):
                raise KeyError(f"boom {WIN}")
                yield
        monkeypatch.setattr(service, "_workflow_graph", lambda: Broken())
    evs, res = run(sample_path, agent=agent, model=m)
    assert res.error_kind == "agent" and res.error == "内部错误（编号 3f9a1c2d）"
    assert_clean(ui_strings(evs, res))


def test_no_exec_answer_not_echoed(sample_path):
    leak = f"'{QUESTION}' 的答案是 42，见 {WIN}"
    m = ScriptedChatModel(replies=[leak, leak], calls=[])
    evs, res = run(sample_path, agent="react", model=m)
    assert res.error_kind == "agent" and "42" not in res.error and "\\" not in res.error
    assert_clean(ui_strings(evs, res))


# ---------------------------------------------------------------- 对照：exec 原文不脱敏（T9）
def test_exec_traceback_stays_raw(sample_path):
    m = ScriptedChatModel(replies=[tool_call("result = df['不存在的列']"), tool_call("result = 1", 2), "好"],
                          calls=[])
    evs, res = run(sample_path, agent="react", model=m)
    obs = [s for s in res.steps if s.name == "observation" and s.error]
    assert obs and "KeyError" in obs[0].error                 # 沙箱 traceback 原样保留
    assert "编号" not in obs[0].error


# ---------------------------------------------------------------- 数据集预览（app.py）
def test_dataset_preview_error_sanitized(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.server.app import create_app
    from tests.test_web import H, TOKEN, upload
    home = tmp_path / "home"
    c = TestClient(create_app(str(home), TOKEN, chat_model_factory=lambda: wf_model(["result = 1"])))
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n\xff\xfe\xfa,1\n\x81\x30")
    ds = upload(c, str(p))
    detail = c.get(f"/datasets/{ds['id']}", headers=H).json()
    errs = [x["error"] for x in detail.get("previews", []) if x.get("error")] or [detail.get("error")]
    for s in errs:
        assert s and "无法识别文件编码" in s and not FORBIDDEN.search(s), s
        assert re.search(r"（编号 [0-9a-f]{8}）$", s)
        assert str(home) not in s and os.sep + "datasets" not in s


# ---------------------------------------------------------------- dataset_message 的判定顺序（S 第三轮 ③）
def test_dataset_message_order():
    """同属 ValueError 家族的几类各用只属于自己的异常构造：精确类在前、宽类兜底在后，编码错误不能被标成解析失败。"""
    from pandas.errors import EmptyDataError, ParserError
    from app.core.errors import dataset_message
    from app.tools.csv_io import CSVEncodingError
    from app.tools.dataset import DuplicateTableError, NoCSVError, TableReadError
    assert issubclass(CSVEncodingError, ValueError) and issubclass(ParserError, ValueError)
    assert issubclass(EmptyDataError, ValueError) and not issubclass(EmptyDataError, ParserError)
    enc = CSVEncodingError("无法识别文件编码（已尝试 BOM 检测、utf-8 / gb18030）。请把文件另存为 UTF-8 后再上传")
    cases = [
        (enc, "无法识别文件编码（已尝试"),
        (CSVEncodingError("文件不能用指定编码 big5 解码：'big5' codec can't decode"), "文件不能用指定编码 big5 解码"),
        (EmptyDataError("No columns to parse from file"), "文件是空的"),
        (ParserError("Error tokenizing data. C error: Expected 2 fields in line 4, saw 4"), "CSV 第 4 行无法解析"),
        (ParserError("odd"), "CSV 无法解析"),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), "无法识别文件编码"),
        (FileNotFoundError(2, "No such file", WIN), "数据文件不见了，请重新上传"),
        (NoCSVError("目录里没有 CSV 文件"), "目录里没有 CSV 文件"),
        (DuplicateTableError("表名重复：a（a.csv 与 a.CSV）"), "表名重复：a（a.csv 与 a.CSV）"),
        (ValueError(f"something {WIN}"), "无法读取文件"),
    ]
    for exc, expect in cases:
        got = dataset_message(exc)
        assert got.startswith(expect) and "alice" not in got and "Error" not in got, (exc, got)
        if expect.startswith("文件不能用指定编码"):
            assert got == expect                              # 后半的 UnicodeDecodeError 原文去掉
    t = TableReadError("x", filename="stores.csv")
    t.__cause__ = enc
    assert dataset_message(t).startswith("表 stores.csv：无法识别文件编码")      # 包了一层也不误标


# ---------------------------------------------------------------- 机械约束：Emitter.error 只收 UserText
def test_emitter_rejects_raw_string():
    from app.core.errors import UserText
    from app.core.events import CANCELLED_MESSAGE, Emitter
    em = Emitter(TRACE)
    with pytest.raises(TypeError, match="user_error"):
        em.error(f"工作流异常：KeyError: 'plan'", "agent", fatal=True)
    em.error(user_error("agent", KeyError("plan"), trace_id=TRACE), "agent", fatal=True)
    em.error(CANCELLED_MESSAGE, "cancelled", fatal=True)                    # F2 常量是 UserText
    em.error("Traceback ... KeyError: 'x'", "execution", fatal=True)        # exec 原文按 T9 原样，例外
    assert isinstance(CANCELLED_MESSAGE, UserText)


# ---------------------------------------------------------------- 预览日志带上下文（S 第三轮 ②）
def test_dataset_preview_log_has_context(tmp_path, caplog):
    from fastapi.testclient import TestClient
    from app.server.app import create_app
    from tests.test_web import H, TOKEN, upload
    c = TestClient(create_app(str(tmp_path / "home"), TOKEN, chat_model_factory=lambda: wf_model(["result = 1"])))
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n\xff\xfe\xfa,1\n\x81\x30")
    ds = upload(c, str(p))
    with caplog.at_level("WARNING", logger="datachat.errors"):
        c.get(f"/datasets/{ds['id']}", headers=H)
    line = [r.getMessage() for r in caplog.records if r.name == "datachat.errors"][-1]
    assert f"dataset={ds['id']}" in line and "file=bad.csv" in line


# ---------------------------------------------------------------- keystore：源头不拼类型名 / 后端全限定名
def test_keystore_errors_have_no_type_or_backend_names(tmp_path, monkeypatch):
    import keyring
    from keyring.backends.fail import Keyring as Fail
    from fastapi.testclient import TestClient
    from app.core import keystore
    from app.server.app import create_app
    from tests.test_web import H, TOKEN
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    c = TestClient(create_app(str(tmp_path / "home"), TOKEN, chat_model_factory=lambda: wf_model(["result = 1"])))
    keyring.set_keyring(Fail())
    for method in ("put", "delete"):
        kw = {"json": {"api_key": "sk-abcdefgh12345678"}} if method == "put" else {}
        r = getattr(c, method)("/settings/api-key", headers=H, **kw)
        assert r.status_code == 400
        d = r.json()["detail"]
        assert d == "系统钥匙串不可用" and not re.search(r"Error|Keyring|keyring\.|backends", d), d

    class Broken(keyring.backend.KeyringBackend):
        priority = 1

        def get_password(self, s, u):
            return None

        def set_password(self, s, u, p):
            raise keyring.errors.PasswordSetError("dbus said no at /run/user/1000/bus")

        def delete_password(self, s, u):
            raise keyring.errors.PasswordDeleteError("x")
    keyring.set_keyring(Broken())
    r = c.put("/settings/api-key", headers=H, json={"api_key": "sk-abcdefgh12345678"})
    assert r.status_code == 400 and r.json()["detail"] == "写入系统钥匙串失败"
    assert keystore.backend_name().endswith("Broken")       # CLI status 仍给全名（本地终端诊断，不上界面）
