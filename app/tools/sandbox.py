import os
import threading
import traceback

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
    ]
}


def run_code(code: str, df: pd.DataFrame, chart_path: str, timeout: int = 20):
    """在受限命名空间 + 超时控制下执行模型生成的 pandas 代码。

    约定：代码使用变量 df，把最终答案赋给 result；若画图则 plt.savefig(chart_path)。
    返回 (result, chart_path_or_None, error_or_None)。
    """
    ns = {
        "__builtins__": _SAFE_BUILTINS,
        "df": df,
        "pd": pd,
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
