"""结果比较器：比较模型代码的执行结果（actual）与 ground truth（expected）。

阶段 1 重写（B12），两类偏差分别处理：
- 虚高：旧实现把 Series 按值排序后转 dict 比较，Top-N 顺序错也判对。
  现在由 ordered 决定是否比较顺序：评测用例显式给出（EvalCase.ordered）；
  未给出时按 expected 推断——索引既不升序也不降序（即被显式排过序）的 Series/DataFrame 视为排名题。
- 虚低：答案"形态"不同但内容相同的情况，按下列有限规则归一后再比，每条规则都有单测：
  1. 标量 vs 单元素容器（1 项 Series、1×1 DataFrame、长度 1 的 list/tuple）→ 拆包比较；
  2. 期望是标签（如 idxmax 返回的"华东"），实际是 (标签, 数值) 二元组/二项 dict → 标签相同即对；
  3. 期望 Series，实际是 reset_index 形态的 DataFrame / 单列 DataFrame / 单行宽表 → 还原成 Series；
  4. 期望两级 MultiIndex Series，实际是透视宽表（或反过来）→ unstack 后按表比较；
  5. 期望 DataFrame，实际列是其超集（多带了几列）→ 只比较期望的列；行索引是否 reset 不影响；
  6. 时间标签：Timestamp(月末) / Period('2024-01') / '2024-01' 视为同一个月；两边都是时间索引时按位置比值；
  7. 数值：相对误差 1e-4；期望值本身被 round 到 d 位小数（d≤4）时，允许半个末位的误差；NaN 等于 NaN。
规则之外的形态差异仍判错，需人工抽检（见 DEVLOG）。
"""
import math
import re

import numpy as np
import pandas as pd

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ------------------------------------------------------------------ 入口
def results_equal(actual, expected, float_tol=1e-4, *, ordered=None) -> bool:
    """actual：模型结果；expected：标准答案。ordered=None 时按 expected 推断。"""
    if ordered is None:
        ordered = looks_ranked(expected)
    try:
        return _eq(_py(actual), _py(expected), float_tol, ordered)
    except Exception:
        return False


def looks_ranked(obj) -> bool:
    """expected 是否像"排过序的结果"：长度 > 1 且索引既非升序也非降序。"""
    if not isinstance(obj, (pd.Series, pd.DataFrame)) or len(obj) <= 1:
        return False
    try:
        idx = obj.index
        return not (idx.is_monotonic_increasing or idx.is_monotonic_decreasing)
    except Exception:
        return False


# ------------------------------------------------------------------ 归一
def _py(v):
    """numpy 标量 → Python 标量；ndarray → list；其余原样。"""
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _is_num(v) -> bool:
    return isinstance(v, (int, float, np.number)) and not isinstance(v, bool)


def _is_nan(v) -> bool:
    try:
        return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT or v is pd.NA
    except Exception:
        return False


def _label(x) -> str:
    """索引标签/时间值的规范字符串。"""
    x = _py(x)
    if isinstance(x, tuple):
        return "|".join(_label(i) for i in x)
    if isinstance(x, pd.Period):
        return str(x)
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d") if x == x.normalize() else x.isoformat()
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x).strip()


def _month_key(x):
    """能看作"某年某月"时返回 'YYYY-MM'，否则 None。"""
    x = _py(x)
    if isinstance(x, pd.Period):
        return x.strftime("%Y-%m")
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m")
    if isinstance(x, str):
        s = x.strip()
        if _MONTH_RE.match(s):
            return s
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return s[:7]
    return None


def _decimals(v: float):
    s = repr(float(v))
    if "e" in s or "." not in s:
        return 0 if "e" not in s else None
    return len(s.split(".")[1].rstrip("0"))


# ------------------------------------------------------------------ 标量
def _scalar_eq(a, e, tol) -> bool:
    a, e = _py(a), _py(e)
    if _is_nan(a) and _is_nan(e):
        return True
    if _is_nan(a) or _is_nan(e):
        return False
    if _is_num(a) and _is_num(e):
        e_is_float = isinstance(e, float)
        a, e = float(a), float(e)
        if math.isclose(a, e, rel_tol=tol, abs_tol=1e-9):
            return True
        if e_is_float:
            # 标准答案被 round 到 d 位小数（d≤4）时，模型未 round 的结果允许差半个末位
            d = _decimals(e)
            if d is not None and 0 < d <= 4:
                return abs(a - e) <= 0.5 * 10 ** (-d) + 1e-12
        return False
    if isinstance(a, bool) or isinstance(e, bool):
        return a == e
    # 时间：Timestamp / Period / 日期字符串
    if isinstance(e, str) and _MONTH_RE.match(e.strip()):
        mk = _month_key(a)
        if mk is not None:
            return mk == e.strip()
    if isinstance(a, (pd.Timestamp, pd.Period)) or isinstance(e, (pd.Timestamp, pd.Period)):
        if _label(a) == _label(e):
            return True
        ma, me = _month_key(a), _month_key(e)
        return ma is not None and ma == me and (isinstance(a, pd.Period) or isinstance(e, pd.Period))
    # 数字与数字字符串
    if _is_num(a) or _is_num(e):
        try:
            return _scalar_eq(float(a), float(e), tol)
        except (TypeError, ValueError):
            return False
    return str(a).strip() == str(e).strip()


def _is_scalar(v) -> bool:
    return not isinstance(v, (pd.Series, pd.DataFrame, list, tuple, dict, set))


# ------------------------------------------------------------------ 分派
def _eq(a, e, tol, ordered) -> bool:
    if a is None and e is None:
        return True
    if a is None or e is None:
        return False
    if isinstance(e, pd.DataFrame):
        return _vs_frame(a, e, tol, ordered)
    if isinstance(e, pd.Series):
        return _vs_series(a, e, tol, ordered)
    if isinstance(e, (list, tuple)):
        return _vs_sequence(a, list(e), tol)
    if isinstance(e, dict):
        if isinstance(a, pd.Series):
            a = a.to_dict()
        if isinstance(a, dict):
            return _mapping_eq(a, e, tol, ordered=False)
        return False
    return _vs_scalar(a, e, tol)


def _unwrap_single(a):
    """单元素容器 → 元素；否则原样返回。"""
    if isinstance(a, pd.DataFrame) and a.shape == (1, 1):
        return _py(a.iat[0, 0])
    if isinstance(a, pd.Series) and len(a) == 1:
        return _py(a.iloc[0])
    if isinstance(a, (list, tuple)) and len(a) == 1:
        return _py(a[0])
    return a


def _vs_scalar(a, e, tol) -> bool:
    if _is_scalar(a):
        return _scalar_eq(a, e, tol)
    # 规则 1：单元素容器
    if isinstance(a, pd.Series) and len(a) == 1:
        if _scalar_eq(a.iloc[0], e, tol):
            return True
        return isinstance(e, str) and _scalar_eq(a.index[0], e, tol)   # Series 只剩一项时，标签即答案
    u = _unwrap_single(a)
    if u is not a and _is_scalar(u):
        return _scalar_eq(u, e, tol)
    # 规则 2：期望是标签，实际是 (标签, 数值)
    if isinstance(e, str) and not _is_num(e):
        items = None
        if isinstance(a, (list, tuple)) and len(a) == 2:
            items = list(a)
        elif isinstance(a, dict) and len(a) == 2:
            items = list(a.values())
        elif isinstance(a, pd.Series) and len(a) == 2 and not _is_num(a.index[0]):
            items = list(a.values)
        elif isinstance(a, pd.DataFrame) and len(a) == 1:
            items = list(a.iloc[0].values)
        if items is not None:
            labels = [x for x in map(_py, items) if isinstance(x, (str, pd.Timestamp, pd.Period))]
            return len(labels) == 1 and _scalar_eq(labels[0], e, tol)
    return False


def _vs_sequence(a, e: list, tol) -> bool:
    if isinstance(a, pd.Series):
        a = list(a.values)
    elif isinstance(a, dict):
        a = list(a.values())
    elif isinstance(a, pd.DataFrame) and a.shape[0] == 1:
        a = list(a.iloc[0].values)
    if not isinstance(a, (list, tuple)) or len(a) != len(e):
        return False
    return all(_eq(_py(x), _py(y), tol, ordered=True) for x, y in zip(a, e))


def _mapping_eq(a: dict, e: dict, tol, ordered) -> bool:
    la = [_label(k) for k in a]
    le = [_label(k) for k in e]
    if sorted(la) != sorted(le) or len(set(le)) != len(le):
        return False
    if ordered and la != le:
        return False
    av = dict(zip(la, a.values()))
    return all(_scalar_eq(av[k], v, tol) for k, v in zip(le, e.values()))


def _is_time_index(idx) -> bool:
    if isinstance(idx, (pd.DatetimeIndex, pd.PeriodIndex)):
        return True
    try:
        return len(idx) > 0 and all(_month_key(x) is not None for x in idx)
    except Exception:
        return False


def _series_eq(a: pd.Series, e: pd.Series, tol, ordered) -> bool:
    if len(a) != len(e):
        return False
    if _mapping_eq(dict(zip(a.index, a.values)), dict(zip(e.index, e.values)), tol, ordered):
        return True
    # 规则 6：两边都是时间索引（月末 Timestamp / Period / 'YYYY-MM'），标签写法不同 → 先按月份对齐
    if _is_time_index(a.index) and _is_time_index(e.index):
        ka = [_month_key(x) for x in a.index]
        ke = [_month_key(x) for x in e.index]
        if None not in ka and None not in ke and len(set(ke)) == len(ke):
            if sorted(ka) == sorted(ke):
                av = dict(zip(ka, a.values))
                return all(_scalar_eq(av[k], v, tol) for k, v in zip(ke, e.values))
        # 周/日频等无法按月对齐时，按位置比较数值
        return all(_scalar_eq(x, y, tol) for x, y in zip(a.values, e.values))
    return False


def _vs_series(a, e: pd.Series, tol, ordered) -> bool:
    if isinstance(a, pd.Series):
        return _series_eq(a, e, tol, ordered)
    if isinstance(a, dict):
        return _series_eq(pd.Series(a), e, tol, ordered)
    if isinstance(a, (list, tuple)):
        # 只有当期望本身没有有意义的标签（默认整数索引）时才按位置比
        if isinstance(e.index, pd.RangeIndex) and len(a) == len(e):
            return all(_scalar_eq(x, y, tol) for x, y in zip(a, e.values))
        return False
    if not isinstance(a, pd.DataFrame):
        return False
    # 规则 3：DataFrame → Series
    candidates = []
    if a.shape[1] == 1:
        candidates.append(a.iloc[:, 0])
    names = [n for n in e.index.names if n is not None]
    if names and all(n in a.columns for n in names):
        rest = [c for c in a.columns if c not in names]
        if len(rest) == 1:
            candidates.append(a.set_index(names)[rest[0]])
    if a.shape[0] == 1:
        candidates.append(a.iloc[0])
    for c in candidates:
        if _series_eq(c, e, tol, ordered):
            return True
    # 规则 4：两级 MultiIndex Series vs 透视宽表
    if isinstance(e.index, pd.MultiIndex) and e.index.nlevels == 2:
        wide = e.unstack()
        if _frame_eq(a, wide, tol, ordered=False) or _frame_eq(a.T, wide, tol, ordered=False):
            return True
    return False


def _vs_frame(a, e: pd.DataFrame, tol, ordered) -> bool:
    if isinstance(a, pd.Series):
        if isinstance(a.index, pd.MultiIndex) and a.index.nlevels == 2:   # 规则 4 反向
            wide = a.unstack()
            return _frame_eq(wide, e, tol, ordered=False) or _frame_eq(wide.T, e, tol, ordered=False)
        if e.shape[1] == 1:
            return _series_eq(a, e.iloc[:, 0], tol, ordered)
        return False
    if isinstance(a, (dict, list)):
        try:
            a = pd.DataFrame(a)
        except Exception:
            return False
    if not isinstance(a, pd.DataFrame):
        return False
    if _frame_eq(a, e, tol, ordered):
        return True
    return not ordered and _frame_eq(a.T, e, tol, ordered=False)


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """有意义的行索引（有名字 / 非整数 / 多级）转成普通列；纯行号索引直接丢掉（规则 5）。"""
    idx = df.index
    meaningful = (isinstance(idx, pd.MultiIndex) or any(n is not None for n in idx.names)
                  or not pd.api.types.is_integer_dtype(idx.dtype))
    out = df.reset_index() if meaningful else df.reset_index(drop=True)
    out.columns = [_label(c) for c in out.columns]
    return out


def _frame_eq(a: pd.DataFrame, e: pd.DataFrame, tol, ordered) -> bool:
    a, e = _flatten(a), _flatten(e)
    if len(a) != len(e) or len(set(e.columns)) != len(e.columns):
        return False
    if not set(e.columns) <= set(a.columns):
        # 透视表常见：期望的行索引没名字（列名 "index"），实际有名字——只要其余列都在就按位置对齐首列
        if "index" in e.columns and set(e.columns) - {"index"} <= set(a.columns) and len(a.columns) > 0:
            first = [c for c in a.columns if c not in set(e.columns)]
            if len(first) != 1:
                return False
            a = a.rename(columns={first[0]: "index"})
        else:
            return False
    cols = list(e.columns)
    ra = [tuple(_py(v) for v in row) for row in a[cols].itertuples(index=False, name=None)]
    re_ = [tuple(_py(v) for v in row) for row in e[cols].itertuples(index=False, name=None)]
    if not ordered:
        key = lambda r: tuple(_label(v) if not _is_num(v) else f"{float(v):.6g}" for v in r)  # noqa: E731
        ra, re_ = sorted(ra, key=key), sorted(re_, key=key)
    return all(all(_scalar_eq(x, y, tol) for x, y in zip(r1, r2)) for r1, r2 in zip(ra, re_))
