"""analyze_stream() 产出的事件（阶段 4，M09）。以后 FastAPI 的 SSE 逐条转发 Event.to_dict()。

每个事件都带 trace_id（同一次分析相同）、seq（从 0 递增）、ts（Unix 时间戳，秒）。类型与 data：

| type   | 何时 | data |
|--------|------|------|
| plan   | 工作流 planner 产出计划 | text |
| code   | 工作流 codegen / reviewer 写出代码；ReAct 模型发起一次工具调用 | code, source（codegen / reviewer / tool_call）, attempt；ReAct 另有 thought（模型随调用附带的文字，常为空） |
| exec   | 一次代码执行结束 | ok, result_text（截断 2000 字）, error, duration_s, chart（PNG 路径或 None）, options（chart() 出的 ECharts spec 列表，exec 失败时为空）, chart_errors, charts_discarded（exec 失败丢弃的张数）；ReAct 另有 stdout, attempt |
| answer | 最终结论（ReAct 在收尾判定后才发，所以每次分析最多一个） | text, forced（ReAct 步数用完后强制收尾得到的结论） |
| error  | 出错 | message, kind（dataset / llm / execution / agent / cancelled）, fatal, llm_kind（kind=llm 时为子类：LLM_KINDS 之一或 http_NNN；其余为 null） |
| done   | 最后一个事件，必有且只有一个 | result（AnalysisResult.to_record()）；Python 侧另可用 Event.result 取原对象 |

error 的 fatal=False 表示过程中的可恢复情况（数据字典读取失败已跳过；ReAct 整轮重跑）。
ReAct 整轮重跑时，之前那一轮已经发出的 code / exec 事件作废，以重跑后的为准（error 事件的 message 以"重跑本轮"开头）。
fatal=True 的 error 只在 done 之前出现一次，内容与 done 里的 error / error_kind 相同。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.errors import UserText

EVENT_TYPES = ("plan", "code", "exec", "answer", "error", "done")
# error 事件 / AnalysisResult 的 llm_kind：classify_error 的枚举加 no_key（没配 Key，没发请求）。
# 另有 http_NNN（classify_error 对未单列的 4xx 返回），是模式不是枚举，不在表里。前端按它给错误卡分出口（phase5 V2a）。
LLM_KINDS = ("timeout", "connection", "rate_limit", "auth", "bad_request", "server", "gateway_error", "unknown", "no_key")
# error 事件的 kind / AnalysisResult.error_kind。前端只按 kind / status 分支，不对文案做匹配（阶段 5 F2）。
# - cancelled：用户点了停止（POST /messages/{id}/cancel）。只有用户动作才用它。
# - interrupted：非用户动作的终止——后端重启时清理遗留 running、SSE 客户端断开（关标签页、网络抖动）。
#   analyze_stream 永远不产出它：只落在 messages.status=interrupted，前端重放时按它合成 done
#   （error_kind=interrupted）并给重试入口。两种原因文案不同，但前端不按文案分支。
ERROR_KINDS = ("dataset", "llm", "execution", "agent", "cancelled", "interrupted")
# 以下文案是常量，不带任何内部异常或堆栈（详情只进日志）。
CANCELLED_MESSAGE = UserText("已取消")
INTERRUPTED_MESSAGE = UserText("分析已中断（服务已重启）")
DISCONNECTED_MESSAGE = UserText("分析已中断（连接已断开）")
STREAM_ABORTED_MESSAGE = UserText("分析异常中断（服务端错误）")     # 流里没收到 done 就抛异常（status=error）


@dataclass
class Event:
    type: str
    trace_id: str
    seq: int
    ts: float
    data: dict = field(default_factory=dict)
    result: Optional[Any] = field(default=None, repr=False)   # 只有 done 有：AnalysisResult 原对象

    def to_dict(self) -> dict:
        """可 JSON 序列化。"""
        d = {"type": self.type, "trace_id": self.trace_id, "seq": self.seq, "ts": self.ts, "data": dict(self.data)}
        if self.type == "done" and self.result is not None:
            d["data"]["result"] = self.result.to_record()
        return d


class Emitter:
    """给一次分析编号、打时间戳。"""

    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self._seq = 0

    def _make(self, type_: str, data: dict, result=None) -> Event:
        ev = Event(type_, self.trace_id, self._seq, round(time.time(), 3), data, result)
        self._seq += 1
        return ev

    def plan(self, text):
        return self._make("plan", {"text": text})

    def code(self, code, *, source, attempt, **extra):
        return self._make("code", {"code": code, "source": source, "attempt": attempt, **extra})

    def exec(self, *, ok, result_text, error, duration_s, chart, **extra):
        return self._make("exec", {"ok": ok, "result_text": result_text, "error": error,
                                   "duration_s": duration_s, "chart": chart, **extra})

    def answer(self, text, *, forced=False):
        return self._make("answer", {"text": text, "forced": forced})

    def error(self, message, kind, *, fatal, llm_kind=None):
        # T11 机械约束：界面文案只能来自 user_error（或 F2 常量）。exec 原文（kind=execution）按 T9 原样，例外
        if kind != "execution" and not isinstance(message, UserText):
            raise TypeError(f"error 事件的 message 必须经 app.core.errors.user_error 生成（kind={kind}）")
        if (llm_kind is not None) != (kind == "llm"):
            raise ValueError(f"llm_kind 只在 kind=llm 时给，且必须给（kind={kind}, llm_kind={llm_kind}）")
        return self._make("error", {"message": str(message), "kind": kind, "fatal": fatal, "llm_kind": llm_kind})

    def done(self, result):
        return self._make("done", {}, result)
