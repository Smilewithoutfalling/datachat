"""结果表导出与代码导出（阶段 7.5 第 2 步，docs/roadmap/phase75-assess.md 第 40 行）。

代码导出（build_script）：把一轮分析最终执行的代码拼成一个**独立的 .py**，在不装 DataChat 的干净 venv
（只有 pandas、matplotlib、openpyxl）里能重跑出同一个 result。原因见验收：沙箱
（app/tools/sandbox_worker.py:205-220）会注入 df / dfs / pd / np / plt / chart_path / chart、重定向
plt.savefig，所以「在本机直接跑通」不算数——导出文件自带：
  ① 头部注释：来源会话、问题、数据集文件名与 sha256；
  ② 数据加载：读数规则与 DataChat 一致（app/tools/export_runtime.py 的源码原样嵌入），数据目录是顶部常量；
  ③ 注入 df（单表）或 dfs（多表），与沙箱同一判据（读出来是 dict 就是 dfs）；
  ④ chart()：只依赖 pandas + matplotlib 的最小实现，每张图落一张 PNG；
  ⑤ plt.savefig：与沙箱一样，不管传什么文件名都落到 chart_path（脚本旁的 <脚本名>_plt.png），
     代码结束时还有打开的图也存一次（同 sandbox_worker.py:236-237）；
  ⑥ 末尾打印 result。
导出文件里没有 `import app`（tests/test_export.py 在 `import app` 会失败的 venv 里跑它来证明）。

代码来源：消息 result_json 里的 `code`（AnalysisResult.code）。多步时以「最后一次执行成功、给出 result 的那段代码」
为准：工作流是 state["code"]（app/core/service.py:402，executed 为真说明最后一次执行成功），ReAct 是最后一次成功
执行的代码（app/core/service.py:720）。每次执行都在新进程里、从 load_data 重新读数据（app/nodes/executor.py:16、
app/react_agent.py:208），不依赖前几步的变量，所以单独这一段就能重现 result。

安全：沙箱里能「成功」的代码，可能把被拦下的操作包在 try 里（读写文件、起进程），拿到本机直接跑就不再有沙箱。
所以导出前做一次静态检查（unsafe_reasons），命中就拒绝导出、说明原因。这不是沙箱，只是不把沙箱拦过的东西原样交出去。

结果表导出（result_table / to_csv_bytes / to_xlsx_bytes）：result 不存库（AnalysisResult.to_record 只留 result_text，
app/core/result.py:81），所以导出时用同一段代码、同一份数据在沙箱里重跑一次拿到原对象；重跑结果的文本预览与库里的
result_text 不一致时（代码里有随机数、取了当天日期等），接口如实报出 matches_original=false。
"""
from __future__ import annotations

import ast
import io
import os
import re

import numpy as np
import pandas as pd

from app.tools.sandbox_caps import CAPS

RUNTIME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_runtime.py")
_RUNTIME_BEGIN = "# ===================== DataChat 导出运行时（开始） ====================="

XLSX_MAX_ROWS = 1_048_576
XLSX_MAX_COLS = 16_384

_COMMENT_DROP = re.compile("[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")

# 沙箱靠审计钩子拦、导出后不再有人拦的东西：读写文件、起进程、ctypes。按属性名 / 函数名静态判。
_UNSAFE_ATTRS = frozenset({
    "to_csv", "to_excel", "to_pickle", "to_parquet", "to_feather", "to_hdf", "to_sql", "to_stata", "to_orc",
    "to_clipboard", "to_json", "to_html", "to_latex", "to_xml", "to_markdown", "tofile",
    "save", "savez", "savez_compressed", "savetxt", "load", "loadtxt", "genfromtxt", "fromfile", "memmap",
    "system", "popen", "spawn", "ctypeslib", "ctypes", "rcdefaults", "rc_file", "rc_file_defaults",
})


_DANGEROUS_BUILTINS = frozenset({"open", "eval", "exec", "compile", "globals", "locals", "vars", "getattr", "setattr",
                                 "delattr", "breakpoint", "memoryview"})


class ExportError(ValueError):
    """导出失败，文案是给用户看的中文。"""


# ---------------------------------------------------------------- 安全检查
def unsafe_reasons(code: str) -> list[str]:
    """导出前的静态检查：import 白名单、沙箱不给的危险内建函数（open / eval / getattr …）、双下划线属性、
    读写文件 / 起进程类调用。只为不把沙箱拦过的操作原样交出去，不是沙箱。"""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return ["代码无法解析"]
    out = []
    # 只查危险的那几个内建（沙箱不给、导出后能读写文件 / 执行任意代码）。id、type、format 这类常被拿来当变量名的
    # 内建沙箱也不给，但不危险，不查，免得误伤。危险名哪怕代码里赋过值也查（`open = open` 这种写法不放过）。
    forbidden = (_DANGEROUS_BUILTINS & CAPS.forbidden_builtins) | {"__import__", "__builtins__"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""] if n.level == 0 else ["（相对导入）"]
        else:
            mods = []
        for m in mods:
            if m.split(".")[0] not in CAPS.allowed_imports:
                out.append(f"导入了沙箱不允许的模块 {m}")
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in forbidden:
            out.append(f"用了沙箱不提供的内置函数 {n.id}")
        elif isinstance(n, ast.Attribute):
            if n.attr.startswith("__") and n.attr.endswith("__"):
                out.append(f"访问了双下划线属性 {n.attr}")
            elif n.attr in _UNSAFE_ATTRS or n.attr.startswith("read_"):
                out.append(f"调用了读写文件或系统的 {n.attr}")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 代码导出
def _comment(s, limit: int = 300) -> str:
    """进注释的文本：去掉换行等控制符和方向控制符（换行会让后面的文字逃出注释变成代码）、限长。"""
    s = _COMMENT_DROP.sub(" ", str(s or "")).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def runtime_source() -> str:
    """export_runtime.py 去掉模块说明后的源码（从「运行时（开始）」那一行起）。
    打包版里它是数据文件（packaging/build_sidecar.py 的 --add-data），不在时明确报错，不生成残缺脚本。"""
    try:
        with open(RUNTIME_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise ExportError("缺少导出运行时文件，安装包可能不完整") from e
    i = text.index(_RUNTIME_BEGIN)
    return text[i:].rstrip() + "\n"


def build_script(code: str, *, files: list[tuple[str, str | None]], data_dir: str, multi_source: bool,
                 meta: dict | None = None) -> str:
    """生成独立脚本的文本。

    files：[(文件名, sha256 或 None)]，只含数据表文件（字典 *.dict.csv 只进 prompt，不影响取值，不列）。
    data_dir：数据文件所在目录（脚本顶部常量，可改；找不到时再找脚本所在目录）。
    multi_source：数据集是不是多个文件（是 → 一律 dfs，同 load_data 对目录的处理）。
    meta：session_id / session_title / message_id / question / dataset_name / exported_at / agent，只进注释。
    """
    if not files:
        raise ExportError("数据集里没有数据表文件")
    meta = meta or {}
    body = (code or "").replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    head = [
        "# -*- coding: utf-8 -*-",
        "# DataChat 导出的分析脚本：独立运行，不需要安装 DataChat。",
        "# 依赖：Python 3.11+、pandas、numpy、matplotlib、openpyxl（只读 CSV 时用不到 openpyxl）。",
        "# 运行：python 本脚本.py —— 末尾打印 result；图保存在本脚本旁边（<脚本名>_plt.png、<脚本名>_chart1.png …）。",
        "#",
        f"# 来源会话：{_comment(meta.get('session_title')) or '（未命名）'}"
        f"（会话 {_comment(meta.get('session_id'), 64)}，消息 {_comment(meta.get('message_id'), 64)}）",
    ]
    if meta.get("question"):
        head.append(f"# 问题：{_comment(meta['question'])}")
    if meta.get("agent"):
        head.append(f"# 分析方式：{_comment(meta['agent'], 32)}")
    if meta.get("exported_at"):
        head.append(f"# 导出时间：{_comment(meta['exported_at'], 64)}")
    head.append(f"# 数据集：{_comment(meta.get('dataset_name')) or '（未命名）'}")
    for name, sha in files:
        head.append(f"#   {_comment(name, 255)}  sha256={_comment(sha, 64) if sha else '（未知）'}")
    head += [
        "#",
        "# 与在 DataChat 里运行的差别：DataChat 在沙箱里执行（受限的内置函数、不能读写文件），这里没有沙箱；",
        "# 图的样式与界面上不同，数字取自同一个 result。数据文件与导出时不同（sha256 不一致）时会在开头提示。",
        "",
        "# ---------------- 可以改的设置 ----------------",
        f"DATA_DIR = {data_dir!r}          # 数据文件所在目录；找不到时再找本脚本所在目录",
        f"DATA_FILES = {[(n, s) for n, s in files]!r}   # (文件名, 导出时的 sha256)",
        f"MULTI_SOURCE = {bool(multi_source)!r}        # 数据集由多个文件组成（代码里用 dfs）",
        "CHECK_SHA256 = True          # 读数据前核对文件是否与导出时相同（只提示，不中断）",
        "",
    ]
    tail = [
        "",
        "# ---------------- 准备运行环境（与 DataChat 沙箱一致） ----------------",
        "import matplotlib",
        "matplotlib.use(\"Agg\")",
        "import matplotlib.pyplot as plt",
        "",
        "_dc_setup_matplotlib()",
        "_DC_SCRIPT_DIR = _dc_os.path.dirname(_dc_os.path.abspath(__file__))",
        "_DC_STEM = _dc_os.path.splitext(_dc_os.path.basename(__file__))[0]",
        "chart_path = _dc_os.path.join(_DC_SCRIPT_DIR, _DC_STEM + \"_plt.png\")",
        "_dc_orig_savefig = plt.savefig",
        "",
        "",
        "def _dc_redirect_savefig(*args, **kwargs):",
        "    \"\"\"同 DataChat 沙箱：plt.savefig 不管传什么文件名，都存到 chart_path。\"\"\"",
        "    kwargs.pop(\"fname\", None)",
        "    return _dc_orig_savefig(chart_path, **kwargs)",
        "",
        "",
        "plt.savefig = _dc_redirect_savefig",
        "chart = _DcChart(_DC_SCRIPT_DIR, _DC_STEM)",
        "_dc_data = _dc_load(DATA_DIR, DATA_FILES, MULTI_SOURCE, _DC_SCRIPT_DIR, CHECK_SHA256)",
        "if isinstance(_dc_data, dict):",
        "    dfs = _dc_data            # 多表：{表名: DataFrame}，没有 df",
        "else:",
        "    df = _dc_data             # 单表",
        "result = None",
        "",
        "# ---------------- DataChat 生成的代码（原样） ----------------",
        body.rstrip("\n"),
        "# ---------------- DataChat 生成的代码（结束） ----------------",
        "",
        "if plt.get_fignums():         # 同 DataChat：代码结束时还开着的图存到 chart_path",
        "    _dc_orig_savefig(chart_path)",
        "with pd.option_context(\"display.max_rows\", 200, \"display.max_columns\", 50, \"display.width\", 200):",
        "    print(result)",
        "if _dc_os.path.exists(chart_path):",
        "    print(f\"[plt] 图已保存：{chart_path}\", file=_dc_sys.stderr)",
    ]
    text = "\n".join(head) + "\n" + runtime_source() + "\n".join(tail) + "\n"
    compile(text, "<export>", "exec")          # 拼出来必须是合法 Python（代码本身沙箱里跑通过）
    return text


# ---------------------------------------------------------------- 结果表导出
def _is_default_index(idx) -> bool:
    return isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1 and idx.name is None


def _flat(c) -> str:
    return " / ".join(str(x) for x in c) if isinstance(c, tuple) else c


def result_table(result) -> tuple[pd.DataFrame, bool]:
    """result → (表, 是否写出索引)。DataFrame 原样；Series 一列；dict / list 摊开；标量一格。"""
    if isinstance(result, pd.DataFrame):
        frame = result
    elif isinstance(result, pd.Series):
        frame = result.to_frame(name=result.name if result.name is not None else "值")
    elif isinstance(result, dict) and all(np.ndim(v) == 0 for v in result.values()):
        frame = pd.DataFrame({"项": [str(k) for k in result], "值": list(result.values())})
    elif isinstance(result, (list, tuple)) and all(np.ndim(v) == 0 for v in result):
        frame = pd.DataFrame({"值": list(result)})
    elif result is None or np.ndim(result) == 0:
        frame = pd.DataFrame({"result": [result]})
    else:
        frame = pd.DataFrame({"result": [repr(result)]})
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = [_flat(c) for c in frame.columns]
    return frame, not _is_default_index(frame.index)


def to_csv_bytes(result) -> bytes:
    """UTF-8 带 BOM（Excel 双击打开不乱码），\\r\\n 换行。取值原样，不做任何改写。"""
    frame, index = result_table(result)
    text = frame.to_csv(index=index, lineterminator="\r\n")
    return ("\ufeff" + text).encode("utf-8")


def _cell(v):
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, pd.Timestamp):
        return (v.tz_localize(None) if v.tzinfo is not None else v).to_pydatetime()
    if isinstance(v, str):
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        return ILLEGAL_CHARACTERS_RE.sub("", v)      # xlsx 存不了的控制字符（openpyxl 会直接报错）去掉
    if isinstance(v, (bool, int, float)):
        return v
    import datetime as _dt
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.replace(tzinfo=None) if isinstance(v, (_dt.datetime, _dt.time)) and v.tzinfo else v
    return str(v)


def to_xlsx_bytes(result) -> bytes:
    """一张「结果」工作表：数字是数字、文本是文本（以 = 开头的文本也按文本写，不会变成公式），
    长编号 / 前导零不会像 CSV 那样被 Excel 改掉。超出 Excel 行列上限时拒绝。
    与 CSV 的两处不同：xlsx 存不了的控制字符（\x00-\x08 等）去掉；带时区的时间去掉时区（Excel 没有时区）。"""
    import openpyxl
    frame, index = result_table(result)
    if index:
        frame = frame.reset_index()
        frame.columns = [_flat(c) for c in frame.columns]
    rows, cols = frame.shape
    if rows + 1 > XLSX_MAX_ROWS or cols > XLSX_MAX_COLS:
        raise ExportError(f"结果有 {rows} 行 × {cols} 列，超出 Excel 的上限，请导出 CSV")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "结果"
    ws.append([str(c) for c in frame.columns])
    for rec in frame.itertuples(index=False, name=None):
        ws.append([_cell(v) for v in rec])
    for row in ws.iter_rows(min_row=1):
        for c in row:
            if c.data_type == "f":           # openpyxl 把 = 开头的字符串当公式；这里一律是数据
                c.data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
