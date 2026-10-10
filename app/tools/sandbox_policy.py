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
