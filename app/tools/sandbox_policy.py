"""沙箱里模型代码可用的 builtins 与 import 白名单（主进程的 run_trusted 与子进程 worker 共用）。"""

_SAFE_NAMES = [
    "abs", "min", "max", "sum", "len", "range", "round", "sorted",
    "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "enumerate", "zip", "map", "filter", "print", "isinstance",
    "any", "all", "reversed", "repr",
    "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "Exception",
]

# 允许 import 的模块（按顶层包名）。模型（如 Qwen）常无视"不要 import"写 import numpy/matplotlib；
# pandas 的部分方法也会在运行时延迟导入（B28）。这些包本身已在命名空间里，放行不扩大攻击面。
ALLOWED_IMPORTS = frozenset({
    "numpy", "pandas", "matplotlib", "math", "statistics", "datetime", "calendar",
    "re", "collections", "itertools", "functools", "decimal", "json", "warnings",
    "time", "locale", "_strptime",
})


def make_safe_builtins(builtins_module) -> dict:
    real_import = builtins_module.__import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name.split(".")[0] in ALLOWED_IMPORTS:
            return real_import(name, globals, locals, fromlist, level)
        raise ImportError(f"沙箱不允许导入 {name!r}；可直接使用 df、pd、np、plt")

    safe = {k: getattr(builtins_module, k) for k in _SAFE_NAMES}
    safe["__import__"] = _safe_import
    return safe


def sandbox_name_hint(e: BaseException) -> str:
    """F2（修复批 1）：模型用了沙箱故意不给的内置名（globals、open、eval…）时，NameError 只说
    "name 'globals' is not defined"，reviewer 看不出这是沙箱限制，三次重试都在原地打转（BACKLOG N6，agg_002）。
    只对「Python 真有、沙箱没给」的名字补一句；模型自己拼错的变量名不补。"""
    if not isinstance(e, NameError):
        return ""
    import builtins
    name = getattr(e, "name", None)
    if not name or name in _SAFE_NAMES or not hasattr(builtins, name):
        return ""
    return (f"提示：沙箱里没有内置函数 {name}（受限环境，故意不提供）。df 等数据变量一定已就绪，"
            f"直接使用，不要判断变量是否存在；改用不依赖 {name} 的写法。")
