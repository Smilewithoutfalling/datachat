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

阶段 1.5 补充（B24，来自阶段 1 真实评测的逐题复核）：
  8. 列名不同：模型常把分组列改成中文（月份/地区/产品）或多带几列（销售额 + 占比、环比列）。
     期望 Series 时，在实际表里按"值"找一对（标签列, 数值列）还原成 Series；期望 DataFrame 时，
     名字对不上的列按值的多重集合匹配。只按值匹配，不看列名。
  9. 期望元组/列表、实际是 N 行表：任一列按顺序等于期望即对（如 最高/最低月份 的两行表）。
 10. 期望数值标量、实际是"单行汇总"（1 行表，或 ≤3 项、标签为文字的 Series/dict）：其中有一项等于期望即对。
     更长的容器不适用——否则"返回整列"会碰巧包含答案（如中位数恰好是某地区的总额）。
 11. 期望是月份/季度序号（5、2），实际是 '2024-05' / Period / 'Q2' / '2024Q2' → 比较月份/季度部分。
 12. 百分数与比例：只对题目问"占比"的用例（EvalCase.percent_equiv）接受 ×100 / ÷100；
     题目明确要"百分比"时仍按原值比较。
阶段 1.5 第二轮（B29，来自 Qwen3.5 实测复核）：
 13. 期望 1 行表（"哪条记录"），实际是这一行的 Series（索引是列名）→ 转成 1 行表再比。
 14. 期望索引/列是月份序号（1–12，groupby(dt.month) 的结果），实际是 '2024-01' / Timestamp / Period → 比较月份部分。
 15. ISO 周标签（'2024-W01'，阶段 3d 起也可带括号说明 '2024-W09 (02-26)'）也算时间索引，两边都是时间索引时按位置比值。
 16. 模型自己起键名的汇总 dict：期望数值时 ≤4 项也可（规则 10 的 Series 仍 ≤3）；
     期望标签元组（最高/最低月份）时，取 dict 里的标签值按顺序比较。
 17. 实际多了"总计/合计/All/Total"汇总行或列（crosstab margins=True）而期望没有 → 去掉再比。
阶段 3（新评测集的等价写法）：
 18. 时间索引的其他写法：期望索引是季度序号 1–4 时，实际 'Q1' / '2024Q1' / 季度 Period / '第一季度' 都可；
     期望是月份时间索引、实际是同一年的月份序号 1–12 → 按月份号对齐；
     期望是时间索引、实际是严格递增的 ISO 周序号（1–53）且长度相同 → 按位置比值；
     期望索引是时间或从 1 起的连续序号时，实际是等长 list/tuple → 按位置比值。
规则之外的形态差异仍判错，需人工抽检（见 DEVLOG）。

19. 百分数字符串（'7.00%'、Series/dict 里的 '50.58%'）按数值比较；dict 的键里含季度/月份
    （'第一季度销售总额'）且期望是序号索引时按序号对齐，dict 里的非数值项（'哪个季度更高'）忽略；
    问排名时给名次 1..n 的 Series，与期望数值从大到小的次序一致即算对（无并列时）。
阶段 3c（B46，来自 eval-3b 的 ReAct 复核；只在上面的规则都不匹配时才用，且要求"唯一"以免奖励罗列多种口径）：
 20. a) 期望是标签、实际是按值排好序的数值 Series（榜首不并列）→ 榜首标签即答案；
     b) 实际是带附加信息的 dict（≤8 项、键是文字而不是月份）：
        期望数值时，第一层数值项里有一项等于期望（阶段 3d B50：原为"恰好一个"，几种口径算出同一个值时也算）；期望标签时，第一层恰好一个标签值且等于期望；
        期望 Series/表时，dict 里恰好一个子对象（Series/表/dict）等于期望；
        期望 Series 且索引是文字标签时，每个标签恰好对应一个"含该标签的键"且数值相等（'工作日平均销量' ↔ '工作日'）；
        嵌套 dict 里的标量不参与（{'口径A': {'复购率': …}, '口径B': {…}} 这种罗列口径的不算对）；
     c) 实际是一句话字符串、期望数值：句中恰好一个百分数（没有百分数时恰好一个数字）且等于期望。
阶段 3：应拒答题由 is_refusal() 判定（"无法回答：<原因>"，原因至少 2 个字），不经过上面的规则。
"""
import math
import re

import numpy as np
import pandas as pd

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_QUARTER_RE = re.compile(r"^(?:\d{4})?\s*Q([1-4])$", re.IGNORECASE)
_WEEK_RE = re.compile(r"^\d{4}-?W\d{1,2}(?:\s*[(（][^()（）]*[)）])?$", re.IGNORECASE)   # B51：可带 '(02-26)' 这类说明
_CN_QUARTER_RE = re.compile(r"^(?:\d{4}\s*年?\s*)?第?\s*([一二三四1-4])\s*季度?$")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4}
_MARGIN_LABELS = {"总计", "合计", "总和", "汇总", "all", "total", "sum"}


from app.core.result import REFUSAL_PREFIX, is_refusal, refusal_from_answer  # noqa: F401  (re-export)
_PCT_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*%\s*$")
_EMBED_Q_RE = re.compile(r"(?:第\s*([一二三四1-4])\s*季度|Q([1-4])(?!\d))", re.IGNORECASE)
_EMBED_M_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月")


def _pct(v):
    """规则 19：'7.00%' 这样的百分数字符串 → 7.0（题目已要求用百分数表示，数值按百分数刻度比较）。"""
    v = _py(v)
    if isinstance(v, str):
        m = _PCT_RE.match(v)
        if m:
            return float(m.group(1))
    return None


# ------------------------------------------------------------------ 入口
def results_equal(actual, expected, float_tol=1e-4, *, ordered=None, percent_equiv=False) -> bool:
    """actual：模型结果；expected：标准答案。ordered=None 时按 expected 推断。
    percent_equiv=True 时允许实际结果是期望的 ×100 或 ÷100（规则 12）。"""
    if ordered is None:
        ordered = looks_ranked(expected)
    a, e = _py(actual), _py(expected)
    variants = [a]
    if percent_equiv:
        variants += [v for v in (_scale(a, 100), _scale(a, 0.01)) if v is not None]
    for v in variants:
        try:
            if _eq(v, e, float_tol, ordered):
                return True
        except Exception:
            pass
        try:
            if _extras_eq(v, e, float_tol, ordered):
                return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------------ 规则 20（B46）
_NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_.])")
_PCT_TOKEN_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%")
_EXTRAS_MAX = 8
_DATE_KEY_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")


def _is_label_value(v) -> bool:
    return isinstance(v, (pd.Timestamp, pd.Period)) or (isinstance(v, str) and not _is_num(v) and _pct(v) is None)


def _extras_eq(a, e, tol, ordered) -> bool:
    """规则 20：答案对、但外面裹了附加信息的形态。见模块说明。"""
    # a) 期望标签，实际是排好序的数值 Series
    if _is_label_value(e) and isinstance(a, pd.Series) and len(a) > 1 \
            and pd.api.types.is_numeric_dtype(a) and not isinstance(a.index, pd.MultiIndex):
        if (a.is_monotonic_decreasing or a.is_monotonic_increasing) and a.iloc[0] != a.iloc[1]:
            return _scalar_eq(_py(a.index[0]), e, tol)
        return False
    # c) 一句话字符串
    if isinstance(a, str) and _is_num(e):
        pcts = _PCT_TOKEN_RE.findall(a)
        if pcts:
            return len(pcts) == 1 and _scalar_eq(float(pcts[0]), e, tol)
        nums = _NUM_TOKEN_RE.findall(a)
        return len(nums) == 1 and _scalar_eq(float(nums[0].replace(",", "")), e, tol)
    # b) 带附加信息的 dict
    if not isinstance(a, dict) or not (1 < len(a) <= _EXTRAS_MAX):
        return False
    if not all(isinstance(k, str) and not _DATE_KEY_RE.match(k.strip()) for k in a):
        return False                     # 键本身是日期/月份 → 是时间序列，不是"答案 + 附加信息"
    vals = {k: _py(v) for k, v in a.items()}
    if _is_num(e):
        leaves = [v for v in vals.values() if _is_num(v) or _pct(v) is not None]
        if len(leaves) == len(vals) and max(len(k.strip()) for k in vals) <= 4:
            return False                 # {'华东': 1, '华北': 2, …}：是分组汇总表，碰巧含期望值不算（同规则 10）
        return any(_scalar_eq(v, e, tol) for v in leaves)   # B50：几个口径算出同一个值（整行去重 / 按 order_id 去重）也算
    if _is_label_value(e):
        labels = [v for v in vals.values() if _is_label_value(v)]
        return len(labels) == 1 and _scalar_eq(labels[0], e, tol)
    if isinstance(e, (pd.Series, pd.DataFrame)):
        subs = [v for v in vals.values() if isinstance(v, (pd.Series, pd.DataFrame, dict))]
        hits = 0
        for v in subs:
            try:
                hits += bool(_eq(v, e, tol, ordered))
            except Exception:
                pass
        if hits == 1:
            return True
        if isinstance(e, pd.Series) and not ordered:
            return _keys_contain_labels(vals, e, tol)
    return False


def _keys_contain_labels(vals: dict, e: pd.Series, tol) -> bool:
    """规则 20 b：{'工作日平均销量': 14.85, '周末平均销量': 19.72, '工作日记录数': 1320} 对 Series(周末, 工作日)。"""
    labels = [_py(x) for x in e.index]
    if len(labels) < 2 or not all(isinstance(x, str) and x for x in labels):
        return False
    used = set()
    for lab, ev in zip(labels, e.values):
        others = [o for o in labels if o != lab and lab in o]          # '周末' 也是 '非周末' 的一部分时
        keys = [k for k, v in vals.items()
                if lab in k and not any(o in k for o in others)
                and (_is_num(v) or _pct(v) is not None) and _scalar_eq(v, _py(ev), tol)]
        if len(keys) != 1 or keys[0] in used:
            return False
        used.add(keys[0])
    return True


def _scale(v, f):
    """把结果里的数值乘以 f；没有可缩放的数值时返回 None。"""
    try:
        if _is_num(v):
            return v * f
        if isinstance(v, pd.Series):
            return v * f if pd.api.types.is_numeric_dtype(v) else None
        if isinstance(v, pd.DataFrame):
            num = v.select_dtypes("number").columns
            if len(num) == 0:
                return None
            out = v.copy()
            out[num] = out[num] * f
            return out
        if isinstance(v, dict):
            return {k: (x * f if _is_num(x) else x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(x * f if _is_num(x) else x for x in v)
    except Exception:
        return None
    return None


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


def _period_part(x, n: int):
    """期望是序号 n 时：x 能看作季度（Q2、2024Q2、季度 Period）且 1≤n≤4 → 返回季度号；
    能看作月份（'2024-05'、Timestamp、月 Period）且 1≤n≤12 → 返回月份号；否则 None。"""
    x = _py(x)
    if isinstance(x, pd.Period) and x.freqstr.upper().startswith("Q"):
        return x.quarter if 1 <= n <= 4 else None
    if isinstance(x, str):
        m = _QUARTER_RE.match(x.strip())
        if m:
            return int(m.group(1)) if 1 <= n <= 4 else None
        m = _CN_QUARTER_RE.match(x.strip())                # 规则 18：'第一季度'、'2024年Q'…
        if m and ("季" in x):
            g = m.group(1)
            return (_CN_NUM.get(g) or int(g)) if 1 <= n <= 4 else None
    if 1 <= n <= 12:
        mk = _month_key(x)
        if mk is not None:
            return int(mk[5:7])
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
    if _pct(a) is not None and _is_num(e):
        return _scalar_eq(_pct(a), e, tol)
    if _is_num(e) and not _is_num(a) and float(e).is_integer():
        p = _period_part(a, int(e))     # 规则 11：月份/季度序号
        if p is not None:
            return p == int(e)
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


def _is_margin(x) -> bool:
    return isinstance(x, str) and x.strip().lower() in _MARGIN_LABELS


def _drop_margins(a, e):
    """规则 17：实际多出的汇总行/列（期望里没有）去掉。"""
    if not isinstance(a, (pd.Series, pd.DataFrame)) or not isinstance(e, (pd.Series, pd.DataFrame)):
        return a
    e_labels = {_label(x) for x in e.index}
    if isinstance(e, pd.DataFrame):
        e_labels |= {_label(c) for c in e.columns}
    out = a
    rows = [x for x in out.index if _is_margin(x) and _label(x) not in e_labels]
    if rows and len(rows) < len(out):
        out = out.drop(index=rows)
    if isinstance(out, pd.DataFrame):
        cols = [c for c in out.columns if _is_margin(c) and _label(c) not in e_labels]
        if cols and len(cols) < out.shape[1]:
            out = out.drop(columns=cols)
    return out


# ------------------------------------------------------------------ 分派
def _eq(a, e, tol, ordered) -> bool:
    if a is None and e is None:
        return True
    if a is None or e is None:
        return False
    if isinstance(e, (pd.Series, pd.DataFrame)) and isinstance(a, (pd.Series, pd.DataFrame)):
        trimmed = _drop_margins(a, e)
        if trimmed is not a:
            return _eq(trimmed, e, tol, ordered) or _eq_core(a, e, tol, ordered)
    return _eq_core(a, e, tol, ordered)


def _eq_core(a, e, tol, ordered) -> bool:
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
        if isinstance(e, str) or (_is_num(e) and _period_part(a.index[0], int(e)) is not None
                                  and float(e).is_integer()):
            return _scalar_eq(a.index[0], e, tol)   # Series 只剩一项时，标签即答案
        return False
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
            if len(labels) == 1 and _scalar_eq(labels[0], e, tol):
                return True
    # 规则 10：期望数值，实际是单行汇总
    if _is_num(e):
        vals = None
        if isinstance(a, pd.DataFrame) and len(a) == 1:
            vals = list(a.iloc[0].values)
        elif (isinstance(a, pd.Series) and 1 < len(a) <= 3) or (isinstance(a, dict) and 1 < len(a) <= 4):
            keys = list(a.index if isinstance(a, pd.Series) else a.keys())
            if all(isinstance(k, str) and not _month_key(k) for k in keys):
                vals = list(a.values if isinstance(a, pd.Series) else a.values())
        if vals is not None:
            return any((_is_num(_py(v)) or _pct(v) is not None) and _scalar_eq(v, e, tol) for v in vals)
    return False


def _vs_sequence(a, e: list, tol) -> bool:
    # 规则 9：实际是 N 行表，任一列按顺序等于期望
    if isinstance(a, pd.DataFrame) and a.shape[0] == len(e) and a.shape[0] > 1:
        flat = _flatten(a)
        for c in range(flat.shape[1]):
            col = list(flat.iloc[:, c].values)
            if all(_eq(_py(x), _py(y), tol, ordered=True) for x, y in zip(col, e)):
                return True
        return False
    if isinstance(a, dict) and len(a) > len(e) and all(isinstance(_py(x), str) for x in e):
        # 规则 16：{'最高月份': '2024-06', '最高销售额': 54406.5, ...} → 取标签值
        labels = [_py(x) for x in a.values() if isinstance(_py(x), (str, pd.Timestamp, pd.Period))]
        if len(labels) == len(e):
            a = labels
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
        return len(idx) > 0 and (all(_month_key(x) is not None for x in idx)
                                 or all(isinstance(x, str) and _WEEK_RE.match(x.strip()) for x in idx))
    except Exception:
        return False


def _series_eq(a: pd.Series, e: pd.Series, tol, ordered) -> bool:
    if len(a) != len(e):
        return False
    if _rank_eq(a, e):
        return True
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
    # 规则 14：期望索引是月份序号；规则 18：季度序号
    parts = _month_numbers(a.index, e.index)
    if parts is not None:
        return _mapping_eq(dict(zip(parts, a.values)), dict(zip(e.index, e.values)), tol, ordered)
    parts = _quarter_numbers(a.index, e.index)
    if parts is not None:
        return _mapping_eq(dict(zip(parts, a.values)), dict(zip(e.index, e.values)), tol, ordered)
    if _is_time_index(e.index):
        # 规则 18：期望是月份时间索引（同一年），实际是月份序号
        parts = _month_numbers(e.index, a.index)
        if parts is not None:
            return _mapping_eq(dict(zip(a.index, a.values)), dict(zip(parts, e.values)), tol, ordered)
        # 规则 18：实际是 ISO 周序号
        if _increasing_ints(a.index, 1, 53):
            return all(_scalar_eq(x, y, tol) for x, y in zip(a.values, e.values))
    return False


def _rank_eq(a: pd.Series, e: pd.Series) -> bool:
    """规则 19：问"排名"时实际给名次（1..n），期望给数值：标签相同且名次 = 期望值从大到小的次序即算对。"""
    try:
        av = [_py(x) for x in a.values]
        if sorted(av) != list(range(1, len(e) + 1)) or len(e) < 2:
            return False
        if not all(_is_num(_py(x)) for x in e.values) or e.index.has_duplicates:
            return False
        if sorted(_py(x) for x in e.values) == list(range(1, len(e) + 1)):
            return False                                   # 期望本身就是 1..n，不能当名次放宽
        if sorted(map(_label, a.index)) != sorted(map(_label, e.index)):
            return False
        order = [_label(k) for k in e.sort_values(ascending=False, kind="stable").index]
        if len(set(e.values)) != len(e):
            return False                                   # 有并列时名次口径不唯一，不放宽
        rank = {k: i + 1 for i, k in enumerate(order)}
        return all(rank[_label(k)] == v for k, v in zip(a.index, av))
    except Exception:
        return False


def _increasing_ints(idx, lo, hi) -> bool:
    try:
        v = [_py(x) for x in idx]
        return (len(v) > 0 and all(_is_num(x) and float(x).is_integer() and lo <= x <= hi for x in v)
                and all(p < q for p, q in zip(v, v[1:])))
    except Exception:
        return False


def _quarter_numbers(idx, e_idx):
    """规则 18：e_idx 全是 1–4 的整数、idx 全能看作季度时，返回 idx 的季度号列表；否则 None。"""
    try:
        ev = [_py(x) for x in e_idx]
        if not ev or not all(_is_num(x) and float(x).is_integer() and 1 <= x <= 4 for x in ev):
            return None
        parts = []
        for x in idx:
            x = _py(x)
            if isinstance(x, pd.Period) and x.freqstr.upper().startswith("Q"):
                parts.append(x.quarter)
            elif isinstance(x, str):
                parts.append(_period_part(x, 4) if (_QUARTER_RE.match(x.strip()) or "季" in x) else None)
            else:
                parts.append(None)
        if None in parts or len(set(parts)) != len(parts):
            return None
        return parts
    except Exception:
        return None


def _month_numbers(idx, e_idx):
    """规则 14：e_idx 全是 1–12 的整数、idx 全能看作月份时，返回 idx 的月份号列表；否则 None。"""
    try:
        ev = [_py(x) for x in e_idx]
        if not ev or not all(_is_num(x) and float(x).is_integer() and 1 <= x <= 12 for x in ev):
            return None
        parts = [_period_part(x, 12) for x in idx]
        if None in parts or len(set(parts)) != len(parts):
            return None
        return parts
    except Exception:
        return None


def _vs_series(a, e: pd.Series, tol, ordered) -> bool:
    if isinstance(a, pd.Series):
        return _series_eq(a, e, tol, ordered)
    if isinstance(a, dict):
        if _series_eq(pd.Series(a), e, tol, ordered):
            return True
        return _dict_embedded_periods(a, e, tol, ordered)
    if isinstance(a, (list, tuple)):
        # 只有当期望本身没有有意义的标签（默认整数索引）时才按位置比；
        # 规则 18：期望索引是时间或从 1 起的连续序号（季度 1–4、月份 1–12）时也按位置比
        ordinal = _increasing_ints(e.index, 1, 12) and _py(e.index[0]) == 1 and \
            all(int(_py(q)) - int(_py(p)) == 1 for p, q in zip(e.index, e.index[1:]))
        if (isinstance(e.index, pd.RangeIndex) or ordinal or _is_time_index(e.index)) and len(a) == len(e):
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
    # 规则 8：按值找（标签列, 数值列）
    for c in _label_value_series(a, len(e)):
        if _series_eq(c, e, tol, ordered):
            return True
    # 规则 4：两级 MultiIndex Series vs 透视宽表
    if isinstance(e.index, pd.MultiIndex) and e.index.nlevels == 2:
        wide = e.unstack()
        if _frame_eq(a, wide, tol, ordered=False) or _frame_eq(a.T, wide, tol, ordered=False):
            return True
    return False


def _dict_embedded_periods(a: dict, e: pd.Series, tol, ordered) -> bool:
    """规则 19：{'第一季度销售总额': 131210.0, '第二季度销售总额': 143463.5, '哪个季度更高': '第二季度'}
    对 Series(index=[1, 2])：只取数值项，键里能读出季度（或月份）序号且一一对应时按序号比较。"""
    nums = {k: v for k, v in a.items() if _is_num(_py(v)) or _pct(v) is not None}
    if len(nums) != len(e) or len(e) < 2:
        return False
    ev = [_py(x) for x in e.index]
    if not all(_is_num(x) and float(x).is_integer() for x in ev):
        return False
    for rx, hi in ((_EMBED_Q_RE, 4), (_EMBED_M_RE, 12)):
        if not all(1 <= x <= hi for x in ev):
            continue
        parts = []
        for k in nums:
            m = rx.search(str(k)) if isinstance(k, str) else None
            if not m:
                parts = None
                break
            g = next(x for x in m.groups() if x)
            parts.append(_CN_NUM.get(g) or int(g))
        if parts and len(set(parts)) == len(parts):
            return _mapping_eq(dict(zip(parts, nums.values())), dict(zip(e.index, e.values)), tol, ordered)
    return False


def _label_value_series(a: pd.DataFrame, n: int, max_cols: int = 20):
    """规则 8：把表里每一对（标签列, 数值列）还原成 Series；有意义的行索引也算一列标签。"""
    if len(a) != n:
        return
    flat = _flatten(a)
    if flat.shape[1] > max_cols or flat.columns.duplicated().any():
        return
    for lc in flat.columns:
        labels = flat[lc]
        if pd.api.types.is_float_dtype(labels):
            continue
        for vc in flat.columns:
            if vc == lc or not pd.api.types.is_numeric_dtype(flat[vc]) or pd.api.types.is_bool_dtype(flat[vc]):
                continue
            yield pd.Series(flat[vc].values, index=pd.Index(labels.values))


def _same_values(x: pd.Series, y: pd.Series, tol) -> bool:
    """两列的值作为多重集合是否相同（不看列名和顺序）。"""
    if len(x) != len(y):
        return False
    xv, yv = [_py(v) for v in x.values], [_py(v) for v in y.values]
    if all(_is_num(v) or _is_nan(v) for v in yv) and all(_is_num(v) or _is_nan(v) for v in xv):
        key = lambda v: (1, 0.0) if _is_nan(v) else (0, float(v))  # noqa: E731
        return all(_scalar_eq(p, q, tol) for p, q in zip(sorted(xv, key=key), sorted(yv, key=key)))
    parts = _month_numbers(xv, yv)
    if parts is not None:                                  # 规则 14
        return sorted(parts) == sorted(int(v) for v in yv)
    norm = lambda v: _month_key(v) or _label(v)  # noqa: E731
    return sorted(map(norm, xv)) == sorted(map(norm, yv))


def _match_columns(a: pd.DataFrame, e: pd.DataFrame, tol):
    """规则 8（表）：同名列直接对应，其余期望列按值在实际表里找一列；找不全返回 None。"""
    mapping, used = {}, set()
    for ec in e.columns:
        if ec in a.columns and ec not in used:
            mapping[ec] = ec
            used.add(ec)
    for ec in e.columns:
        if ec in mapping:
            continue
        for ac in a.columns:
            if ac not in used and _same_values(a[ac], e[ec], tol):
                mapping[ec] = ac
                used.add(ac)
                break
        else:
            return None
    return pd.DataFrame({ec: a[ac].values for ec, ac in mapping.items()})


def _vs_frame(a, e: pd.DataFrame, tol, ordered) -> bool:
    if isinstance(a, pd.Series):
        if isinstance(a.index, pd.MultiIndex) and a.index.nlevels == 2:   # 规则 4 反向
            wide = a.unstack()
            return _frame_eq(wide, e, tol, ordered=False) or _frame_eq(wide.T, e, tol, ordered=False)
        if e.shape[1] == 1:
            return _series_eq(a, e.iloc[:, 0], tol, ordered)
        if len(e) == 1 and not isinstance(a.index, pd.MultiIndex):   # 规则 13
            e_cols = {_label(c) for c in e.columns}
            if e_cols <= {_label(x) for x in a.index}:
                return _frame_eq(a.to_frame().T, e, tol, ordered=False)
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
            if a.columns.duplicated().any() or e.columns.duplicated().any():
                return False
            matched = _match_columns(a, e, tol)
            if matched is None:
                return False
            a = matched
    cols = list(e.columns)
    ra = [tuple(_py(v) for v in row) for row in a[cols].itertuples(index=False, name=None)]
    re_ = [tuple(_py(v) for v in row) for row in e[cols].itertuples(index=False, name=None)]
    if not ordered:
        key = lambda r: tuple(_label(v) if not _is_num(v) else f"{float(v):.6g}" for v in r)  # noqa: E731
        ra, re_ = sorted(ra, key=key), sorted(re_, key=key)
    return all(all(_scalar_eq(x, y, tol) for x, y in zip(r1, r2)) for r1, r2 in zip(ra, re_))
