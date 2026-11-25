"""沙箱能力对象（阶段 7.5 第 1 步「评估地基」的前置，docs/roadmap/phase75-assess.md §2）。

**唯一来源，纯数据。** 模型代码在沙箱里能用什么，只在这里写一份：
- `app/tools/sandbox_policy.py` 的 `_SAFE_NAMES` / `ALLOWED_IMPORTS` 由它派生（语义与派生前逐字一致）；
- `app/tools/sandbox_worker.py` 注入命名空间的变量名必须与 `injected_names()` 一致
  （worker 在子进程里按名字逐个构造对象，名字仍是字面量；一致性由
  `tests/test_assess_caps.py::test_worker_namespace_matches_caps` 钉住）；
- 评估契约（`app/assess/contracts.py` 的 codegen 契约）读它判 import / 内建 / 注入变量。

第 3 步 S3-1（docs/roadmap/phase75-step3.md §2）起，codegen / reviewer 两处 prompt 里关于沙箱的句子
由 `prompt_lines()` 从这里渲染，不再手写；对 prompt 可见的包是 `prompt_imports`（`allowed_imports` 的子集，
`tests/test_assess_caps.py` 钉住）。react 的 system prompt 本步不注入（phase75-step3.md §7 第 4 条）。

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
    # 第 3 步 S3-1：写进 prompt 的「可以 import 的包」，有序（prompt 逐字节稳定）。是 allowed_imports 的子集：
    # 去掉 `_` 开头的私有名（_strptime）和只给运行时用的 time / locale / warnings。
    prompt_imports: tuple = ()

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
    prompt_imports=(
        "numpy", "pandas", "matplotlib", "math", "statistics", "datetime", "calendar",
        "re", "collections", "itertools", "functools", "decimal", "json",
    ),
)

# 不给的内建：只举一份**固定的示例子集**，后面加「等」。不全量列出：forbidden_builtins 有 100 多个名字，
# 而且按解释器现算，全量列会让 prompt 跟着 Python 版本变（phase75-step3.md §2）。
# 每个名字都必须在 CAPS.forbidden_builtins 里或是 `__import__`（沙箱换成了受限版本，模型代码不该直接调），测试钉住。
PROMPT_FORBIDDEN_EXAMPLES = ("globals", "locals", "eval", "exec", "open", "getattr", "__import__")

# 已就绪变量在 prompt 里的简短说明（只是注释性文字，名字本身从 CAPS 取；键必须是注入的名字，测试钉住）
_VAR_GLOSS = {
    "df": "数据表",
    "dfs": "表名 → 数据表的 dict",
    "pd": "pandas",
    "np": "numpy",
    "plt": "matplotlib.pyplot",
    "chart": "出图函数，见绘图要求",
    "chart_path": "图表文件路径",
}


def prompt_vars(multi: bool, caps: SandboxCaps = CAPS) -> tuple:
    """prompt 里列出的已就绪变量（有序）：数据变量在前，再是公共变量。result 不在这里（它有自己那一句）。"""
    return (caps.multi_data_vars if multi else caps.single_data_vars) + caps.common_vars


def prompt_lines(multi: bool, caps: SandboxCaps = CAPS) -> str:
    """codegen / reviewer prompt 里关于沙箱的三句话（纯函数，全部从 caps 取）：

    1. 已就绪的变量；2. 可以 import 的包（只能用这些）；3. 不给的内建（固定示例子集 + 「等」）。
    每句以「- 」开头，句间换行，直接嵌进两处模板的约定列表。"""
    names = "、".join(f"{v}（{_VAR_GLOSS[v]}）" if v in _VAR_GLOSS else v for v in prompt_vars(multi, caps))
    data = "、".join(caps.multi_data_vars if multi else caps.single_data_vars)
    return "\n".join((
        f"- 已就绪的变量：{names}。直接使用，无需 import；{data} 等数据变量一定已就绪，不要判断变量是否存在。",
        f"- 可以 import 的包：{'、'.join(caps.prompt_imports)}；只能用这些，导入其他库会被沙箱拒绝。",
        f"- 代码在受限沙箱里执行：没有 {' / '.join(PROMPT_FORBIDDEN_EXAMPLES)} 等内置函数。",
    ))
