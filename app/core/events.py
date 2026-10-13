"""analyze_stream() 产出的事件（阶段 4，M09）。以后 FastAPI 的 SSE 逐条转发 Event.to_dict()。

每个事件都带 trace_id（同一次分析相同）、seq（从 0 递增）、ts（Unix 时间戳，秒）。类型与 data：

| type   | 何时 | data |
|--------|------|------|
| plan   | 工作流 planner 产出计划 | text |
| code   | 工作流 codegen / reviewer 写出代码；ReAct 模型发起一次工具调用 | code, source（codegen / reviewer / tool_call）, attempt；ReAct 另有 thought（模型随调用附带的文字，常为空） |
| exec   | 一次代码执行结束 | ok, result_text（截断 2000 字）, error, duration_s, chart（图表路径或 None）；ReAct 另有 stdout, attempt |
| answer | 最终结论（ReAct 在收尾判定后才发，所以每次分析最多一个） | text, forced（ReAct 步数用完后强制收尾得到的结论） |
| error  | 出错 | message, kind（dataset / llm / execution / agent）, fatal |
| done   | 最后一个事件，必有且只有一个 | result（AnalysisResult.to_record()）；Python 侧另可用 Event.result 取原对象 |

error 的 fatal=False 表示过程中的可恢复情况（数据字典读取失败已跳过；ReAct 整轮重跑）。
ReAct 整轮重跑时，之前那一轮已经发出的 code / exec 事件作废，以重跑后的为准（error 事件的 message 以"重跑本轮"开头）。
fatal=True 的 error 只在 done 之前出现一次，内容与 done 里的 error / error_kind 相同。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

EVENT_TYPES = ("plan", "code", "exec", "answer", "error", "done")


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

    def error(self, message, kind, *, fatal):
        return self._make("error", {"message": message, "kind": kind, "fatal": fatal})

    def done(self, result):
        return self._make("done", {}, result)
