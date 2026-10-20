"""T11：到达界面的错误文案的唯一出口（规则见 docs/roadmap/phase5-frontend.md「T11 错误文案脱敏」）。

纳入按生成点算：凡经 user_error 生成的串都已脱敏，不管落在 res.error、Step.error 还是非致命 error 事件。
沙箱 exec 原文（模型代码在用户自己数据上的 traceback）一律不经这里，按 T9 只当文本渲染。
原始异常（类型名、原文、堆栈）只按 trace_id 写进 server.log。
"""
from __future__ import annotations

import logging
import re

from app.core.text import CONTROL_CHARS

logger = logging.getLogger("datachat.errors")

MAX_LEN = 200          # 文案正文上限（不含编号）
ECHO_MIN = 4           # 用户问题整串剥离：问题至少这么长才判
ECHO_PREFIX_MIN = 12   # 截断回显：问题前缀至少这么长才判
ELLIPSIS = "…"

# 文案只写详情，种类由 error_kind 承担：界面渲染成「{KIND}失败：{文案}」（TurnView.tsx KIND），
# 所以这里不再写"失败""LLM 调用"这类种类前缀（S 10-20 第三轮）
AGENT_MESSAGE = "内部错误"
DICTIONARY_MESSAGE = "数据字典读取失败，已跳过"
NO_EXEC_MESSAGE = "模型没有执行代码，也没有按契约拒答"
# classify_error 的内部枚举 → 中文。不在表里的（unknown）省略；http_NNN 写成「HTTP NNN」
LLM_KIND_TEXT = {
    "timeout": "请求超时", "connection": "连不上模型服务", "rate_limit": "请求太频繁，被限流",
    "auth": "鉴权失败，请检查 API Key", "bad_request": "请求被模型服务拒绝", "server": "模型服务出错",
    "gateway_error": None,   # 上游原文已以「接口返回错误内容：」开头，不重复
    "unknown": None,
}


class UserText(str):
    """经 user_error 生成（或 F2 常量）的界面文案。Emitter.error 断言 message 是它（exec 原文除外），
    谁写个裸 f-string 塞进 error 事件，测试当场红在那一行。"""


def llm_kind_text(kind: str) -> str | None:
    if kind in LLM_KIND_TEXT:
        return LLM_KIND_TEXT[kind]
    m = re.fullmatch(r"http_(\d{3})", kind or "")
    return f"HTTP {m.group(1)}" if m else None

_KEY = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_URL_QUERY = re.compile(r"(https?://[^\s?#\"'<>]+)\?[^\s\"'<>]*")
_WIN_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"'<>，。；：）)\]]*")
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>，。；：）)\]]+")
_POSIX_PATH = re.compile(r"(?<![\w.:/])/(?:[\w.\-~]+/)+[\w.\-~]*")
_PARSER_LINE = re.compile(r"line (\d+)")


def trace_code(trace_id: str | None) -> str:
    return (trace_id or "")[:8]


def _with_code(text: str, trace_id: str | None) -> UserText:
    if len(text) > MAX_LEN:          # 正文（含 kind 标签）总长不超过 MAX_LEN，编号另计
        text = text[:MAX_LEN - 1] + ELLIPSIS
    code = trace_code(trace_id)
    return UserText(f"{text}（编号 {code}）" if code else text)


def scrub(text: str, question: str | None = None) -> str:
    """上游原文的四步之 (b)(c)(d)：剥用户问题回显 → 打码 Key / 带 query 的 URL / 路径 → 洗控制符并截断。"""
    t = str(text)
    q = (question or "").strip()
    if len(q) >= ECHO_MIN and q in t:
        t = t.replace(q, ELLIPSIS)
    if len(q) > ECHO_PREFIX_MIN:
        for n in range(len(q) - 1, ECHO_PREFIX_MIN - 1, -1):
            if q[:n] in t:
                t = t.replace(q[:n], ELLIPSIS)
                break
    t = _KEY.sub("sk-***", t)
    t = _URL_QUERY.sub(lambda m: m.group(1) + "?" + ELLIPSIS, t)
    t = _UNC_PATH.sub("<路径>", t)
    t = _WIN_PATH.sub("<路径>", t)
    t = _POSIX_PATH.sub("<路径>", t)
    t = CONTROL_CHARS.sub("", t).strip()
    if len(t) > MAX_LEN:
        t = t[:MAX_LEN - 1] + ELLIPSIS
    return t


def upstream_message(exc: BaseException | None) -> str | None:
    """四步之 (a)：只取上游的 error.message，不要异常 repr。拿不到就返回 None（只显示 kind）。"""
    if exc is None:
        return None
    up = getattr(exc, "upstream", None)
    if up:
        return str(up)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg") or err.get("detail")
        else:
            msg = err if isinstance(err, str) else body.get("message")
        if msg:
            return str(msg)
    if type(exc).__name__ == "GatewayErrorContent":
        return str(exc)
    cause = getattr(exc, "cause", None) or exc.__cause__
    if cause is not None and cause is not exc:
        return upstream_message(cause)
    return None


def dataset_message(exc: BaseException) -> str:
    """dataset 已知异常 → 常量文案（不带路径、类型名）；未知 → 「无法读取文件」。"""
    from app.tools.dataset import DatasetError, TableReadError
    if isinstance(exc, TableReadError):
        inner = exc.__cause__ if exc.__cause__ is not None else Exception()
        return f"表 {CONTROL_CHARS.sub('', exc.filename or '')}：{dataset_message(inner)}"
    if isinstance(exc, DatasetError):
        return CONTROL_CHARS.sub("", str(exc))
    from app.tools.csv_io import CSVEncodingError
    try:
        from pandas.errors import EmptyDataError, ParserError
    except Exception:  # pragma: no cover
        EmptyDataError = ParserError = ()  # type: ignore[assignment]
    if isinstance(exc, FileNotFoundError):
        return "数据文件不见了，请重新上传"
    if isinstance(exc, CSVEncodingError):
        s = str(exc)   # 我们自己的文案；指定编码那条后半是 UnicodeDecodeError 原文，只留前半
        return s.split("：")[0] if s.startswith("文件不能用指定编码") else s
    # 顺序：精确类在前、宽类兜底在后。CSVEncodingError / EmptyDataError / ParserError 都是 ValueError，
    # EmptyDataError 不是 ParserError 的子类（pandas 3 实测）；UnicodeDecodeError 也是 ValueError。
    # 每条都有只属于它的异常构造测试（test_t11_errors::test_dataset_message_order）
    if EmptyDataError and isinstance(exc, EmptyDataError):
        return "文件是空的"
    if ParserError and isinstance(exc, ParserError):
        m = _PARSER_LINE.search(str(exc))
        return f"CSV 第 {m.group(1)} 行无法解析" if m else "CSV 无法解析"
    if isinstance(exc, UnicodeDecodeError):
        return "无法识别文件编码"
    return "无法读取文件"


def user_error(kind: str, src, *, trace_id: str | None, question: str | None = None,
               prefix: str | None = None, context: str = "") -> UserText:
    """生成到界面的错误串，并把原始异常按 trace_id 写进日志。末尾统一追加（编号 xxxxxxxx）。

    kind：
      dataset    src 是异常 → dataset_message
      dictionary src 是异常 → 常量「数据字典读取失败，已跳过」
      llm        src 是异常（LLMError 或 langchain 直接抛的 openai 异常）→「{中文原因}，共尝试 n 次：上游 message」
      upstream   src 是上游原文（网关错误 JSON 里的 message）→ prefix + 四步处理后的原文
      agent      src 是异常 → 常量「内部错误」（界面前面有「分析流程失败：」）
      text       src 是我们自己生成的文案 → 只洗控制符
    """
    # context：没有 trace_id 可依的调用方（数据集预览）给上 dataset id + 文件名，日志查下去才有上下文
    ctx = f" {context}" if context else ""
    if isinstance(src, BaseException):
        logger.warning("user_error trace=%s kind=%s%s: %s: %s", trace_id, kind, ctx, type(src).__name__, src,
                       exc_info=(type(src), src, src.__traceback__))
    elif kind == "upstream":
        logger.warning("user_error trace=%s kind=%s%s: %s", trace_id, kind, ctx, str(src)[:2000])
    if kind == "dataset":
        text = dataset_message(src)
    elif kind == "dictionary":
        text = DICTIONARY_MESSAGE
    elif kind == "llm":
        from app.core.llm import classify_error
        lk = getattr(src, "kind", None) or classify_error(src)[0]
        attempts = getattr(src, "attempts", None)
        parts = [p for p in (llm_kind_text(lk), f"共尝试 {attempts} 次" if attempts else None) if p]
        label = "，".join(parts)
        up = upstream_message(src)
        body = scrub(up, question) if up else ""
        text = f"{label}：{body}" if label and body else (body or label or "模型调用出错")
    elif kind == "upstream":
        body = scrub(str(src), question)
        text = f"{prefix or ''}{body}"
    elif kind == "agent":
        text = AGENT_MESSAGE
    else:
        text = CONTROL_CHARS.sub("", str(src)).strip()
    return _with_code(text, trace_id)

