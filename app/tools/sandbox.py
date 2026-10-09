import os
import threading
import traceback

import builtins

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # 无界面后端，服务器/脚本下也能出图
import matplotlib.pyplot as plt

from app.tools.plotting import apply_style

apply_style()                  # 模块加载即设好中文字体与汇报级风格

# 受限内置函数白名单：只放数据分析常用的安全函数，
# 屏蔽 open / __import__ / eval / exec 等高危能力，降低任意代码执行风险。
_SAFE_BUILTINS = {
    k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
    for k in [
        "abs", "min", "max", "sum", "len", "range", "round", "sorted",
        "list", "dict", "set", "tuple", "str", "int", "float", "bool",
        "enumerate", "zip", "map", "filter", "print", "isinstance",
        "any", "all", "reversed", "repr",
        "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "Exception",
    ]
}

# 允许 import 的模块（按顶层包名）。模型（如 Qwen）常无视"不要 import"写 import numpy/matplotlib，
# 沙箱直接拦截会让整题执行失败；pandas 的部分方法（如 Timestamp.strftime）也会在运行时延迟导入（B28）。
# 这些包本身已在命名空间里，放行不扩大攻击面；同进程沙箱仍可经 pd 逃逸（B01），阶段 2 子进程沙箱再收紧。
_ALLOWED_IMPORTS = {
    "numpy", "pandas", "matplotlib", "math", "statistics", "datetime", "calendar",
    "re", "collections", "itertools", "functools", "decimal", "json", "warnings",
    "time", "locale", "_strptime",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name.split(".")[0] in _ALLOWED_IMPORTS:
        return builtins.__import__(name, globals, locals, fromlist, level)
    raise ImportError(f"沙箱不允许导入 {name!r}；可直接使用 df、pd、np、plt")


_SAFE_BUILTINS["__import__"] = _safe_import


def run_code(code: str, df: pd.DataFrame, chart_path: str, timeout: int = 20):
    """在受限命名空间 + 超时控制下执行模型生成的 pandas 代码。

    约定：代码使用变量 df，把最终答案赋给 result；若画图则 plt.savefig(chart_path)。
    返回 (result, chart_path_or_None, error_or_None)。
    """
    ns = {
        "__builtins__": _SAFE_BUILTINS,
        "df": df,
        "pd": pd,
        "np": np,
        "plt": plt,
        "chart_path": chart_path,
        "result": None,
    }
    box = {}

    apply_style()          # 防止上一次执行的代码改了 rcParams
    plt.close("all")       # 清掉残留图，避免叠图

    # 重定向 savefig：模型常用自己的相对文件名（污染工作目录），
    # 这里强制所有保存都落到 chart_path，杜绝散落的临时图片。
    _orig_savefig = plt.savefig

    def _redirect_savefig(*args, **kwargs):
        kwargs.pop("fname", None)
        return _orig_savefig(chart_path, **kwargs)

    plt.savefig = _redirect_savefig

    def target():
        try:
            exec(code, ns)
        except Exception:
            box["error"] = traceback.format_exc(limit=3)

    t = threading.Thread(target=target, daemon=True)
    try:
        t.start()
        t.join(timeout)
        if t.is_alive():
            plt.close("all")
            return None, None, f"TimeoutError: 代码执行超过 {timeout} 秒"
        if "error" in box:
            plt.close("all")
            return None, None, box["error"]

        # 兜底：只要代码画了图，就由我们把当前图存到 chart_path，
        # 不依赖模型是否正确调用了 plt.savefig（重定向已兜住大多数情况）。
        if plt.get_fignums():
            try:
                _orig_savefig(chart_path)
            except Exception:
                pass
        plt.close("all")

        result = ns.get("result")
        chart = chart_path if os.path.exists(chart_path) else None
        return result, chart, None
    finally:
        plt.savefig = _orig_savefig
