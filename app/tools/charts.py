"""结构化图表（M13，阶段 5 第 1 步）：DataFrame → ECharts option，以及 option 的白名单校验。

约定（见 DEVLOG [22] 与 S 的 M13 方案 v3）：
- 模型只通过 chart(kind, df, x=, y=, series=, title=) 出图，只选图型、列和标题；
  数据层（xAxis.data / series[].data）全部由 build_option 从 df 生成，模型写不进数字。
- v1 图型：bar / line / area / pie / scatter。横向、堆叠、平滑、数值标签等是前端开关，不在这里。
- 不产出 dataset；不产出任何函数、formatter 模板、link、graphic；产出必须是严格 JSON（无 NaN / Infinity）。
- build_option 是纯函数，参数问题抛 ChartError；产物没过白名单（builder 自身的 bug）抛 ChartBugError。
- ChartSlot 是沙箱里注入给模型的 chart()（第 2 步，[26]）：永不抛异常，ChartError 记 chart_errors，
  其他异常记 chart_internal_errors（我们的 bug，必须清零）；exec 结束后 finish() 对槽位里的 spec 独立复检。
- validate_spec 是丢弃式白名单之前的最后一道：未知键、禁用键、非法类型、超量数据 → 整图拒绝并给出原因。

返回的 spec 结构（v1）：
    {"v": 1, "kind": "bar", "truncated": False, "x_kind": "category", "option": {...ECharts option...}}
- option 是"交给 ECharts 的东西"；x_kind（category / time / value）是给前端判断能否换图型 / 排序用的元信息，
  所以和 option 并列放在 spec 层，不进 option（F3 第五步，S 10-19）。spec.kind 是后端出的图型，前端换图型后
  option.series[].type 会和它有意不一致（前端测试 spec_kind_is_backend_truth 钉住）。
"""
from __future__ import annotations

import inspect
import json
import math
import copy
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

# 升版规则（F3 第五步，S 10-19）：加字段不升（向后兼容）；改字段语义或删字段才升。
# 判据是"老前端读到新 spec 会不会误判"——会才升。x_kind 是纯加法、老 spec 缺它时前端保守处理，所以没升。
SPEC_VERSION = 1
X_KINDS = ("category", "time", "value")
SHOW_SYMBOL_MAX = 60       # 折线 / 面积类目数 ≤ 此值才画数据点（前端换图型沿用，经 schema 导出）
KINDS = ("bar", "line", "area", "pie", "scatter")
MAX_POINTS = 5000          # 每张图的数据点上限（类目数 × 系列数）
MAX_SERIES = 20
MAX_PIE_SLICES = 50
MISSING_LABEL = "（缺失）"   # 缺失类目的显示名：明示缺失，不冒充真实取值（不出现 'nan' / '<NA>'）
TITLE_MAX = 100
NAME_MAX = 100             # 系列名、坐标轴名
CATEGORY_MAX = 200         # 单个类目名

# 与 matplotlib 风格（plotting.PALETTE）同一套主色，测试钉住两份相等。option 里不再带 color（F3 第四步）：
# echarts 的 mergeTheme 在 option.color 存在时整条跳过主题配色，配色只能归主题。这份经 gen_ui_types 导出到
# chart_schema.json 的 palette，前端默认主题（经典）从那里读。
# 第 3 色 #CD7D28（原 #E2843B 对白底 2.76，不到 WCAG 1.4.11 的 3:1）：对白底 3.20、对 #C0392B ΔE00 25.0。
# 暖色带里"白底 ≥3:1"与"离红 ≥24"几乎互斥，25 左右就是这一带的上限。
# F4（S 10-19 定）：饼图 >6 类目颜色循环，扩到 10 色。前 6 色不动；后 4 色对白底 ≥3.0、循环相邻（含第 10→1）ΔE00 ≥23。
PALETTE = ["#1F6FB2", "#159A8C", "#CD7D28", "#C0392B", "#7E57C2", "#3A7D44", "#6B2E47", "#6B572E", "#D9268E", "#172082"]
# 轴名截断宽度（px）：12px 字体下约 10 个汉字、约 18 个 ASCII 字符。轴名纳入外边界（outerBoundsContain='all'）后，
# 长轴名在窄画布上靠收缩 grid 包不住（clamp 调到 10% 也不行，F3 第四步实测），只能截断；省略号自述被截。
AXIS_NAME_MAX_PX = 120
_AXIS_NAME_TRUNCATE = {"maxWidth": AXIS_NAME_MAX_PX, "ellipsis": "\u2026"}

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]")
# 渲染面的不安全字符 → 显示替换（F3 第三步，THREAT_MODEL §2.3）。_display_safe 与闸门 _check_strings 共用这一份。
# - { } ：tooltip 的 richText 会解析，用户串里的 `}` 能提前闭合包装并借用内部样式（伪造数值列）。
# - \n ：参与 tooltip 排版，能让真值配上攻击者的标签。
# - \t 不在此列：第二步实测它作为整体绘制、不参与排版（_CTRL 同样放过了它）。
DISPLAY_UNSAFE = {"{": "\uff5b", "}": "\uff5d", "\n": " "}


class ChartError(ValueError):
    """builder 无法按给定参数出图（列不存在、类型不符、参数冲突等）。消息给模型和用户看，用中文。"""


class ChartBugError(RuntimeError):
    """builder 自己的产物没过白名单：是我们的 bug，不是模型的错（chart_option 链路里单列报警，[23]）。"""


# ------------------------------------------------------------------ 值转换
def _clean_str(s, limit: int) -> str:
    """字符串 → 模型 / 用户可见文本（清控制字符、限长）。也用于拼 ChartError 等消息，
    所以这里**不做**渲染面的规范化：消息原样回到模型，全角化会让模型照抄出不存在的列名（F3 第三步）。
    画布上的规则只在 _display_safe 里做。"""
    s = _CTRL.sub(" ", str(s)).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _num(v):
    """数值 → 原生 int/float；NaN / ±inf / None / NaT → None；非数值抛 ChartError。"""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (pd.Timedelta,)):
        return v.total_seconds()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    raise ChartError(f"数值列里有非数值：{_clean_str(repr(v), 40)}")


def _cat(v) -> str:
    """类目标签，缺失显示为 MISSING_LABEL。"""
    lab = _label(v)
    return MISSING_LABEL if lab is None else lab


def _label(v) -> str | None:
    """类目 → 字符串；时间 → ISO；缺失（None / NaN / NaT / pd.NA）→ None，由调用方显示为 MISSING_LABEL。"""
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if not isinstance(v, (str, tuple)):
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat() if (v.hour or v.minute or v.second or v.microsecond) else v.date().isoformat()
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, pd.Period):
        return str(v)
    if isinstance(v, tuple):          # MultiIndex 的一项
        return _clean_str(" / ".join(str(p) for p in v), CATEGORY_MAX)
    return _clean_str(v, CATEGORY_MAX)


def _is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def _x_kind(s: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(s) or isinstance(s.dtype, pd.PeriodDtype):
        return "time"
    return "category"


# ------------------------------------------------------------------ 参数整理
def _as_frame(df):
    """→ (DataFrame, 默认 x 列名或 None)。Series 的索引变成一列并作为默认 x。"""
    if isinstance(df, pd.Series):
        name = df.name if df.name is not None else "值"
        idx_name = df.index.name if df.index.name is not None else "类别"
        if idx_name == name:
            idx_name = f"{idx_name}_"
        return pd.DataFrame({idx_name: list(df.index), name: df.to_numpy()}), idx_name
    if isinstance(df, pd.DataFrame):
        if df.columns.duplicated().any():
            raise ChartError("DataFrame 有重名列，先重命名再出图")
        if isinstance(df.columns, pd.MultiIndex):
            raise ChartError("不支持多级列名，先拍平（如 df.columns = ['_'.join(map(str, c)) for c in df.columns]）")
        return df, None
    raise ChartError(f"df 必须是 DataFrame 或 Series，收到 {type(df).__name__}")


def _col(df: pd.DataFrame, name, what: str) -> pd.Series:
    if name not in df.columns:
        # 列名来自用户数据，原样（仅清控制字符、限长）进消息；HTML 转义在渲染边界做（THREAT_MODEL §图表）
        cols = "、".join(_clean_str(c, NAME_MAX) for c in list(df.columns)[:20])
        raise ChartError(f"{what}列 {_clean_str(repr(name), NAME_MAX)} 不存在；可用列：{cols}")
    return df[name]


def _resolve(df: pd.DataFrame, x, y, series):
    """返回 (x_values: Series, y_cols: list, series_col or None)。x 为 None 时用索引。"""
    if y is not None and series is not None and not isinstance(y, str):
        raise ChartError("y 给列表（宽表）时不能再给 series（长表），二选一")
    if x is None:
        xs = pd.Series(list(df.index), index=df.index, name=df.index.name or "类别")
    else:
        xs = _col(df, x, "x ")
    if series is not None:
        _col(df, series, "series ")
    if y is None:
        skip = {x, series}
        cand = [c for c in df.columns if c not in skip and _is_numeric(df[c])]
        if len(cand) != 1:
            raise ChartError("没给 y，且无法唯一确定数值列；请用 y='列名' 指定")
        ys = cand
    elif isinstance(y, str) or not isinstance(y, (list, tuple)):
        ys = [y]
    else:
        ys = list(y)
        if not ys:
            raise ChartError("y 是空列表")
    for c in ys:
        if not _is_numeric(_col(df, c, "y ")):
            raise ChartError(f"y 列 {c!r} 不是数值类型（{df[c].dtype}）")
    if len(ys) > MAX_SERIES:
        raise ChartError(f"系列太多（{len(ys)}），最多 {MAX_SERIES} 个")
    return xs, ys, series


# ------------------------------------------------------------------ builder
def build_option(kind, df, *, x=None, y=None, series=None, title=None) -> dict:
    """DataFrame / Series → 图表 spec（见模块说明）。纯函数；失败抛 ChartError。

    - kind：bar / line / area / pie / scatter
    - x：横轴（类目）列；不给就用索引。scatter 时 x 必须是数值列。
    - y：一列名，或列名列表（宽表：多列 = 多系列）；不给时若只有一个数值列就用它。
    - series：分组列（长表：每组一个系列），与 y 列表互斥。
    - 排序、Top-N 请先用 pandas 做好；builder 按 df 现有顺序出图。
    """
    if kind not in KINDS:
        raise ChartError(f"不支持的图型 {kind!r}；可用：{', '.join(KINDS)}（其他图型请用 plt）")
    frame, default_x = _as_frame(df)
    if x is None:
        x = default_x
    if frame.empty:
        raise ChartError("数据为空，不出图")
    xs, ys, series_col = _resolve(frame, x, y, series)
    title_txt = _clean_str(title, TITLE_MAX) if title else None

    if kind == "pie":
        option, truncated = _pie(frame, xs, ys, series_col)
    elif kind == "scatter":
        option, truncated = _scatter(frame, xs, ys, series_col)
    else:
        option, truncated = _cartesian(kind, frame, xs, ys, series_col)

    if title_txt:
        option["title"] = {"text": title_txt, "left": "center"}
    # 顺序写死：规范化在校验之前，否则闸门 _check_strings 会拒掉每一张图
    x_kind = "value" if kind == "scatter" else _x_kind(xs)
    spec = {"v": SPEC_VERSION, "kind": kind, "truncated": truncated, "x_kind": x_kind, "option": _display_safe(option)}
    problems = validate_spec(spec)
    if problems:                                  # builder 自身的 bug 也不能放出去
        raise ChartBugError("图表未通过校验：" + "；".join(problems[:3]))
    return spec


def _display_str(s: str) -> str:
    for bad, good in DISPLAY_UNSAFE.items():
        s = s.replace(bad, good)
    return s


def _display_safe(node):
    """option → 可安全上画布的 option：递归替换每一个 string 值里的 DISPLAY_UNSAFE 字符（键由 builder 决定，不动）。
    遍历的是产物不是登记表，新增字段自动覆盖。只用于 option；消息 / 数据表 / 结论不经过这里。"""
    if isinstance(node, str):
        return _display_str(node)
    if isinstance(node, dict):
        return {k: _display_safe(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_display_safe(v) for v in node]
    return node


def _wide(frame, xs, ys, series_col):
    """统一成 (类目标签列表, [(系列名, 数值列表)])。长表按 series 透视，保留 x 的首次出现顺序。"""
    if series_col is None:
        cats = [_cat(v) for v in xs]
        return cats, [(_clean_str(c, NAME_MAX), [_num(v) for v in frame[c]]) for c in ys]
    ycol = ys[0]
    tmp = pd.DataFrame({"_x": [_cat(v) for v in xs], "_s": [_cat(v) for v in frame[series_col]],
                        "_y": list(frame[ycol])})
    if tmp.duplicated(["_x", "_s"]).any():
        raise ChartError("长表里同一 (x, series) 出现多行，请先 groupby 聚合")
    cats = list(dict.fromkeys(tmp["_x"]))
    groups = list(dict.fromkeys(tmp["_s"]))
    if len(groups) > MAX_SERIES:
        raise ChartError(f"series 分组太多（{len(groups)}），最多 {MAX_SERIES} 个；先筛选或合并为'其他'")
    pv = tmp.pivot(index="_x", columns="_s", values="_y").reindex(index=cats, columns=groups)
    return cats, [(_clean_str(g, NAME_MAX), [_num(v) for v in pv[g]]) for g in groups]


# outerBoundsContain='all'：轴名也纳入外边界（'axisLabel' 时 x 轴名在 640 宽画布上起画于 x≈629，画出画布）。
# clamp 显式写 25%（官方默认），不靠默认值：调小只是把"轴名出界"换成"图被压废"（F3 第四步）。
_GRID_BOUNDS = {"outerBoundsMode": "same", "outerBoundsContain": "all",
                "outerBoundsClampWidth": "25%", "outerBoundsClampHeight": "25%"}


# 轴名的位置（F3 第四步实测后定）：默认 x 轴名在轴末端右侧、y 轴名居中骑在 y 轴线上，纳入外边界后它们横向占宽——
# 320 宽画布上长轴名把 plot 区压到 31–39%。x 轴名放到轴下方居中（nameLocation='middle'），y 轴名左对齐向右伸，
# 横向不再占宽：同样夹具 plot 区 ≥ 82%。代价是 x 轴名多占一行高度（400 高时 plot 区高 66% → 60%）。
_X_NAME = {"nameLocation": "middle", "nameGap": 28}
_Y_NAME = {"nameTextStyle": {"align": "left"}}

# 几何契约登记表（F3 第五步）：后端改过、而重放路径原样下发历史 spec 的几何 / 外观键。前端 prepare 的 normalize
# 用它把老 spec 归一到当前契约（经 gen_ui_types 导出为 chart_schema.json 的 geometry，前端不写第二份字面量）。
# 以后后端改任何几何键都必须在这里登记；tests/test_charts.py 双向比对它和 _cartesian / _scatter 的产物，漏登记就红。
GEOMETRY = {
    "grid": _GRID_BOUNDS,
    "xAxis": {**_X_NAME, "nameTruncate": _AXIS_NAME_TRUNCATE},
    "yAxis": {**_Y_NAME, "nameTruncate": _AXIS_NAME_TRUNCATE},
}
# 每张图自己的框架值（不是契约归一的对象：bottom 随系列数变）。前端换图型要造出和 builder 一样的 option，从 schema 读这些值。
_CART_GRID = {"left": "3%", "right": "4%", "top": 60}
_CART_BOTTOM = {"single": 30, "multi": 50}
_PIE_LEGEND = {"show": True, "type": "scroll", "orient": "vertical", "left": "left", "top": "middle"}
_PIE_RADIUS = ["0%", "65%"]
_PIE_CENTER = ["60%", "55%"]


def _axis(which, **kw):
    return {**kw, **copy.deepcopy(_X_NAME if which == "x" else _Y_NAME), "nameTruncate": dict(_AXIS_NAME_TRUNCATE)}


def _truncate(cats, sers):
    n = max(1, len(sers))
    cap = MAX_POINTS // n
    if len(cats) <= cap:
        return cats, sers, False
    return cats[:cap], [(nm, vals[:cap]) for nm, vals in sers], True


def _cartesian(kind, frame, xs, ys, series_col):
    cats, sers, = _wide(frame, xs, ys, series_col)
    cats, sers, truncated = _truncate(cats, sers)
    multi = len(sers) > 1
    out_series = []
    for nm, vals in sers:
        s = {"name": nm, "type": "bar" if kind == "bar" else "line", "data": vals}
        if kind == "area":
            s["areaStyle"] = {}
        if kind in ("line", "area"):
            s["showSymbol"] = len(cats) <= SHOW_SYMBOL_MAX
        out_series.append(s)
    x_name = "" if xs.name is None else _clean_str(xs.name, NAME_MAX)
    y_name = _clean_str(ys[0], NAME_MAX) if (series_col is not None or not multi) else ""
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": multi, "top": "bottom"},
        "grid": {**_CART_GRID, "bottom": _CART_BOTTOM["multi" if multi else "single"], **_GRID_BOUNDS},
        "xAxis": _axis("x", type="category", name=x_name, data=cats, boundaryGap=kind == "bar"),
        "yAxis": _axis("y", type="value", name=y_name),
        "series": out_series,
    }
    if _x_kind(xs) == "time":
        option["xAxis"]["axisLabel"] = {"hideOverlap": True}
    return option, truncated


def _pie(frame, xs, ys, series_col):
    if series_col is not None or len(ys) != 1:
        raise ChartError("饼图只能是一列类目 + 一个数值列（不支持 series 或多个 y）")
    vals = [_num(v) for v in frame[ys[0]]]
    if any(v is not None and v < 0 for v in vals):
        raise ChartError("饼图的数值不能为负")
    items = [{"name": _cat(c), "value": v}
             for c, v in zip(xs, vals) if v is not None]
    if len(items) > MAX_PIE_SLICES:
        raise ChartError(f"饼图扇区太多（{len(items)}），最多 {MAX_PIE_SLICES} 个；先取 Top-N 并合并为'其他'")
    option = {
        "tooltip": {"trigger": "item"},
        "legend": dict(_PIE_LEGEND),
        "series": [{"name": _clean_str(ys[0], NAME_MAX), "type": "pie", "radius": list(_PIE_RADIUS),
                    "center": list(_PIE_CENTER), "data": items}],
    }
    return option, False


def _scatter(frame, xs, ys, series_col):
    if not _is_numeric(xs):
        raise ChartError("散点图的 x 必须是数值列")
    groups = []
    if series_col is None:
        for c in ys:
            groups.append((_clean_str(c, NAME_MAX), list(zip(xs, frame[c]))))
    else:
        ycol = ys[0]
        keys = pd.Series([_cat(v) for v in frame[series_col]], index=frame.index)
        order = list(dict.fromkeys(keys))
        if len(order) > MAX_SERIES:
            raise ChartError(f"series 分组太多（{len(order)}），最多 {MAX_SERIES} 个")
        for g in order:
            m = (keys == g).to_numpy()
            groups.append((_clean_str(g, NAME_MAX), list(zip(xs[m], frame[ycol][m]))))
    total = sum(len(p) for _, p in groups)
    truncated = total > MAX_POINTS
    if truncated:
        cap = MAX_POINTS // len(groups)
        groups = [(nm, pts[:cap]) for nm, pts in groups]
    out = []
    for nm, pts in groups:
        data = [[_num(a), _num(b)] for a, b in pts]
        out.append({"name": nm, "type": "scatter", "data": [p for p in data if None not in p],
                    "symbolSize": 6 if total > 500 else 9})
    option = {
        "tooltip": {"trigger": "item"},
        "legend": {"show": len(out) > 1, "top": "bottom"},
        "grid": {**_CART_GRID, "bottom": _CART_BOTTOM["multi" if len(out) > 1 else "single"], **_GRID_BOUNDS},
        "xAxis": _axis("x", type="value", name=_clean_str(xs.name, NAME_MAX) if xs.name is not None else "", scale=True),
        "yAxis": _axis("y", type="value", name=_clean_str(ys[0], NAME_MAX) if len(ys) == 1 else "", scale=True),
        "series": out,
    }
    return option, truncated


# ------------------------------------------------------------------ 白名单校验
# 结构：dict 的值是子结构；类型元组表示叶子允许的 Python 类型。"*" 表示数组元素结构。
# 只收 builder 实际产出的键（无人产出的键不预留）；前端样式层的 patch 有了消费方再加。
#
# 定位（别误读成安全边界）：v1 里 validate_spec 只校验 builder 自己的产出——模型拿不到 option
# （chart() 返回 None），v1 真正的边界是 chart() 的签名：模型只能传图型、列名和标题字符串。
# 这里防的是 builder 自身的 bug（漏掉 NaN、多出键、长度不一致）；v2 层 2 的 patch 才是它的第一个外部输入。
_STR, _NUM, _BOOL = (str,), (int, float), (bool,)
_POS = (str, int, float)                         # "3%" / 60 / "center"
_ALLOWED = {
    "title": {"text": _STR, "left": _POS},
    "tooltip": {"trigger": _STR},
    "legend": {"show": _BOOL, "type": _STR, "top": _POS, "left": _POS, "orient": _STR},
    # outerBounds 替代已弃用的 containLabel；containLabel 不在白名单，前端不注册 LegacyGridContainLabel。
    # 第四步起 'all'（轴名也纳入）+ 显式 clamp 25%，见 _GRID_BOUNDS。color 不在白名单：配色归前端主题。
    "grid": {"left": _POS, "right": _POS, "top": _POS, "bottom": _POS,
             "outerBoundsMode": _STR, "outerBoundsContain": _STR,
             "outerBoundsClampWidth": _STR, "outerBoundsClampHeight": _STR},
    "xAxis": {"type": _STR, "name": _STR, "data": {"*": _STR}, "boundaryGap": _BOOL, "scale": _BOOL,
              "axisLabel": {"hideOverlap": _BOOL}, "nameTruncate": {"maxWidth": _NUM, "ellipsis": _STR},
              "nameLocation": _STR, "nameGap": _NUM},
    "yAxis": {"type": _STR, "name": _STR, "scale": _BOOL, "nameTruncate": {"maxWidth": _NUM, "ellipsis": _STR},
              "nameTextStyle": {"align": _STR}},
    "series": {"*": {
        "name": _STR, "type": _STR, "data": None,          # data 单独按图型校验
        "areaStyle": {}, "showSymbol": _BOOL, "symbolSize": _NUM,
        "radius": {"*": _STR}, "center": {"*": _STR},             # 饼图
    }},
}
# 明确禁止（即使将来放宽白名单也不许出现）：会进 DOM 或执行代码的通道，以及数据层绕过面
# 禁的是"由后端 / 模型决定这个键"。前端在校验之后自己加 tooltip.renderMode='richText'，所以最终渲染产物
# 必然不过本白名单——这是有意的：白名单只校验 builder 输出（v2 起含 patch），最终产物永不回验。
# F3 第五步起例外不止 renderMode 一个键：前端开关写的整层（dataZoom、series[].markLine / markPoint / label / stack /
# smooth / itemStyle / areaStyle.color）都在白名单外，_check_strings 也管不到。约束改由前端 FRONTEND_KEYS（路径 → 值集合，
# 只有字面量和主题色）承担，ui/web/src/charts/switches.test.ts 的"例外层"测试钉住：prepare 产物相对 builder 等价产物的
# 新增 / 改动 ⊆ FRONTEND_KEYS，且不含任何字符串型用户数据（THREAT_MODEL §2.3）。
# 将来回灌前端 option 的流程只回传样式差量重新走 builder；不得为了让回灌通过而删 renderMode（THREAT_MODEL §2.3）。
BANNED_KEYS = {"link", "sublink", "graphic", "formatter", "renderItem", "dataset", "aria", "toolbox",
               "rich", "renderMode", "extraCssText", "target", "sublinkTarget"}
_ENUMS = {
    ("tooltip", "trigger"): {"axis", "item"},
    ("legend", "type"): {"plain", "scroll"},
    ("legend", "orient"): {"horizontal", "vertical"},
    ("xAxis", "type"): {"category", "value"},
    ("yAxis", "type"): {"value"},
    ("series", "type"): {"bar", "line", "pie", "scatter"},
    ("grid", "outerBoundsMode"): {"same"},
    ("grid", "outerBoundsContain"): {"all"},
    ("grid", "outerBoundsClampWidth"): {"25%"},
    ("grid", "outerBoundsClampHeight"): {"25%"},
    ("xAxis", "nameLocation"): {"middle"},
    ("yAxis", "nameTextStyle", "align"): {"left"},
}


def _walk(node, rule, path, problems):
    if len(problems) >= 20:
        return
    where = ".".join(path) or "option"
    if rule is None:
        return
    if isinstance(rule, tuple):
        if isinstance(node, bool) and bool not in rule:
            problems.append(f"{where} 类型应为 {'/'.join(t.__name__ for t in rule)}")
        elif not isinstance(node, rule):
            problems.append(f"{where} 类型应为 {'/'.join(t.__name__ for t in rule)}")
        elif isinstance(node, str):
            if len(node) > max(TITLE_MAX, CATEGORY_MAX) or _CTRL.search(node):
                problems.append(f"{where} 字符串过长或含控制字符")
        elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
            problems.append(f"{where} 不能是 NaN/Infinity")
        return
    if "*" in rule:
        if not isinstance(node, list):
            problems.append(f"{where} 应为数组")
            return
        for i, item in enumerate(node):
            _walk(item, rule["*"], path + [str(i)], problems)
        return
    if not isinstance(node, dict):
        problems.append(f"{where} 应为对象")
        return
    for k, v in node.items():
        if not isinstance(k, str):
            problems.append(f"{where} 有非字符串键")
            continue
        if k in BANNED_KEYS:
            problems.append(f"{where}.{k} 是禁用键")
            continue
        if k not in rule:
            problems.append(f"{where}.{k} 不在白名单")
            continue
        _walk(v, rule[k], path + [k], problems)


def _check_strings(node, path, problems):
    """闸门：独立于 _ALLOWED，递归遍历整个 option，任何 string 值或键含 DISPLAY_UNSAFE 字符即报问题。
    对 builder 产物它永远不该触发（_display_safe 在前）；触发就是 builder 漏了，记 ChartBugError。"""
    if len(problems) >= 20:
        return
    where = ".".join(path) or "option"
    if isinstance(node, str):
        bad = sorted({c for c in DISPLAY_UNSAFE if c in node})
        if bad:
            problems.append(f"{where} 含渲染不安全字符 {bad!r}")
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and any(c in k for c in DISPLAY_UNSAFE):
                problems.append(f"{where} 的键 {k!r} 含渲染不安全字符")
            _check_strings(v, path + [str(k)], problems)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_strings(v, path + [str(i)], problems)


def _check_enums(option, problems):
    def get(d, keys):
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return None
            d = d[k]
        return d
    for keys, allowed in _ENUMS.items():
        if keys[0] == "series":
            for i, s in enumerate(option.get("series") or []):
                v = get(s, keys[1:])
                if v is not None and v not in allowed:
                    problems.append(f"series.{i}.{'.'.join(keys[1:])} 取值 {v!r} 不允许")
        else:
            v = get(option, keys)
            if v is not None and v not in allowed:
                problems.append(f"{'.'.join(keys)} 取值 {v!r} 不允许")


_KIND_SERIES_TYPE = {"bar": "bar", "line": "line", "area": "line", "pie": "pie", "scatter": "scatter"}


def _check_kind(kind, option, problems):
    """spec.kind 与每个 series.type 一致（area = line + areaStyle）；前端“换图型”读 spec.kind。"""
    want = _KIND_SERIES_TYPE.get(kind)
    for i, s in enumerate(option.get("series") or []):
        if not isinstance(s, dict):
            continue
        if want and s.get("type") != want:
            problems.append(f"series.{i}.type {s.get('type')!r} 与 kind {kind!r} 不一致")
        if (kind == "area") != ("areaStyle" in s):
            problems.append(f"series.{i}.areaStyle 与 kind {kind!r} 不一致")


def _is_num(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)
                         and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))


def _check_data(option, problems):
    n_cats = len((option.get("xAxis") or {}).get("data") or []) if isinstance(option.get("xAxis"), dict) else 0
    total = 0
    for i, s in enumerate(option.get("series") or []):
        if not isinstance(s, dict):
            continue
        data, typ = s.get("data"), s.get("type")
        if not isinstance(data, list):
            problems.append(f"series.{i}.data 应为数组")
            continue
        total += len(data)
        if typ in ("bar", "line"):
            if not all(_is_num(v) for v in data):
                problems.append(f"series.{i}.data 只能是数值或 null")
            if n_cats and len(data) != n_cats:
                problems.append(f"series.{i}.data 长度 {len(data)} 与类目数 {n_cats} 不一致")
        elif typ == "scatter":
            if not all(isinstance(p, list) and len(p) == 2 and all(_is_num(v) for v in p) for p in data):
                problems.append(f"series.{i}.data 应为 [x, y] 数值对")
        elif typ == "pie":
            ok = all(isinstance(p, dict) and set(p) == {"name", "value"} and isinstance(p["name"], str)
                     and len(p["name"]) <= CATEGORY_MAX and not _CTRL.search(p["name"]) and _is_num(p["value"])
                     for p in data)
            if not ok:
                problems.append(f"series.{i}.data 应为 {{name, value}} 列表")
    if total > MAX_POINTS:
        problems.append(f"数据点 {total} 超过上限 {MAX_POINTS}")


def validate_spec(spec) -> list[str]:
    """返回问题列表；空列表 = 通过。任何问题都应整图拒绝（不做静默删改）。"""
    problems: list[str] = []
    if not isinstance(spec, dict) or set(spec) != {"v", "kind", "truncated", "x_kind", "option"}:
        return ["spec 结构应为 {v, kind, truncated, x_kind, option}"]
    if spec["v"] != SPEC_VERSION:
        problems.append(f"不支持的 spec 版本 {spec['v']!r}")
    if spec["kind"] not in KINDS:
        problems.append(f"未知图型 {spec['kind']!r}")
    if not isinstance(spec["truncated"], bool):
        problems.append("truncated 应为布尔值")
    if spec["x_kind"] not in X_KINDS:
        problems.append(f"未知 x_kind {spec['x_kind']!r}")
    elif (spec["kind"] == "scatter") != (spec["x_kind"] == "value"):
        problems.append("x_kind 与图型不符（scatter 才是 value）")
    option = spec["option"]
    if not isinstance(option, dict) or not isinstance(option.get("series"), list) or not option["series"]:
        return problems + ["option.series 应为非空数组"]
    _walk(option, _ALLOWED, [], problems)
    _check_strings(option, [], problems)
    _check_kind(spec["kind"], option, problems)
    _check_enums(option, problems)
    _check_data(option, problems)
    try:
        json.dumps(spec, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        problems.append(f"不是严格 JSON：{e}")
    return problems


# ------------------------------------------------------------------ 沙箱里的 chart()（第 2 步，[26]）
MAX_CHARTS = 4                     # 每次执行最多几张结构化图


def _spec_title(spec) -> str:
    try:
        return spec["option"]["title"]["text"]
    except (KeyError, TypeError):
        return ""


def _chart_signature(kind=None, df=None, x=None, y=None, series=None, title=None):
    pass


_CHART_SIG = inspect.signature(_chart_signature)


class ChartSlot:
    """注入沙箱命名空间的 chart(kind, df, x=None, y=None, series=None, title=None)。

    - 永不抛异常、返回 None：模型拿不到 option，也就改不了数据层（v1 的安全边界是这个签名）。
      连参数个数都不对（TypeError 发生在绑定参数时）也一样吞掉，所以用 *args / **kwargs 自己绑定。
    - 每次执行最多 MAX_CHARTS 张，超出的记 chart_errors。
    - 模型能拿到这个对象本身（chart.specs），所以 exec 结束后 finish() 对槽位里的每个 spec 独立复检，
      不信任 exec 期间的任何状态；复检不过的按内部错误记、整图丢弃。
    """

    def __init__(self):
        self.specs: list = []
        self.calls = 0
        self.errors: list = []         # ChartError：模型参数问题（计入 chart_option 链路的未通过）
        self.internal: list = []       # 其他异常：我们的 bug，单列报警

    def __call__(self, *args, **kwargs):
        self.calls += 1
        try:
            spec = self._build(*args, **kwargs)
            if len(self.specs) >= MAX_CHARTS:
                raise ChartError(f"每次执行最多 {MAX_CHARTS} 张图，第 {self.calls} 次 chart() 未出图")
            self.specs.append(spec)
        except ChartError as e:
            self.errors.append(str(e))
        except Exception as e:  # noqa: BLE001
            self.internal.append(f"{type(e).__name__}: {_clean_str(str(e), 300)}")
        return None

    _USAGE = "用法：chart(kind, df, x=列名, y=列名或列名列表, series=分组列, title=标题)"

    @staticmethod
    def _build(*args, **kwargs):
        try:                                   # 参数个数 / 名字不对是模型的用法问题，记 ChartError
            b = _CHART_SIG.bind(*args, **kwargs)
        except TypeError as e:
            raise ChartError(f"{ChartSlot._USAGE}（{e}）") from None
        a = {**{k: None for k in _CHART_SIG.parameters}, **b.arguments}
        if a["kind"] is None or a["df"] is None:
            raise ChartError(ChartSlot._USAGE)
        return build_option(a["kind"], a["df"], x=a["x"], y=a["y"], series=a["series"], title=a["title"])

    def finish(self, exec_ok: bool) -> dict:
        """worker 在 exec 结束后调用（独立 try，不影响 result）。exec 失败时槽位里的图一律丢弃（[23]）。
        注意：这里仍在沙箱进程里，模型代码可能改过本对象甚至本模块，所以输出只是"候选"，
        主进程用 accept_worker_charts() 重新校验，那一道才算数。"""
        out = {"charts": [], "chart_calls": 0, "chart_errors": [], "chart_internal_errors": [],
               "charts_discarded": 0}
        try:
            specs = list(self.specs)
            out["chart_calls"] = int(self.calls)
            out["chart_errors"] = list(self.errors)
            out["chart_internal_errors"] = list(self.internal)
            if exec_ok:
                out["charts"] = specs
            else:
                out["charts_discarded"] = len(specs)
        except Exception as e:  # noqa: BLE001
            out["chart_internal_errors"] = [f"finish 异常：{type(e).__name__}"]
        return out


_MSG_MAX = 500


def _msgs(v) -> list:
    if not isinstance(v, list):
        return []
    return [_clean_str(m if isinstance(m, str) else repr(m), _MSG_MAX) for m in v[:20]]


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10 ** 6 else 0


def accept_worker_charts(out: dict) -> dict:
    """主进程（可信）对沙箱回传的图表字段做最终校验。沙箱进程整体视为不可信：
    条数上限、每个 spec 过 validate_spec、消息清洗限长、truncated 警告由这里生成。永不抛异常。"""
    res = {"charts": [], "chart_calls": _int(out.get("chart_calls")),
           "chart_errors": _msgs(out.get("chart_errors")),
           "chart_internal_errors": _msgs(out.get("chart_internal_errors")),
           "charts_discarded": _int(out.get("charts_discarded")), "chart_warnings": []}
    raw = out.get("charts")
    if not isinstance(raw, list):
        raw = []
    if len(raw) > MAX_CHARTS:
        res["chart_internal_errors"].append(f"回传了 {len(raw)} 张图，超过上限 {MAX_CHARTS}，多出的丢弃")
    for spec in raw[:MAX_CHARTS]:
        try:
            problems = validate_spec(spec)
        except Exception as e:  # noqa: BLE001
            problems = [f"校验异常：{type(e).__name__}"]
        if problems:
            res["chart_internal_errors"].append("主进程复检未通过：" + "；".join(problems[:3]))
            continue
        res["charts"].append(spec)
        if spec["truncated"]:
            name = _clean_str(_spec_title(spec), TITLE_MAX) or spec["kind"]
            res["chart_warnings"].append(f"图表「{name}」数据点超过 {MAX_POINTS}，只显示了前面的部分")
    return res
