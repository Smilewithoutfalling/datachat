"""LLM 调用工程保护：显式超时、带退避的重试、token 统计（B10）。

两种 Agent 的处理方式不同，原因如下：
- 工作流版：节点通过 LLMClient.invoke 调模型。底层 ChatOpenAI 设 max_retries=0，
  重试完全由本模块控制（指数退避 + 抖动，只重试超时/限流/连接/5xx），每次重试记入 usage.retries。
- ReAct 版：自己的 StateGraph 循环（app/react_agent.py，B20）在 agent 节点里按同一份 LLMConfig
  重试（同样只重试超时/限流/连接/5xx），SDK max_retries=0，每次重试记入 usage.retries（B21）；
  token 通过回调 UsageCallbackHandler 统计。
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Callable, Optional

from langchain_core.callbacks import BaseCallbackHandler

# DeepSeek 提供 OpenAI 兼容接口，直接用 ChatOpenAI 指向其 base_url 即可。
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 阶段 6.5 §2a：4 种协议，都走 LangChain，共用 LLMClient 重试、classify_error、UsageTracker。
PROTOCOLS = ("openai_chat", "openai_responses", "azure", "anthropic")
ANTHROPIC_MAX_TOKENS = 8192          # Anthropic 的 max_tokens 必填；分析一步的回复远小于它


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
    # 阶段 6.5：协议与连接上的附加项。extra = {"quirks": {...已合并的怪癖}, "thinking": bool,
    # "deployment": Azure 部署名}；环境变量那条路径恒为 openai_chat + {}
    protocol: str = "openai_chat"
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_env(cls, **overrides) -> "LLMConfig":
        """从环境变量读取（.env 由入口脚本加载），再用 overrides 覆盖。
        api_key：环境变量 DEEPSEEK_API_KEY 优先，没有时读系统钥匙串（阶段 4，app/core/keystore.py）。"""
        from app.core.keystore import resolve_api_key
        env = {
            "model": os.getenv("DEEPSEEK_MODEL") or cls.model,
            "api_key": resolve_api_key()[0],
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
DEFAULT_TOKEN_BUDGET = 130_000   # V2d §2：单轮预算，ReAct 闸门实测最高 63,817 的约 2 倍
EST_CHARS_PER_TOKEN = 2          # V2d §2a：缺 usage 时按字符数估算（中文约 1 字 1 token、英文约 4 字符，宁可多算）


def token_budget() -> int:
    """单轮 token 预算：环境变量 DATACHAT_TOKEN_BUDGET，默认 DEFAULT_TOKEN_BUDGET；0 表示关闭。"""
    v = os.getenv("DATACHAT_TOKEN_BUDGET")
    try:
        return max(0, int(v)) if v not in (None, "") else DEFAULT_TOKEN_BUDGET
    except ValueError:
        return DEFAULT_TOKEN_BUDGET


def text_chars(x: Any) -> int:
    """提示词 / 消息列表 / 回复内容的字符数（估算 token 用）。"""
    if x is None:
        return 0
    if isinstance(x, str):
        return len(x)
    if isinstance(x, (list, tuple)):
        return sum(text_chars(m) for m in x)
    if isinstance(x, dict):
        return text_chars(x.get("text") or x.get("content"))
    content = getattr(x, "content", None)
    n = text_chars(content) if content is not None else len(str(x))
    for tc in getattr(x, "tool_calls", None) or []:
        n += len(str(tc.get("args") or ""))
    return n


def _est(chars: int) -> int:
    return -(-chars // EST_CHARS_PER_TOKEN)


def is_truncated(msg: Any) -> bool:
    """V2d §3：模型因达到输出长度上限而停。OpenAI 兼容口 finish_reason=length；阶段 6.5 起另认
    Anthropic 的 stop_reason=max_tokens 和 Responses API 的 incomplete_details.reason=max_output_tokens。"""
    meta = getattr(msg, "response_metadata", None) or {}
    inc = meta.get("incomplete_details") or {}
    return (meta.get("finish_reason") == "length" or meta.get("stop_reason") == "max_tokens"
            or (isinstance(inc, dict) and inc.get("reason") == "max_output_tokens"))


def message_text(msg: Any) -> str:
    """AIMessage 的文字部分。OpenAI Chat 回的是字符串；Responses API 和 Anthropic 回内容块列表
    （文字、推理、tool_use 混在一起），只取文字块拼起来。内容块本身不改：多轮工具调用要原样带回推理块。"""
    content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        return text
    return _flatten_content(content) if isinstance(content, list) else str(content)


class BudgetExceeded(RuntimeError):
    """V2d §2：本轮 token 用量（含预留）达到预算，由 service 走收尾通道，不是错误。"""

    def __init__(self, used: int, budget: int):
        super().__init__(f"本轮 token 用量达到上限（{used}/{budget}）")
        self.used, self.budget = used, budget


@dataclass
class TokenUsage:
    calls: int = 0                 # 成功的模型调用次数
    input_tokens: int = 0          # 以下四项只累加服务商返回的真数
    output_tokens: int = 0
    total_tokens: int = 0
    retries: Optional[int] = 0     # 本模块执行的重试次数；ReAct 版由 SDK 内部重试，无法计数时为 None
    # 是否每次调用都拿到了 usage（假模型/不返回 usage 的服务为 False）；一次调用都没有时为 None（V2d §1）
    reported: Optional[bool] = None
    # V2d §1：服务商在 input/output_token_details 里给了才有值；None = 没上报（不是 0）
    cache_read_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    # V2d §2a：缺 usage 的调用按字符数估算的量（不混进上面的真数）；estimated = 至少一次是估算的
    estimated_tokens: int = 0
    estimated: bool = False
    budget: int = 0                # 本轮预算（0 = 关闭）
    budget_hit: bool = False       # 本轮因预算提前收尾

    @property
    def counted(self) -> int:
        """预算口径：真数 + 估算。"""
        return self.total_tokens + self.estimated_tokens


class UsageTracker:
    """线程安全的累加器，每次 analyze() 新建一个。budget>0 时供 over_budget() 判定（V2d §2）。"""

    def __init__(self, budget: int = 0):
        self._lock = threading.Lock()
        self.usage = TokenUsage(budget=max(0, int(budget or 0)))
        self._last_input = 0

    def add_message(self, msg: Any, input_chars: int | None = None) -> None:
        meta = getattr(msg, "usage_metadata", None) or {}
        with self._lock:
            u = self.usage
            u.calls += 1
            if not meta:
                u.reported = False
                ei = _est(input_chars or 0)
                u.estimated_tokens += ei + _est(text_chars(msg))
                u.estimated = True
                self._last_input = ei
                return
            if u.reported is None:
                u.reported = True
            i = int(meta.get("input_tokens") or 0)
            o = int(meta.get("output_tokens") or 0)
            u.input_tokens += i
            u.output_tokens += o
            u.total_tokens += int(meta.get("total_tokens") or (i + o))
            self._last_input = i
            cr = (meta.get("input_token_details") or {}).get("cache_read")
            if cr is not None:
                u.cache_read_tokens = (u.cache_read_tokens or 0) + int(cr)
            rs = (meta.get("output_token_details") or {}).get("reasoning")
            if rs is not None:
                u.reasoning_tokens = (u.reasoning_tokens or 0) + int(rs)

    def add_retry(self) -> None:
        with self._lock:
            if self.usage.retries is not None:
                self.usage.retries += 1

    def over_budget(self) -> bool:
        """下一次调用之前判定：已用 + 预留 ≥ 预算。预留 = 最近一次调用的输入量（收尾那次调用大致这么大），
        这样超限后的收尾调用也落在预算内（V2d §2b）。"""
        with self._lock:
            u = self.usage
            return bool(u.budget) and u.counted + self._last_input >= u.budget

    def mark_budget_hit(self) -> None:
        with self._lock:
            self.usage.budget_hit = True

    def check_budget(self) -> None:
        if self.over_budget():
            self.mark_budget_hit()
            raise BudgetExceeded(self.usage.counted, self.usage.budget)

    def snapshot(self) -> TokenUsage:
        with self._lock:
            return replace(self.usage)


class UsageCallbackHandler(BaseCallbackHandler):
    """ReAct 版用：挂在 agent.invoke 的 callbacks 上，每次模型返回时记 token。
    开始时记下输入字符数，服务商不回 usage 时用来估算（V2d §2a）。"""

    def __init__(self, tracker: UsageTracker):
        self.tracker = tracker
        self._input_chars: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):  # noqa: D401
        self._input_chars[run_id] = text_chars(messages)

    def on_llm_end(self, response, *, run_id=None, **kwargs):  # noqa: D401
        chars = self._input_chars.pop(run_id, None)
        for gens in response.generations:
            for g in gens:
                self.tracker.add_message(getattr(g, "message", None), input_chars=chars)


# ---------------------------------------------------------------- 错误分类
class LLMError(RuntimeError):
    """重试用尽或遇到不可重试错误后抛出。kind 便于上层区分"基础设施失败"和"答错"。"""

    def __init__(self, message: str, *, kind: str, attempts: int, cause: BaseException | None = None,
                 upstream: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts
        self.cause = cause
        # T11：上游 error.message 原文（未剥离）。用户可见文案由 service.py 经 user_error 生成，
        # 回显剥离要用到问题原文，只有 service.py 的作用域里有
        self.upstream = upstream


_TRUNCATED_ERROR_RE = re.compile(r'^\{\s*"(message|error|detail|msg)"\s*:\s*"([^"\\]*)"?\s*\}?$')
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
    if not t.startswith("{"):
        return None
    try:
        obj = json.loads(t)
    except Exception:
        # B62：网关的错误 JSON 可能被截断，如 '{"message":"prompt 必须包含字符串内容'（闸门 s15）。
        # 整段只有一个错误键、值是没闭合的字符串时也认作错误。
        m = _TRUNCATED_ERROR_RE.match(t)
        return (m.group(2) or m.group(1)) if m else None
    if not isinstance(obj, dict) or not obj or not set(obj) <= _API_ERROR_KEYS:
        return None
    err = obj.get("error")
    if isinstance(err, dict):
        err = err.get("message") or json.dumps(err, ensure_ascii=False)
    msg = obj.get("message") or err or obj.get("detail") or obj.get("msg")
    return str(msg) if msg else None


class GatewayErrorContent(Exception):
    """模型接口返回了错误 JSON 而不是回复（B45）。按短暂故障处理，可重试。"""


def _sdk_modules():
    """openai 和 anthropic 两个 SDK（异常类同名同构：都由 Stainless 生成）。没装的跳过。"""
    mods = []
    for name in ("openai", "anthropic"):
        try:
            mods.append(__import__(name))
        except Exception:  # pragma: no cover
            pass
    return mods


def classify_error(exc: BaseException) -> tuple[str, bool]:
    """返回 (kind, 是否可重试)。只重试短暂性故障；鉴权/参数错误重试无意义。
    阶段 6.5：anthropic SDK 的异常按同一张表分（529 overloaded 是 5xx → server，可重试）。"""
    for sdk in _sdk_modules():
        if isinstance(exc, sdk.APITimeoutError):
            return "timeout", True
        if isinstance(exc, sdk.APIConnectionError):
            return "connection", True
        if isinstance(exc, sdk.RateLimitError):
            return "rate_limit", True
        if isinstance(exc, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
            return "auth", False
        if isinstance(exc, (sdk.BadRequestError, sdk.NotFoundError, sdk.UnprocessableEntityError)):
            return "bad_request", False
        if isinstance(exc, sdk.APIStatusError):
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
def quirks_of(cfg: LLMConfig) -> dict:
    from app.core.providers import QUIRK_KEYS
    q = (cfg.extra or {}).get("quirks") or {}
    return {k: q.get(k) for k in QUIRK_KEYS}


def thinking_body(cfg: LLMConfig) -> Optional[dict]:
    """thinking_param 怪癖（§2c）：Qwen 一类用 enable_thinking，GLM / 方舟一类用 thinking={type}。默认关思考，
    连接上 extra.thinking=true 才开。没设 thinking_param 时什么都不发（不猜服务商认不认）。"""
    tp = quirks_of(cfg).get("thinking_param")
    on = bool((cfg.extra or {}).get("thinking"))
    if tp == "enable_thinking":
        return {"enable_thinking": on}
    if tp == "thinking":
        return {"thinking": {"type": "enabled" if on else "disabled"}}
    return None


def _flatten_content(content):
    if not isinstance(content, list):
        return content
    return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content
                   if isinstance(p, str) or (isinstance(p, dict) and p.get("type", "text") == "text"))


@lru_cache(maxsize=None)
def _quirk_class(base_name: str):
    """ChatOpenAI 的子类，承载三个改请求体的怪癖。只改 Chat Completions 的 messages；
    Responses API 的请求体结构不同，这三个怪癖对它不生效（预设里也没有 Responses 协议的服务商开它们）。"""
    from langchain_core.messages import AIMessage
    from langchain_openai import ChatOpenAI

    base = {"ChatOpenAI": ChatOpenAI}[base_name]

    class _Quirky(base):  # type: ignore[misc, valid-type]
        dc_no_stream_options: bool = False   # 不发 stream_options（流式时 SDK 会加 include_usage，有的网关 400）
        dc_no_array_content: bool = False    # content 只发字符串（有的网关不认分段 content）
        dc_reasoning_replay: bool = False    # 多轮工具调用时把 reasoning_content 带回去（DeepSeek 推理模型一类）

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if self.dc_no_stream_options:
                payload.pop("stream_options", None)
            msgs = payload.get("messages")
            if not isinstance(msgs, list):
                return payload
            if self.dc_no_array_content:
                for m in msgs:
                    if isinstance(m, dict) and isinstance(m.get("content"), list):
                        m["content"] = _flatten_content(m["content"])
            if self.dc_reasoning_replay:
                src = self._convert_input(input_).to_messages()   # 与 payload["messages"] 一一对应（见父类实现）
                for lm, pm in zip(src, msgs):
                    rc = lm.additional_kwargs.get("reasoning_content") if isinstance(lm, AIMessage) else None
                    if rc and isinstance(pm, dict) and pm.get("role") == "assistant":
                        pm["reasoning_content"] = rc
            return payload

        def _create_chat_result(self, response, generation_info=None):
            result = super()._create_chat_result(response, generation_info)
            if self.dc_reasoning_replay:
                d = response if isinstance(response, dict) else response.model_dump()
                for gen, ch in zip(result.generations, d.get("choices") or []):
                    rc = ((ch or {}).get("message") or {}).get("reasoning_content")
                    if rc:
                        gen.message.additional_kwargs["reasoning_content"] = rc
            return result

    _Quirky.__name__ = _Quirky.__qualname__ = f"Datachat{base_name}"
    return _Quirky


def build_chat_model(cfg: LLMConfig, *, sdk_retries: int | None = 0, max_tokens: int | None = None):
    """按协议构建 LangChain ChatModel（§2a）。超时总是显式传入；sdk_retries 默认 0（由 LLMClient 重试）。
    缺 Key 时用占位串，让请求以 401 失败，而不是构建时崩溃。"""
    key = cfg.api_key or "missing-api-key"
    if cfg.protocol == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=cfg.model, api_key=key, base_url=cfg.base_url or None,
                             temperature=cfg.temperature, default_request_timeout=cfg.timeout,
                             max_retries=2 if sdk_retries is None else sdk_retries,
                             max_tokens=max_tokens or ANTHROPIC_MAX_TOKENS)
    if cfg.protocol not in PROTOCOLS:
        raise ValueError(f"未知协议 {cfg.protocol!r}，可选 {PROTOCOLS}")
    q = quirks_of(cfg)
    kw: dict = dict(model=cfg.model, api_key=key, temperature=cfg.temperature, timeout=cfg.timeout,
                    max_retries=sdk_retries)
    if max_tokens is not None:
        kw["max_tokens"] = max_tokens
    body = thinking_body(cfg)
    if body:
        kw["extra_body"] = body
    flags = dict(dc_no_stream_options=bool(q.get("no_stream_options")),
                 dc_no_array_content=bool(q.get("no_array_content")),
                 dc_reasoning_replay=bool(q.get("reasoning_replay")))
    if flags["dc_no_stream_options"]:
        kw["stream_usage"] = False
    base_url = cfg.base_url
    if cfg.protocol == "azure":
        # Azure v1 路径（learn.microsoft.com/azure/ai-foundry/openai/api-version-lifecycle）：普通 OpenAI 客户端 +
        # {资源}/openai/v1/，不再需要 api-version；model 填部署名。
        base_url = azure_v1_url(cfg.base_url)
        kw["model"] = (cfg.extra or {}).get("deployment") or cfg.model
    if cfg.protocol == "openai_responses":
        kw["use_responses_api"] = True
    if any(flags.values()):
        return _quirk_class("ChatOpenAI")(base_url=base_url, **kw, **flags)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(base_url=base_url, **kw)


def azure_v1_url(url: str) -> str:
    """资源地址 → v1 地址；已经带 /openai/v1 的原样保留。"""
    u = (url or "").rstrip("/")
    return u if u.endswith("/openai/v1") else u + "/openai/v1"


# 设置页「测试连接」（阶段 5 收尾 C）：一条固定的 user 消息、max_tokens=1、不重试、超时最多 15 秒。
# tests/fake_llm.py 的 MARK_PING 认这条消息（改了这里，fake 认不出 → 400，tests/test_settings_test.py 的 ok 那条红）。
PING_MESSAGE = "ping"
PING_TIMEOUT_MAX = 15.0
# Responses API 的 max_output_tokens 下限是 16（OpenAI 文档），1 会被 400；其余协议仍用 1
PING_MAX_TOKENS = {"openai_responses": 16}
# 阶段 6.5 §2d 第 2 步：只有一个工具、tool_choice 强制调用它，看回复里有没有这个 tool_call。
# tests/fake_llm.py 的 MARK_PROBE_TOOL 认这个工具名
PROBE_TOOL = "datachat_probe"
PROBE_MESSAGE = "连接测试：请调用 datachat_probe 工具，参数 ok=true。"
PROBE_MAX_TOKENS = 64


def _wrap_error(e: BaseException, what: str) -> "LLMError":
    from app.core.errors import upstream_message
    kind, _ = classify_error(e)
    up = upstream_message(e)
    if isinstance(e, GatewayErrorContent):
        up = f"接口返回错误内容：{up}"
    return LLMError(f"{what}失败（{kind}）：{type(e).__name__}: {e}", kind=kind, attempts=1, cause=e, upstream=up)


def _short(cfg: LLMConfig) -> LLMConfig:
    return replace(cfg, timeout=min(cfg.timeout, PING_TIMEOUT_MAX))


def ping(cfg: LLMConfig) -> None:
    """用 cfg 发一次最小请求。成功返回 None；失败抛 LLMError（kind 取 classify_error，upstream 是上游 message 原文）。
    不重试（max_retries=0），不经 LLMClient 的退避；调用方负责"没 Key 不发请求"。按协议分发（build_chat_model）。"""
    from langchain_core.messages import HumanMessage

    model = build_chat_model(_short(cfg), sdk_retries=0, max_tokens=PING_MAX_TOKENS.get(cfg.protocol, 1))
    try:
        msg = model.invoke([HumanMessage(content=PING_MESSAGE)])
        bad = api_error_text(message_text(msg))
        if bad is not None:
            raise GatewayErrorContent(bad)
    except Exception as e:  # noqa: BLE001
        raise _wrap_error(e, "测试连接") from e


def probe_tools(cfg: LLMConfig) -> bool:
    """§2d 第 2 步：返回回复里有没有 PROBE_TOOL 的 tool_call。请求本身失败抛 LLMError（调用方决定怎么记）。"""
    from langchain_core.messages import HumanMessage

    tool = {"type": "function", "function": {
        "name": PROBE_TOOL, "description": "连接测试用的工具，调用即可",
        "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}
    model = build_chat_model(_short(cfg), sdk_retries=0, max_tokens=PROBE_MAX_TOKENS)
    try:
        msg = model.bind_tools([tool], tool_choice=PROBE_TOOL).invoke([HumanMessage(content=PROBE_MESSAGE)])
    except Exception as e:  # noqa: BLE001
        raise _wrap_error(e, "工具调用测试") from e
    return any((tc or {}).get("name") == PROBE_TOOL for tc in getattr(msg, "tool_calls", None) or [])


MODELS_TIMEOUT = 10.0


def list_models(cfg: LLMConfig, timeout: float | None = None) -> list[str]:
    """读服务商的模型列表：OpenAI 兼容口 GET {base_url}/models，Anthropic GET /v1/models。不重试，超时 timeout 秒。
    失败抛 LLMError。Azure 列的是部署而不是模型，不支持（调用方退回预设）。"""
    key = cfg.api_key or "missing-api-key"
    timeout = MODELS_TIMEOUT if timeout is None else timeout
    try:
        if cfg.protocol == "anthropic":
            import anthropic
            cl = anthropic.Anthropic(api_key=key, base_url=cfg.base_url or None, timeout=timeout, max_retries=0)
            ids = [m.id for m in cl.models.list(limit=1000)]
        elif cfg.protocol == "azure":
            raise ValueError("Azure 按部署调用，不支持列出模型")
        else:
            import openai
            cl = openai.OpenAI(api_key=key, base_url=cfg.base_url, timeout=timeout, max_retries=0)
            ids = [m.id for m in cl.models.list()]
    except Exception as e:  # noqa: BLE001
        raise _wrap_error(e, "获取模型列表") from e
    return sorted({str(i) for i in ids if i})


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
                bad = api_error_text(message_text(msg))
                if bad is not None:
                    self.tracker.add_message(msg, input_chars=text_chars(prompt))
                    raise GatewayErrorContent(bad)
            except Exception as e:  # noqa: BLE001
                kind, retryable = classify_error(e)
                if not retryable or attempts > self.config.max_retries:
                    from app.core.errors import upstream_message
                    up = upstream_message(e)
                    if isinstance(e, GatewayErrorContent):
                        up = f"接口返回错误内容：{up}"
                    # message 只给日志看（不进界面）；界面文案由 service.py 经 user_error 生成（T11）
                    raise LLMError(
                        f"LLM 调用失败（{kind}，共尝试 {attempts} 次）：{type(e).__name__}: {e}",
                        kind=kind, attempts=attempts, cause=e, upstream=up,
                    ) from e
                self.tracker.add_retry()
                self._sleep(self._delay(attempts - 1))
                continue
            self.tracker.add_message(msg, input_chars=text_chars(prompt))
            return msg

    def invoke(self, prompt) -> str:
        return message_text(self.invoke_message(prompt))

    def invoke_checked(self, prompt) -> tuple[str, bool]:
        """返回 (文本, 是否被输出长度上限截断)（V2d §3）。"""
        msg = self.invoke_message(prompt)
        return message_text(msg), is_truncated(msg)


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
