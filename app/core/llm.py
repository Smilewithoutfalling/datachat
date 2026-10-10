"""LLM 调用工程保护：显式超时、带退避的重试、token 统计（B10）。

两种 Agent 的处理方式不同，原因如下：
- 工作流版：节点通过 LLMClient.invoke 调模型。底层 ChatOpenAI 设 max_retries=0，
  重试完全由本模块控制（指数退避 + 抖动，只重试超时/限流/连接/5xx），每次重试记入 usage.retries。
- ReAct 版：create_react_agent 只接受 ChatModel 或 bind_tools 后的 RunnableBinding，
  包不进外层重试（RunnableRetry 会被拒绝），所以把同一份 LLMConfig 的 timeout/max_retries
  显式交给 openai SDK，由 SDK 做指数退避；token 通过回调 UsageCallbackHandler 统计。
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from langchain_core.callbacks import BaseCallbackHandler

# DeepSeek 提供 OpenAI 兼容接口，直接用 ChatOpenAI 指向其 base_url 即可。
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


@dataclass(frozen=True)
class LLMConfig:
    """一次分析使用的模型配置。api_key 不进 repr，避免被打印到日志。"""
    model: str = "deepseek-chat"
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = DEEPSEEK_BASE_URL
    temperature: float = 0.0
    timeout: float = 60.0          # 单次请求超时（秒），显式设置，不依赖库默认
    max_retries: int = 3           # 失败后最多再试几次（不含首次）
    backoff_base: float = 1.0      # 退避基数：第 i 次重试前等待 base * 2**i 秒（加抖动）
    backoff_max: float = 20.0      # 单次等待上限（秒）

    @classmethod
    def from_env(cls, **overrides) -> "LLMConfig":
        """从环境变量读取（.env 由入口脚本加载），再用 overrides 覆盖。"""
        env = {
            "model": os.getenv("DEEPSEEK_MODEL") or cls.model,
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "base_url": os.getenv("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL,
        }
        if os.getenv("DATACHAT_LLM_TIMEOUT"):
            env["timeout"] = float(os.getenv("DATACHAT_LLM_TIMEOUT"))
        if os.getenv("DATACHAT_LLM_MAX_RETRIES"):
            env["max_retries"] = int(os.getenv("DATACHAT_LLM_MAX_RETRIES"))
        env.update(overrides)
        return cls(**env)

    def with_(self, **kw) -> "LLMConfig":
        return replace(self, **kw)


# ---------------------------------------------------------------- token 统计
@dataclass
class TokenUsage:
    calls: int = 0                 # 成功的模型调用次数
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    retries: Optional[int] = 0     # 本模块执行的重试次数；ReAct 版由 SDK 内部重试，无法计数时为 None
    reported: bool = True          # 是否每次调用都拿到了 usage（假模型/不返回 usage 的服务为 False）


class UsageTracker:
    """线程安全的累加器，每次 analyze() 新建一个。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.usage = TokenUsage()

    def add_message(self, msg: Any) -> None:
        meta = getattr(msg, "usage_metadata", None) or {}
        with self._lock:
            self.usage.calls += 1
            if not meta:
                self.usage.reported = False
                return
            i = int(meta.get("input_tokens") or 0)
            o = int(meta.get("output_tokens") or 0)
            self.usage.input_tokens += i
            self.usage.output_tokens += o
            self.usage.total_tokens += int(meta.get("total_tokens") or (i + o))

    def add_retry(self) -> None:
        with self._lock:
            if self.usage.retries is not None:
                self.usage.retries += 1

    def snapshot(self) -> TokenUsage:
        with self._lock:
            return replace(self.usage)


class UsageCallbackHandler(BaseCallbackHandler):
    """ReAct 版用：挂在 agent.invoke 的 callbacks 上，每次模型返回时记 token。"""

    def __init__(self, tracker: UsageTracker):
        self.tracker = tracker

    def on_llm_end(self, response, **kwargs):  # noqa: D401
        for gens in response.generations:
            for g in gens:
                self.tracker.add_message(getattr(g, "message", None))


# ---------------------------------------------------------------- 错误分类
class LLMError(RuntimeError):
    """重试用尽或遇到不可重试错误后抛出。kind 便于上层区分"基础设施失败"和"答错"。"""

    def __init__(self, message: str, *, kind: str, attempts: int, cause: BaseException | None = None):
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts
        self.cause = cause


_API_ERROR_KEYS = {"message", "error", "detail", "msg", "code", "status", "type", "param", "request_id"}


def api_error_text(text) -> Optional[str]:
    """B45：网关有时以 200 返回一段错误 JSON 作为"回复内容"，例如
    {"message":"prompt: A user's message must contain at least one image or a PDF or audio."}。
    整段内容是一个 JSON 对象、键全是错误字段（message/error/detail…）时返回错误说明，否则 None。
    正常结论（中文文字、代码、含其他键的 JSON）不受影响。"""
    import json

    if not isinstance(text, str):
        return None
    t = text.strip()
    if not (t.startswith("{") and t.endswith("}")):
        return None
    try:
        obj = json.loads(t)
    except Exception:
        return None
    if not isinstance(obj, dict) or not obj or not set(obj) <= _API_ERROR_KEYS:
        return None
    err = obj.get("error")
    if isinstance(err, dict):
        err = err.get("message") or json.dumps(err, ensure_ascii=False)
    msg = obj.get("message") or err or obj.get("detail") or obj.get("msg")
    return str(msg) if msg else None


class GatewayErrorContent(Exception):
    """模型接口返回了错误 JSON 而不是回复（B45）。按短暂故障处理，可重试。"""


def classify_error(exc: BaseException) -> tuple[str, bool]:
    """返回 (kind, 是否可重试)。只重试短暂性故障；鉴权/参数错误重试无意义。"""
    try:
        import openai
    except Exception:  # pragma: no cover
        openai = None
    if openai is not None:
        if isinstance(exc, openai.APITimeoutError):
            return "timeout", True
        if isinstance(exc, openai.APIConnectionError):
            return "connection", True
        if isinstance(exc, openai.RateLimitError):
            return "rate_limit", True
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return "auth", False
        if isinstance(exc, (openai.BadRequestError, openai.NotFoundError,
                            openai.UnprocessableEntityError)):
            return "bad_request", False
        if isinstance(exc, openai.APIStatusError):
            code = getattr(exc, "status_code", 0) or 0
            return ("server", True) if code >= 500 else ("http_%d" % code, False)
    if isinstance(exc, GatewayErrorContent):
        return "gateway_error", True
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return "timeout", True
    if isinstance(exc, ConnectionError):
        return "connection", True
    return "unknown", False


# ---------------------------------------------------------------- 构建与调用
def build_chat_model(cfg: LLMConfig, *, sdk_retries: int | None = 0):
    """按配置构建 ChatOpenAI。超时总是显式传入；sdk_retries 默认 0（由 LLMClient 重试）。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key or "missing-api-key",   # 缺 Key 时让请求以 401 失败，而不是构建时崩溃
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        timeout=cfg.timeout,
        max_retries=sdk_retries,
    )


class LLMClient:
    """节点使用的模型句柄：invoke(prompt) -> str，自带重试与 token 统计。"""

    def __init__(self, config: LLMConfig | None = None, *, model=None,
                 tracker: UsageTracker | None = None,
                 sleep: Callable[[float], None] = time.sleep, jitter: bool = True):
        self.config = config or LLMConfig.from_env()
        self.model = model if model is not None else build_chat_model(self.config, sdk_retries=0)
        self.tracker = tracker or UsageTracker()
        self._sleep = sleep
        self._jitter = jitter

    def _delay(self, retry_index: int) -> float:
        d = min(self.config.backoff_max, self.config.backoff_base * (2 ** retry_index))
        if self._jitter:
            d = d * (0.5 + random.random() / 2)   # 抖动：避免多个请求同时重试
        return d

    def invoke_message(self, prompt):
        """返回原始 AIMessage。失败按 classify_error 决定是否重试。"""
        attempts = 0
        while True:
            attempts += 1
            try:
                msg = self.model.invoke(prompt)
                bad = api_error_text(getattr(msg, "content", None))
                if bad is not None:
                    self.tracker.add_message(msg)
                    raise GatewayErrorContent(f"接口返回错误内容：{bad}")
            except Exception as e:  # noqa: BLE001
                kind, retryable = classify_error(e)
                if not retryable or attempts > self.config.max_retries:
                    raise LLMError(
                        f"LLM 调用失败（{kind}，共尝试 {attempts} 次）：{type(e).__name__}: {e}",
                        kind=kind, attempts=attempts, cause=e,
                    ) from e
                self.tracker.add_retry()
                self._sleep(self._delay(attempts - 1))
                continue
            self.tracker.add_message(msg)
            return msg

    def invoke(self, prompt) -> str:
        return self.invoke_message(prompt).content


_FENCE_RE = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\n(.*?)(?:\n[ \t]*```|\Z)", re.S | re.I)


def strip_code(text: str) -> str:
    """从模型输出中取出纯代码。

    - 有 ``` 代码块（哪怕前面有标题/说明文字）：取代码块内容，多个时取最长的一个；
    - 没有代码块：原样返回（去首尾空白）。
    """
    t = text.strip()
    blocks = [b.strip() for b in _FENCE_RE.findall(t)]
    blocks = [b for b in blocks if b]
    if blocks:
        return max(blocks, key=len)
    return t


def node_llm(config) -> LLMClient:
    """工作流节点取模型：优先用 analyze() 经 RunnableConfig 注入的 LLMClient；
    直接调用图（旧用法）时退回到按环境变量新建。"""
    conf = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    client = conf.get("llm")
    return client if client is not None else LLMClient(LLMConfig.from_env())
