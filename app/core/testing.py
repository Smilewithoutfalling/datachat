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

    **改写器（M7）的调用也要答。** 改写题（`mem_004` / `mem_005`）在 `memory_mode != off`
    时会先发一次「你是问题改写器」的调用，那一次不是分析、也不该消耗下面那个"第一次给代码"
    的计数：2026-11-17 之前默认档是 off，改写被 service 短路，这条路径在 oracle 自检里根本
    没被走到，所以桩不答也没人发现。桩拿不到"正确改写"（它不知道 gold 对应的是哪句人话），
    就明说拿不准 → 按 M7 的契约回落原问题，判分链路照旧可验；改写质量由真实模型跑 mem_* 题测。
    """
    if say is not None:
        def respond(messages):
            return say
        return ScriptedChatModel(responder=respond, calls=[])

    rewrite_fallback = '{"rewritten": "", "needs_clarify": true, "reason": "oracle 不判改写"}'

    if agent == "workflow":
        def respond(messages):
            text = prompt_text(messages)
            if "你是问题改写器" in text:
                return rewrite_fallback
            if "写一段 pandas 代码" in text or "请修正它" in text:
                return code
            if "数据分析规划助手" in text:
                return "（oracle）直接使用标准答案代码。"
            return "（oracle）结论见结果。"
    else:
        state = {"n": 0}

        def respond(messages):
            # 改写调用不计数：它发生在分析之前，计进去会让"第一次给代码"错位一轮
            if "你是问题改写器" in prompt_text(messages):
                return rewrite_fallback
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
    会被 negative_verdict 判成没交答案也没反问（执行了但 result 是空的），
    与它的本意正好相反。
    """
    clarify_say = "您是指哪个时间范围和口径？请确认后我再计算。"

    def make(case):
        # clarify 题的正确输出是一句反问，没有 gold 可执行；照 gold 跑 result = None
        # 会被 negative_verdict 判成"没交答案也没反问"，与它的本意正好相反。
        #
        # 两个 agent 的表达方式不同，因为走的路不同：
        #   workflow  planner 用 `CLARIFY: ` 前缀打标，图短路到 summarizer（2026-11-13 起支持）；
        #   react     直接回一句话，不调工具。
        # 给 workflow 少写这个前缀，它会当成分析步骤走 codegen，然后 executor 拿中文当代码跑，
        # 报 SyntaxError —— 那个失败不是判分链路坏了。
        clarify = getattr(case, "expect_kind", "") == "clarify"
        if clarify and agent == "workflow":
            say = "CLARIFY: " + clarify_say
        elif clarify:
            say = clarify_say
        else:
            say = None
        return oracle_model(case.ground_truth, agent, say=say)
    return make


__all__ = ["ScriptedChatModel", "oracle_model", "oracle_factory", "prompt_text"]

