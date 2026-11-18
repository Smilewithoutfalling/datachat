"""阶段 7 A2：结果合理性校验（docs/roadmap/phase7-a2a3.md）。

代码执行成功之后做几项很便宜的检查。命中任意一项，就让 reviewer 再看一遍，最多一次：
第二次结果还是这样，就照常交给 summarizer。检查只认"几乎不可能是正确答案"的形态，宁可漏报：

- 空结果：0 行的 DataFrame / Series，或者 0 列的 DataFrame。最常见的原因是筛选值和数据里的
  实际写法对不上，比如「华东」对「华东区」、大小写、首尾空格。
- 全是空值：标量 NaN，或者 Series / DataFrame 里所有值都是 NaN。
- 无穷大：数值里出现 inf，通常是除以了 0。

不做的：
- 占比之和偏离 100%：子集占比、Top-N 占比本来就不到 100%，单看结果判断不了。
- 数量级突变：没有参照值。
- 计数为 0：「已取消的有几单」答 0 可能是对的。

结果是 dict 时逐个值检查（多个小问用 dict 作答是 codegen 的约定）。字符串（包括拒答）不检查。
"""
import math

import numpy as np
import pandas as pd


def _is_nan_scalar(v) -> bool:
    try:
        return v is pd.NA or v is pd.NaT or (isinstance(v, (float, np.floating)) and math.isnan(v))
    except TypeError:
        return False


def _is_inf_scalar(v) -> bool:
    return isinstance(v, (float, np.floating)) and math.isinf(v)


def _frame_issue(obj) -> str | None:
    if isinstance(obj, pd.DataFrame) and obj.shape[1] == 0:
        return "结果是空表（0 列）"
    if len(obj) == 0:
        return "结果是空的（0 行）"
    try:
        if obj.isna().all() if isinstance(obj, pd.Series) else bool(obj.isna().all().all()):
            return "结果里的值全是空值（NaN）"
    except Exception:  # noqa: BLE001  奇怪的 dtype 不阻断主流程
        return None
    num = obj if isinstance(obj, pd.Series) else obj.select_dtypes(include="number")
    if isinstance(num, pd.Series) and not pd.api.types.is_numeric_dtype(num):
        return None
    try:
        arr = np.asarray(num, dtype="float64")
    except (TypeError, ValueError):
        return None
    if arr.size and np.isinf(arr).any():
        return "结果里有无穷大（inf），可能是除以了 0"
    return None


def _one(v) -> str | None:
    if isinstance(v, (pd.DataFrame, pd.Series)):
        return _frame_issue(v)
    if isinstance(v, pd.Index):
        return "结果是空的（0 行）" if len(v) == 0 else None
    if _is_nan_scalar(v):
        return "结果是空值（NaN）"
    if _is_inf_scalar(v):
        return "结果是无穷大（inf），可能是除以了 0"
    return None


def result_issue(result) -> str | None:
    """返回一句「哪里可疑」；没问题返回 None。"""
    if isinstance(result, dict):
        for k, v in result.items():
            issue = _one(v)
            if issue:
                return f"result[{k!r}]：{issue}"
        return None
    return _one(result)


SANITY_PREFIX = "代码执行成功，但结果可疑："
SANITY_HINT = ("请对照问题检查：筛选条件里的取值和数据里的实际写法是否一致（全称/简称、大小写、首尾空格），"
               "分母会不会是 0，列选得对不对。如果确认这个结果就是对的，原样输出原代码即可。")


def sanity_message(issue: str) -> str:
    return f"{SANITY_PREFIX}{issue}。{SANITY_HINT}"
