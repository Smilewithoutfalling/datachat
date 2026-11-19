"""沙箱能力对象（阶段 7.5 第 1 步「评估地基」的前置，docs/roadmap/phase75-assess.md §2）。

**唯一来源，纯数据。** 模型代码在沙箱里能用什么，只在这里写一份：
- `app/tools/sandbox_policy.py` 的 `_SAFE_NAMES` / `ALLOWED_IMPORTS` 由它派生（语义与派生前逐字一致）；
- `app/tools/sandbox_worker.py` 注入命名空间的变量名必须与 `injected_names()` 一致
  （worker 在子进程里按名字逐个构造对象，名字仍是字面量；一致性由
  `tests/test_assess_caps.py::test_worker_namespace_matches_caps` 钉住）；
- 评估契约（`app/assess/contracts.py` 的 codegen 契约）读它判 import / 内建 / 注入变量。

本步**不**把它注入 codegen / reviewer 的 prompt（那是第 3 步）。

本模块不 import 任何第三方包：worker 子进程在装审计钩子之前会经 sandbox_policy 导入它。
"""
from __future__ import annotations

import builtins as _builtins
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxCaps:
    # 允许 import 的顶层包名（`import numpy.linalg` 按 numpy 判）
    allowed_imports: frozenset
    # 沙箱给的安全 builtins（顺序与原 _SAFE_NAMES 一致；__import__ 另由 make_safe_builtins 换成受限版本）
    safe_builtins: tuple
    # 单表时注入的数据变量 / 多表时注入的数据变量（二者互斥：多表没有 df，单表没有 dfs）
    single_data_vars: tuple
    multi_data_vars: tuple
    # 两种情况都注入的变量
    common_vars: tuple
    # 模型必须赋值的结果变量
    result_var: str

    @property
    def forbidden_builtins(self) -> frozenset:
        """Python builtins 里有、但沙箱不给的公开名字（globals / locals / eval / exec / open / getattr …）。
        按当前解释器的 builtins 现算：新版 Python 多出来的内建同样是「沙箱不给」。"""
        return frozenset(n for n in dir(_builtins)
                         if not n.startswith("_") and n not in self.safe_builtins)

    def injected_names(self, multi: bool) -> frozenset:
        """模型代码开始执行时命名空间里已有的变量名（不含 __builtins__ / __name__）。
        result 预置为 None，也算注入。"""
        data = self.multi_data_vars if multi else self.single_data_vars
        return frozenset(data + self.common_vars + (self.result_var,))


CAPS = SandboxCaps(
    allowed_imports=frozenset({
        "numpy", "pandas", "matplotlib", "math", "statistics", "datetime", "calendar",
        "re", "collections", "itertools", "functools", "decimal", "json", "warnings",
        "time", "locale", "_strptime",
    }),
    safe_builtins=(
        "abs", "min", "max", "sum", "len", "range", "round", "sorted",
        "list", "dict", "set", "tuple", "str", "int", "float", "bool",
        "enumerate", "zip", "map", "filter", "print", "isinstance",
        "any", "all", "reversed", "repr",
        "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "Exception",
    ),
    single_data_vars=("df",),
    multi_data_vars=("dfs",),
    common_vars=("pd", "np", "plt", "chart", "chart_path"),
    result_var="result",
)
