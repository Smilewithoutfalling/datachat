"""离线用的脚本化假模型：单元测试与评测自检（run_eval.py --oracle）共用，不访问网络。

ScriptedChatModel 是真正的 LangChain ChatModel：能被 LLMClient 调用，也能交给
ReAct 循环（bind_tools 返回自身），回调里能拿到 usage_metadata，所以 token 统计链路也被覆盖。
"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict


class ScriptedChatModel(BaseChatModel):
    """responder(messages) -> AIMessage | str | Exception（异常会被抛出，用来模拟超时/限流）。
    或者给 replies 列表，按顺序依次返回。每次返回的 AIMessage 自动带上 usage_metadata。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    responder: Any = None
    replies: list = []
    calls: list = []
    tokens_per_call: Any = (10, 5)   # None = 不带 usage_metadata

    def _next(self, messages):
        if self.responder is not None:
            out = self.responder(messages)
        else:
            if not self.replies:
                raise AssertionError("ScriptedChatModel: 预设回复已用完")
            out = self.replies.pop(0)
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, str):
            out = AIMessage(content=out)
        if self.tokens_per_call is None:      # 模拟不回 usage 的服务商（V2d §2a）
            return out
        i, o = self.tokens_per_call
        if out.usage_metadata is None:
            out = out.model_copy(update={"usage_metadata": {
                "input_tokens": i, "output_tokens": o, "total_tokens": i + o}})
        return out

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"


def prompt_text(messages) -> str:
    """把模型收到的消息拼成一段文本，方便按提示词内容决定回复。"""
    return "\n".join(str(getattr(m, "content", m)) for m in messages)


def oracle_model(code: str, agent: str = "workflow", *, say: str | None = None) -> ScriptedChatModel:
    """评测自检用：无论问什么，都"生成"给定代码（通常是 ground truth）。
    用来在没有 API Key 时验证评测流水线和打分口径本身是否正确。

    `say`：只回一句话、**不执行任何代码**。澄清题（EV-B7 的 clarify）用 —— 那类题的
    正确行为是反问，没有 gold 可执行；照旧执行 `result = None` 会被判成"没问清就动手"，
    于是 oracle 自检红、PR 档永久红，而红的原因不是判分链路坏了。
    """
    if say is not None:
        def respond(messages):
            return say
        return ScriptedChatModel(responder=respond, calls=[])

    if agent == "workflow":
        def respond(messages):
            text = prompt_text(messages)
            if "写一段 pandas 代码" in text or "请修正它" in text:
                return code
            if "数据分析规划助手" in text:
                return "（oracle）直接使用标准答案代码。"
            return "（oracle）结论见结果。"
    else:
        state = {"n": 0}

        def respond(messages):
            state["n"] += 1
            if state["n"] == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "run_python_on_data", "args": {"code": code}, "id": "call_oracle_1"}])
            return "（oracle）结论见结果。"
    return ScriptedChatModel(responder=respond, calls=[])


def oracle_factory(agent: str):
    """评测自检用的 `model_factory`：按用例类型给出"完美回答者"。

    这个分叉必须只有一份实现。它原来写在两处（`run_eval.py` 与
    `tests/test_eval_cases.py`），加 clarify 支持时只改了一处，于是 CLI 跑
    193/193、测试跑 187/193，红灯看起来像判分坏了 —— 实际是两个入口的假模型不同。

    clarify 题的正确答案是一句反问，不是一段代码。照 gold 执行 `result = None`
    会被 negative_verdict 判成"没问清口径就猜着算"，与它的本意正好相反。
    """
    clarify_say = "您是指哪个时间范围和口径？请确认后我再计算。"

    def make(case):
        # 只有 react 能表达"不执行、只反问"。workflow 是固定线性图
        # （planner → codegen → executor → summarizer），codegen 的契约只有
        # 「算」或「拒答」，没有"反问问清"这条路 —— 硬把一句中文塞给它，
        # 结果是 executor 拿它当代码跑，报 SyntaxError: invalid character '？'。
        # 那个失败不是判分链路坏了，是这个 agent 结构上没有这条路。
        say = clarify_say if (agent == "react" and getattr(case, "expect_kind", "") == "clarify") else None
        return oracle_model(case.ground_truth, agent, say=say)
    return make


__all__ = ["ScriptedChatModel", "oracle_model", "oracle_factory", "prompt_text"]

