"""假模型服务（F3 起所有异步测试的公共设施）：独立进程的 OpenAI 兼容 HTTP 服务。

产品代码不改，只把 base_url 指过来（DEEPSEEK_BASE_URL=http://127.0.0.1:<port>/v1）。
行为完全由请求决定，服务端没有状态：同样的 model 名 + 同样的提示词 → 同样的行为。
测试重跑不用重置，多个后端 / worker 可以共享一个实例。

model 名语法（解析器严格，见 parse_model）：
    <scenario>[@<step>]
    scenario：ok | hang-<N>s | fail-<code> | slow-<N>s | chart-<kind> | inject-<kind> | inject-error
      ok          每一步正常回复（固定剧本，见 reply_for）
      chart-<kind> 同 ok，但写代码的那一步（codegen / fix / act）多调一次 chart('<kind>', df, …)（F3 图表测试）；
                  kind 取 app/tools/charts.py 的 KINDS，列按 dtype 选（chart_code），任何 CSV 只要有一个类目列和
                  一个数值列（scatter 要两个数值列）都能画。不带 @step。
      inject-<kind> F3 第二步注入实测：写代码的那一步对 inject_csv() 这份数据出图，标题、列名、类目、系列名都是
                  INJECT_PAYLOADS；cartesian / scatter 出两张（宽表多 y：列名进图例；长表 series=：单元格值进图例），
                  pie 出一张；结论拼上 P1–P3（含一个 javascript: 链接）。不带 @step。
      inject-error 同上，但只调一次 chart()，x 传不存在的列名 P1：没有图时 chart_error 才进 result.warnings
                  （app/core/result.py chart_warnings 的 `not has_option`），所以单独一个场景。
      hang-<N>s   在目标调用上先睡 N 秒再正常回复（测停止）
      fail-<code> 目标调用返回 HTTP <code>（400/401/403/404/429/500/502/503）
      slow-<N>s   每一次调用都先睡 N 秒（把事件拉开，测增量渲染）
    step：plan | codegen | fix | answer（工作流）、act | final（ReAct）
      不写 @step 时目标调用是"第一次调用"：工作流的 plan、ReAct 的 act（无状态可判定，不需要计数）。

fail loud：认不出的东西一律 HTTP 400（不可重试，后端立刻以 http_400 失败，不会被当成 5xx 退避重试三次），
body 写明原因——未知 scenario / step、拼错（hang-30 少了 s）、@step 不属于本次请求的链路
（@codegen 用在 ReAct 上会永远匹配不上，静默不挂就是假绿）、认不出当前是哪一步（提示词可能改了）、
请求要求 stream。没有"认不出就按默认走"这条路。

运行：python -m tests.fake_llm --port 8790
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from app.tools.charts import KINDS

WORKFLOW_STEPS = ("plan", "codegen", "fix", "answer")
REACT_STEPS = ("act", "final")
FIRST_STEP = {"workflow": "plan", "react": "act"}
FAIL_CODES = (400, 401, 403, 404, 429, 500, 502, 503)
MAX_SECONDS = 600

# 剧本：单表数据集里 df 就是那张表（app/tools/dataset.py），行数对任何 CSV 都成立
CODE = "result = int(len(df))"
PLAN = "（fake）统计行数。"
ANSWER = "（fake）结论：数据共有若干行。"


def chart_code(kind: str) -> str:
    """chart-<kind> 场景的代码：类目列取第一个非数值列，数值列取第一个（scatter 取前两个数值列）。"""
    xy = "x=num[0], y=num[1]" if kind == "scatter" else "x=cat[0], y=num[0]"
    return (f"num = list(df.select_dtypes('number').columns)\n"
            f"cat = [c for c in df.columns if c not in num]\n"
            f"chart({kind!r}, df, {xy}, title={'fake ' + kind!r})\n" + CODE)
FAIL_ANSWER = "（fake）没能得出结果。"

# ------------------------------------------------------------ F3 第二步：注入载荷（gen_ui_types 导出给前端，前端不另写）
# 每条都短于 charts.NAME_MAX，不会被截断。P4 / P5 不是代码执行面，测的是 ECharts 会不会把用户字符串当模板 / 富文本解析。
# P6 / P7（F3 第三步）：第二步实测出的两个最高级威胁的回归载荷。P6 用 `}` 跳出 tooltip 的 richText 包装、借内部数值样式
# 在数值列伪造 999（样式名 __EC_aUTo_<n>，n 起点随机，固定写 4 只是覆盖其中一个）；P7 用换行改变 tooltip 行归属。
# 后端 _display_safe 之后两者都应原样（全角 / 空格）画成一段，期望显示串由 gen_ui_types 算进 inject.json 的 display。
INJECT_PAYLOADS = {
    "P1": '<img src=x onerror="window.__pwned=1">',
    "P2": '"><svg onload="window.__pwned=2">',
    "P3": "javascript:window.__pwned=3",
    "P4": "{a}{b}{c}",
    "P5": "{x|富文本}",
    "P6": "x}{__EC_aUTo_4|999",
    "P7": "上\n下",
}
_P = INJECT_PAYLOADS
# 列：类目列名 P4、系列列名 P5（进轴名 / 标题）；数值列名 P2、P3（进宽表图例、长表 y 轴名）。
# 7 行：类目值按 INJECT_ORDER，系列值错开一位（长表每个 (类目, 系列) 唯一）。P2 列全相等，饼图 7 个扇区等分（e2e 按角度悬停）。
# 顺序有讲究：载荷标签长，1200px 宽的图里 echarts 自动隔一个画一个（第 0、2、4、6 个），P4–P7 放在画得出来的位置上，
# 这样类目轴标签这个位置上 P4–P7 都有实测结论（e2e 断言了这四个确实被画出来）。
INJECT_COLUMNS = [_P["P4"], _P["P5"], _P["P2"], _P["P3"]]
INJECT_ORDER = ["P4", "P1", "P5", "P2", "P6", "P3", "P7"]
_N = len(INJECT_ORDER)
INJECT_ROWS = [[_P[INJECT_ORDER[i]], _P[INJECT_ORDER[(i + 1) % _N]], 2, i + 1] for i in range(_N)]
INJECT_ANSWER = (f"（fake）结论：{_P['P1']} {_P['P2']} {_P['P3']} [点我]({_P['P3']})")


def inject_csv() -> str:
    """注入夹具 CSV，用 csv.writer 生成：载荷里有 < " { | 和换行，手拼会把 CSV 结构撑坏。"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(INJECT_COLUMNS)
    w.writerows(INJECT_ROWS)
    return buf.getvalue()


def inject_code(kind: str) -> str:
    """inject-<kind> / inject-error 场景的代码。列按 dtype 选（不在代码里写列名），标题和错列名是载荷字面量（代码面板也是一个面）。"""
    head = ("num = list(df.select_dtypes('number').columns)\n"
            "cat = [c for c in df.columns if c not in num]\n")
    if kind == "error":
        return head + f"chart('bar', df, x={_P['P1']!r}, y=num[0], title={_P['P1']!r})\n" + CODE
    if kind == "pie":
        return head + f"chart('pie', df, x=cat[0], y=num[0], title={_P['P1']!r})\n" + CODE
    title2 = f"{_P['P4']} {_P['P5']}"
    if kind == "scatter":
        wide, long_ = "x=num[0], y=num", "x=num[0], y=num[1], series=cat[1]"
    else:
        wide, long_ = "x=cat[0], y=num", "x=cat[0], y=num[0], series=cat[1]"
    return (head + f"chart({kind!r}, df, {wide}, title={_P['P1']!r})\n"
            f"chart({kind!r}, df, {long_}, title={title2!r})\n" + CODE)

# 步骤识别用的提示词片段。改了 app/nodes/* 或 app/react_agent.py 的提示词，这里会认不出 → 400，
# tests/test_fake_llm.py 的真链路测试（两种 agent 都跑一遍）立刻红。
MARK_REACT = "你是一个数据分析智能体"
MARK_PLAN = "你是数据分析规划助手"
MARK_FIX = "之前生成的 pandas 代码执行出错了，请修正它"
MARK_CODEGEN = "根据分析计划写一段 pandas 代码"
MARK_ANSWER_OK = "根据分析结果，用中文简洁、直接地回答用户问题"
MARK_ANSWER_FAIL = "分析未能成功完成"


class FakeError(Exception):
    """认不出 / 不支持：返回 400 + 原因。"""


@dataclass(frozen=True)
class Scenario:
    kind: str                    # ok | hang | fail | slow | chart | inject
    value: int = 0               # 秒数或 HTTP 状态码
    step: Optional[str] = None   # 目标步骤；None = 第一次调用
    chart: Optional[str] = None  # chart / inject 场景的图型（inject 另有 "error"）

    def targets(self, agent: str, step: str) -> bool:
        if self.step is not None and self.step not in (WORKFLOW_STEPS if agent == "workflow" else REACT_STEPS):
            raise FakeError(f"场景 @{self.step} 不属于 {agent} 链路，永远匹配不上——换成该链路的步骤名")
        return step == (self.step or FIRST_STEP[agent])


_CHART_RE = re.compile(r"^chart-(?P<kind>[a-z]+)(?:@(?P<step>[a-z]*))?$")
_INJECT_RE = re.compile(r"^inject-(?P<kind>[a-z]+)(?:@(?P<step>[a-z]*))?$")
_MODEL_RE = re.compile(r"^(?P<kind>ok|hang|fail|slow)(?:-(?P<val>\d+)(?P<unit>s?))?(?:@(?P<step>[a-z]+))?$")


def parse_model(name: str) -> Scenario:
    c = _CHART_RE.match(name or "")
    if c:
        if c["kind"] not in KINDS:
            raise FakeError(f"未知图型 {c['kind']!r}：可选 {', '.join(KINDS)}")
        if c["step"] is not None:
            raise FakeError(f"chart 作用于写代码的那一步，不带 @step：{name!r}")
        return Scenario("chart", chart=c["kind"])
    j = _INJECT_RE.match(name or "")
    if j:
        if j["kind"] not in KINDS + ("error",):
            raise FakeError(f"未知图型 {j['kind']!r}：可选 {', '.join(KINDS)}, error")
        if j["step"] is not None:
            raise FakeError(f"inject 作用于写代码的那一步，不带 @step：{name!r}")
        return Scenario("inject", chart=j["kind"])
    m = _MODEL_RE.match(name or "")
    if not m:
        raise FakeError(f"无法解析 model 名 {name!r}：语法是 <ok|hang-Ns|fail-CODE|slow-Ns|chart-KIND|inject-KIND>[@step]")
    kind, val, unit, step = m["kind"], m["val"], m["unit"], m["step"]
    if step is not None and step not in WORKFLOW_STEPS + REACT_STEPS:
        raise FakeError(f"未知步骤 @{step}：可选 {', '.join(WORKFLOW_STEPS + REACT_STEPS)}")
    if kind == "ok":
        if val is not None or step is not None:
            raise FakeError(f"ok 不带参数：{name!r}")
        return Scenario("ok")
    if val is None:
        raise FakeError(f"{kind} 需要参数：{name!r}")
    n = int(val)
    if kind in ("hang", "slow"):
        if unit != "s":
            raise FakeError(f"{kind} 的参数要带单位 s（如 {kind}-30s）：{name!r}")
        if not 1 <= n <= MAX_SECONDS:
            raise FakeError(f"{kind} 秒数要在 1–{MAX_SECONDS}：{name!r}")
        if kind == "slow" and step is not None:
            raise FakeError(f"slow 作用于每一次调用，不带 @step：{name!r}")
        return Scenario(kind, n, step)
    if unit:
        raise FakeError(f"fail 的参数是 HTTP 状态码，不带单位：{name!r}")
    if n not in FAIL_CODES:
        raise FakeError(f"fail 只支持 {FAIL_CODES}：{name!r}")
    return Scenario("fail", n, step)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):   # OpenAI 的分段 content
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def recognize(messages: list) -> tuple[str, str]:
    """(agent, step)。认不出就抛 FakeError，绝不猜。"""
    if not isinstance(messages, list) or not messages:
        raise FakeError("请求里没有 messages")
    whole = "\n".join(_text(m.get("content")) for m in messages if isinstance(m, dict))
    if MARK_REACT in whole:
        # 边界：只按"最后一条是不是 tool"分 act / final，适用于单轮工具调用的剧本。多轮（连调两次工具再收尾）
        # 分不出第几轮——真要测时按 tool 消息个数分，仍然无状态，不要加计数器。
        return "react", ("final" if messages[-1].get("role") == "tool" else "act")
    for mark, step in ((MARK_PLAN, "plan"), (MARK_FIX, "fix"), (MARK_CODEGEN, "codegen"),
                       (MARK_ANSWER_OK, "answer"), (MARK_ANSWER_FAIL, "answer")):
        if mark in whole:
            return "workflow", step
    raise FakeError("无法识别当前步骤，提示词可能已变（更新 tests/fake_llm.py 的 MARK_*）")


def reply_for(agent: str, step: str, messages: list, chart: Optional[str] = None, inject: bool = False) -> dict:
    """固定剧本：返回 OpenAI 的 assistant message。chart 给定时，写代码的那一步换成 chart_code(chart)；
    inject 时换成 inject_code(chart)，成功结论换成 INJECT_ANSWER。"""
    code = inject_code(chart) if inject else (chart_code(chart) if chart else CODE)
    answer = INJECT_ANSWER if inject else ANSWER
    if agent == "react":
        if step == "act":
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_fake_1", "type": "function",
                "function": {"name": "run_python_on_data", "arguments": json.dumps({"code": code})}}]}
        return {"role": "assistant", "content": answer}
    if step == "plan":
        return {"role": "assistant", "content": PLAN}
    if step in ("codegen", "fix"):
        return {"role": "assistant", "content": f"```python\n{code}\n```"}
    whole = "\n".join(_text(m.get("content")) for m in messages)
    return {"role": "assistant", "content": FAIL_ANSWER if MARK_ANSWER_FAIL in whole else answer}


def handle(body: dict, sleep=time.sleep) -> tuple[int, dict]:
    """纯函数核心（HTTP 外壳只做收发），单元测试直接调它。"""
    try:
        if body.get("stream"):
            raise FakeError("假服务不支持 stream=true（产品目前不用流式调用）")
        sc = parse_model(body.get("model", ""))
        agent, step = recognize(body.get("messages"))
        hit = sc.targets(agent, step)
    except FakeError as e:
        return 400, {"error": {"message": f"[fake_llm] {e}", "type": "invalid_request_error", "code": "fake_llm"}}
    if sc.kind == "slow" or (sc.kind == "hang" and hit):
        sleep(sc.value)
    if sc.kind == "fail" and hit:
        return sc.value, {"error": {"message": f"[fake_llm] 按场景返回 {sc.value}", "type": "fake_failure",
                                    "code": str(sc.value)}}
    msg = reply_for(agent, step, body["messages"], sc.chart, sc.kind == "inject")
    return 200, {
        "id": f"chatcmpl-fake-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": int(time.time()),
        "model": body["model"],
        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass   # 调用方已放弃（超时 / 取消）

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/v1/health"):
            return self._send(200, {"ok": True})
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            return self._send(404, {"error": {"message": f"[fake_llm] 未知路径 {self.path}"}})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": {"message": "[fake_llm] body 不是 JSON"}})
        code, obj = handle(body)
        if code == 400:
            sys.stderr.write(f"{obj['error']['message']}\n")
        self._send(code, obj)

    def log_message(self, fmt, *args):  # 安静；400 已单独写 stderr
        pass


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), _Handler)
    srv.daemon_threads = True
    return srv


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args(argv)
    srv = make_server(a.host, a.port)
    print(f"fake_llm listening on http://{a.host}:{srv.server_address[1]}/v1", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
