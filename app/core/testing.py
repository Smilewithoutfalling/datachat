"""离线用的脚本化假模型：单元测试与评测自检（run_eval.py --oracle）共用，不访问网络。

ScriptedChatModel 是真正的 LangChain ChatModel：能被 LLMClient 调用，也能交给
create_react_agent（bind_tools 返回自身），回调里能拿到 usage_metadata，所以 token 统计链路也被覆盖。
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
    tokens_per_call: tuple = (10, 5)

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


def oracle_model(code: str, agent: str = "workflow") -> ScriptedChatModel:
    """评测自检用：无论问什么，都"生成"给定代码（通常是 ground truth）。
    用来在没有 API Key 时验证评测流水线和打分口径本身是否正确。"""
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


__all__ = ["ScriptedChatModel", "oracle_model", "prompt_text"]

