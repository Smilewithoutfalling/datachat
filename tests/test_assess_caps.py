"""阶段 7.5 第 1 步：沙箱能力对象是唯一来源（app/tools/sandbox_caps.py）。"""
import ast
import builtins
import os

from app.tools import sandbox_policy
from app.tools.sandbox import run_code
from app.tools.sandbox_caps import CAPS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 派生之前 sandbox_policy.py 里的字面量（f8167d3），钉住「语义逐字不变」
_OLD_SAFE_NAMES = [
    "abs", "min", "max", "sum", "len", "range", "round", "sorted",
    "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "enumerate", "zip", "map", "filter", "print", "isinstance",
    "any", "all", "reversed", "repr",
    "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "Exception",
]
_OLD_ALLOWED_IMPORTS = frozenset({
    "numpy", "pandas", "matplotlib", "math", "statistics", "datetime", "calendar",
    "re", "collections", "itertools", "functools", "decimal", "json", "warnings",
    "time", "locale", "_strptime",
})


def test_policy_is_derived_from_caps_and_unchanged():
    assert sandbox_policy._SAFE_NAMES == _OLD_SAFE_NAMES == list(CAPS.safe_builtins)
    assert sandbox_policy.ALLOWED_IMPORTS == _OLD_ALLOWED_IMPORTS
    assert sandbox_policy.ALLOWED_IMPORTS is CAPS.allowed_imports
    assert isinstance(sandbox_policy.ALLOWED_IMPORTS, frozenset)


def test_make_safe_builtins_matches_caps():
    safe = sandbox_policy.make_safe_builtins(builtins)
    assert set(safe) == set(CAPS.safe_builtins) | {"__import__"}


def test_forbidden_builtins_are_python_builtins_not_given():
    fb = CAPS.forbidden_builtins
    for name in ("globals", "locals", "eval", "exec", "open", "compile", "getattr", "vars", "input"):
        assert name in fb
    assert not fb & set(CAPS.safe_builtins)
    assert all(hasattr(builtins, n) for n in fb)
    # sandbox_name_hint 对「Python 有、沙箱不给」的名字补提示，口径与 forbidden_builtins 一致
    for n in ("globals", "open"):
        assert sandbox_policy.sandbox_name_hint(NameError(f"name '{n}' is not defined", name=n))
    assert sandbox_policy.sandbox_name_hint(NameError("x", name="len")) == ""


def _worker_ns_keys():
    """sandbox_worker.main() 里 data = {...} 与 ns = {...} 的键（AST 读源码，不跑子进程）。"""
    src = open(os.path.join(ROOT, "app", "tools", "sandbox_worker.py"), encoding="utf-8").read()
    main = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    data_keys, ns_keys = set(), set()
    for n in ast.walk(main):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            name = n.targets[0].id
            if name == "data" and isinstance(n.value, ast.IfExp):
                for d in (n.value.body, n.value.orelse):
                    data_keys |= {k.value for k in d.keys}
            if name == "ns" and isinstance(n.value, ast.Dict):
                ns_keys |= {k.value for k in n.value.keys if k is not None}
    return data_keys, ns_keys


def test_worker_namespace_matches_caps():
    data_keys, ns_keys = _worker_ns_keys()
    assert data_keys == set(CAPS.single_data_vars) | set(CAPS.multi_data_vars)
    injected = ns_keys - {"__builtins__", "__name__"}
    assert injected | set(CAPS.single_data_vars) == CAPS.injected_names(multi=False)
    assert injected | set(CAPS.multi_data_vars) == CAPS.injected_names(multi=True)


_PROBE = """
present = []
for name in ('df', 'dfs', 'pd', 'np', 'plt', 'chart', 'chart_path', 'result'):
    try:
        eval_ok = {'df': lambda: df, 'dfs': lambda: dfs, 'pd': lambda: pd, 'np': lambda: np,
                   'plt': lambda: plt, 'chart': lambda: chart, 'chart_path': lambda: chart_path,
                   'result': lambda: result}[name]()
        present.append(name)
    except Exception:
        present.append('!' + name)
result = present
"""


def test_worker_runtime_injects_caps_names(sample_df, chart_path):
    """真跑一次子进程：单表时 caps 列出的名字都在、dfs 不在；多表时反过来。"""
    single, _, err = run_code(_PROBE, sample_df, chart_path)
    assert err is None, err
    assert {n for n in single if not n.startswith("!")} == CAPS.injected_names(multi=False)
    multi, _, err = run_code(_PROBE, {"t": sample_df}, chart_path)
    assert err is None, err
    assert {n for n in multi if not n.startswith("!")} == CAPS.injected_names(multi=True)
