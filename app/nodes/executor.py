"""执行节点。B07：result 保留结构化对象，另生成 result_text 预览；
数据表由 analyze() 读一次后经 RunnableConfig 注入，每次执行用副本（不再每次重试都读 CSV）。"""
import ast
import re

from app.core.result import format_result
from app.tools.dataset import copy_data, load_data
from app.tools.persist import new_chart_path
from app.tools.sandbox import run_code
from app.tools.sanity import result_issue


def _dataset(state, config):
    conf = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    df = conf.get("df")
    return copy_data(df) if df is not None else load_data(state["df_path"])[0]


TRUNCATED_CODE_ERROR = "模型输出被截断（达到输出长度上限），代码不完整，未执行"

# 修复批 1 F2：执行成功但答案没赋给 result（只留裸表达式），以前 executed=True、result=None 直接进
# summarizer（BACKLOG N6，corr_006）。按一次失败交给 reviewer。不自动把最后一个表达式当 result：
# 那是隐式行为，模型写错时会悄悄给出一个错的答案。
NO_RESULT_ERROR = ("代码执行成功，但没有把最终答案赋给变量 result（只写裸表达式或 print 不算答案）。"
                   "请把最终答案赋值给 result。")

# 修复批 1 F3：codegen 偶尔输出的是一段中文计划而不是代码（BACKLOG P14，mul_013），
# 执行只得到 SyntaxError: invalid character '，'，reviewer 再拿这段文字当「出错的代码」复述三次。
NOT_CODE_ERROR = "上一次输出的是一段文字说明，不是 Python 代码，未执行。请按分析计划重新写完整的 Python 代码。"

_INVALID_CHAR = re.compile(r"SyntaxError: invalid character '.' \(U\+([0-9A-F]{4,5})\)")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_QUOTED = re.compile(r"""("[^"\n]*"|'[^'\n]*')""")


def _is_wide(cp: int) -> bool:
    return 0x3000 <= cp <= 0x303F or 0x4E00 <= cp <= 0x9FFF or 0xFF00 <= cp <= 0xFFEF


def looks_like_prose(code: str, error: str) -> bool:
    """SyntaxError 由全角/中文字符引起，且至少两行、至少一半非注释行在引号之外含汉字 → 判为「不是代码」。
    第二个条件挡住「正常代码里混进一个全角逗号」：那种情况 reviewer 看着原代码改一个字符就好。"""
    m = _INVALID_CHAR.search(error or "")
    if not m or not _is_wide(int(m.group(1), 16)):
        return False
    lines = [ln.strip() for ln in (code or "").splitlines() if ln.strip()]
    if not lines:
        return False
    body = [ln for ln in lines if not ln.startswith("#")]
    prose = sum(1 for ln in body if _HAN.search(_QUOTED.sub("", ln.split(" #")[0])))
    return prose >= 2 and prose * 2 >= len(body)


def assigns_result(code: str) -> bool:
    """代码里有没有任何一处给 result 赋值（=、+=、注解赋值、for/with 目标、海象）。解析不了按「有」处理。"""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return True
    return any(isinstance(n, ast.Name) and n.id == "result" and isinstance(n.ctx, ast.Store)
               for n in ast.walk(tree))


def execute(state, config=None):
    cap = {}
    if state.get("truncated"):
        # V2d §3：半截代码不执行（执行只会得到一个掩盖原因的语法错误），按一次失败进 reviewer
        result, chart, error = None, None, TRUNCATED_CODE_ERROR
    else:
        chart_path = new_chart_path()
        df = _dataset(state, config)
        result, chart, error = run_code(
            state["code"], df, chart_path, timeout=state.get("exec_timeout", 20), capture=cap
        )

    not_code = False
    if error and looks_like_prose(state.get("code", ""), error):
        error, not_code = NOT_CODE_ERROR, True
    elif (not error and result is None and not chart and not cap.get("charts")
          and not assigns_result(state.get("code", ""))):
        error = NO_RESULT_ERROR

    # A2：成功但结果形态可疑（空表、全 NaN、inf）→ 记下来让路由送 reviewer 再看一遍，只给一次机会。
    # 不写进 error：重试用尽或预算到了时，这个结果照常交给 summarizer，不能因为「可疑」把它丢掉。
    sanity_issue = ""
    if not error and not state.get("sanity_retried"):
        sanity_issue = result_issue(result) or ""

    update = {
        "not_code": not_code,
        "sanity_issue": sanity_issue,
        "result": None if error else result,
        "result_text": "" if error else format_result(result),
        "chart_path": chart or "",
        "error": error or "",
        # M13（[26]）：chart() 的结构化图与统计，字段含义见 sandbox.run_code 的 capture
        "chart_options": cap.get("charts") or [],
        "chart_calls": cap.get("chart_calls", 0),
        "chart_errors": cap.get("chart_errors") or [],
        "chart_internal_errors": cap.get("chart_internal_errors") or [],
        "charts_discarded": cap.get("charts_discarded", 0),
        "chart_warnings": cap.get("chart_warnings") or [],
    }
    if sanity_issue:
        update["sanity_retried"] = True
    # 只记第一次执行的报错，用来区分"一次写对"与"reviewer 修好"
    if error and not state.get("initial_error") and state.get("attempts", 0) == 0:
        update["initial_error"] = error
    return update
