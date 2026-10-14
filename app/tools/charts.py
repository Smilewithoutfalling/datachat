"""结构化图表（M13，阶段 5 第 1 步）：DataFrame → ECharts option，以及 option 的白名单校验。

约定（见 DEVLOG [22] 与 S 的 M13 方案 v3）：
- 模型只通过 chart(kind, df, x=, y=, series=, title=) 出图，只选图型、列和标题；
  数据层（xAxis.data / series[].data）全部由 build_option 从 df 生成，模型写不进数字。
- v1 图型：bar / line / area / pie / scatter。横向、堆叠、平滑、数值标签等是前端开关，不在这里。
- 不产出 dataset；不产出任何函数、formatter 模板、link、graphic；产出必须是严格 JSON（无 NaN / Infinity）。
- build_option 是纯函数，失败抛 ChartError；chart()（沙箱里的薄包装，第 2 步接入）负责吞异常、记 chart_error。
- validate_spec 是丢弃式白名单之前的最后一道：未知键、禁用键、非法类型、超量数据 → 整图拒绝并给出原因。

返回的 spec 结构（v1）：
    {"v": 1, "kind": "bar", "truncated": False, "option": {...ECharts option...}}
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

SPEC_VERSION = 1
KINDS = ("bar", "line", "area", "pie", "scatter")
MAX_POINTS = 5000          # 每张图的数据点上限（类目数 × 系列数）
MAX_SERIES = 20
MAX_PIE_SLICES = 50
TITLE_MAX = 100
NAME_MAX = 100             # 系列名、坐标轴名
CATEGORY_MAX = 200         # 单个类目名

# 与 matplotlib 风格（plotting.PALETTE）同一套主色，前端主题可整体覆盖
PALETTE = ["#1F6FB2", "#159A8C", "#E2843B", "#C0392B", "#7E57C2", "#3A7D44"]

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ChartError(ValueError):
    """builder 无法按给定参数出图（列不存在、类型不符、参数冲突等）。消息给模型和用户看，用中文。"""


# ------------------------------------------------------------------ 值转换
def _clean_str(s, limit: int) -> str:
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


def _label(v) -> str | None:
    """类目 → 字符串；时间 → ISO；缺失 → None。"""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
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
        cols = "、".join(map(str, list(df.columns)[:20]))
        raise ChartError(f"{what}列 {name!r} 不存在；可用列：{cols}")
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

    option["color"] = list(PALETTE)
    if title_txt:
        option["title"] = {"text": title_txt, "left": "center"}
    spec = {"v": SPEC_VERSION, "kind": kind, "truncated": truncated, "option": option}
    problems = validate_spec(spec)
    if problems:                                  # builder 自身的 bug 也不能放出去
        raise ChartError("图表未通过校验：" + "；".join(problems[:3]))
    return spec


def _wide(frame, xs, ys, series_col):
    """统一成 (类目标签列表, [(系列名, 数值列表)])。长表按 series 透视，保留 x 的首次出现顺序。"""
    if series_col is None:
        cats = [_label(v) for v in xs]
        return cats, [(_clean_str(c, NAME_MAX), [_num(v) for v in frame[c]]) for c in ys]
    ycol = ys[0]
    tmp = pd.DataFrame({"_x": [_label(v) for v in xs], "_s": frame[series_col].map(_label), "_y": frame[ycol]})
    if tmp.duplicated(["_x", "_s"]).any():
        raise ChartError("长表里同一 (x, series) 出现多行，请先 groupby 聚合")
    cats = list(dict.fromkeys(tmp["_x"]))
    groups = list(dict.fromkeys(tmp["_s"]))
    if len(groups) > MAX_SERIES:
        raise ChartError(f"series 分组太多（{len(groups)}），最多 {MAX_SERIES} 个；先筛选或合并为'其他'")
    pv = tmp.pivot(index="_x", columns="_s", values="_y").reindex(index=cats, columns=groups)
    return cats, [(_clean_str("（空）" if g is None else g, NAME_MAX), [_num(v) for v in pv[g]]) for g in groups]


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
            s["showSymbol"] = len(cats) <= 60
        out_series.append(s)
    x_name = "" if xs.name is None else _clean_str(xs.name, NAME_MAX)
    y_name = _clean_str(ys[0], NAME_MAX) if (series_col is not None or not multi) else ""
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": multi, "top": "bottom"},
        "grid": {"left": "3%", "right": "4%", "top": 60, "bottom": 50 if multi else 30, "containLabel": True},
        "xAxis": {"type": "category", "name": x_name, "data": ["" if c is None else c for c in cats],
                  "boundaryGap": kind == "bar"},
        "yAxis": {"type": "value", "name": y_name},
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
    items = [{"name": "（空）" if (lab := _label(c)) is None else lab, "value": v}
             for c, v in zip(xs, vals) if v is not None]
    if len(items) > MAX_PIE_SLICES:
        raise ChartError(f"饼图扇区太多（{len(items)}），最多 {MAX_PIE_SLICES} 个；先取 Top-N 并合并为'其他'")
    option = {
        "tooltip": {"trigger": "item"},
        "legend": {"show": True, "type": "scroll", "orient": "vertical", "left": "left", "top": "middle"},
        "series": [{"name": _clean_str(ys[0], NAME_MAX), "type": "pie", "radius": ["0%", "65%"],
                    "center": ["60%", "55%"], "data": items}],
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
        keys = frame[series_col].map(_label)
        order = list(dict.fromkeys(keys))
        if len(order) > MAX_SERIES:
            raise ChartError(f"series 分组太多（{len(order)}），最多 {MAX_SERIES} 个")
        for g in order:
            m = (keys == g).to_numpy()
            groups.append((_clean_str("（空）" if g is None else g, NAME_MAX), list(zip(xs[m], frame[ycol][m]))))
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
        "grid": {"left": "3%", "right": "4%", "top": 60, "bottom": 50 if len(out) > 1 else 30, "containLabel": True},
        "xAxis": {"type": "value", "name": _clean_str(xs.name, NAME_MAX) if xs.name is not None else "", "scale": True},
        "yAxis": {"type": "value", "name": _clean_str(ys[0], NAME_MAX) if len(ys) == 1 else "", "scale": True},
        "series": out,
    }
    return option, truncated


# ------------------------------------------------------------------ 白名单校验
# 结构：dict 的值是子结构；类型元组表示叶子允许的 Python 类型。"*" 表示数组元素结构。
_STR, _NUM, _BOOL = (str,), (int, float), (bool,)
_POS = (str, int, float)                         # "3%" / 60 / "center"
_STYLE_TEXT = {"color": _STR, "fontSize": _NUM, "fontWeight": (str, int)}
_ALLOWED = {
    "color": {"*": _STR},
    "title": {"text": _STR, "left": _POS, "top": _POS, "textStyle": _STYLE_TEXT},
    "tooltip": {"trigger": _STR},
    "legend": {"show": _BOOL, "type": _STR, "top": _POS, "left": _POS, "orient": _STR},
    "grid": {"left": _POS, "right": _POS, "top": _POS, "bottom": _POS, "containLabel": _BOOL},
    "xAxis": {"type": _STR, "name": _STR, "data": {"*": _STR}, "boundaryGap": _BOOL, "scale": _BOOL,
              "axisLabel": {"hideOverlap": _BOOL, "rotate": _NUM}},
    "yAxis": {"type": _STR, "name": _STR, "scale": _BOOL},
    "series": {"*": {
        "name": _STR, "type": _STR, "data": None,          # data 单独按图型校验
        "areaStyle": {"opacity": _NUM}, "showSymbol": _BOOL, "symbolSize": _NUM,
        "stack": _STR, "smooth": _BOOL,
        "label": {"show": _BOOL, "position": _STR},
        "itemStyle": {"color": _STR, "borderRadius": _NUM},
        "radius": {"*": _STR}, "center": {"*": _STR},
    }},
}
# 明确禁止（即使将来放宽白名单也不许出现）：会进 DOM 或执行代码的通道，以及数据层绕过面
BANNED_KEYS = {"link", "sublink", "graphic", "formatter", "renderItem", "dataset", "aria", "toolbox",
               "rich", "renderMode", "extraCssText", "target", "sublinkTarget"}
_ENUMS = {
    ("tooltip", "trigger"): {"axis", "item"},
    ("legend", "type"): {"plain", "scroll"},
    ("legend", "orient"): {"horizontal", "vertical"},
    ("xAxis", "type"): {"category", "value"},
    ("yAxis", "type"): {"value"},
    ("series", "type"): {"bar", "line", "pie", "scatter"},
    ("series", "label", "position"): {"top", "inside", "outside", "insideTop", "right"},
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
    for i, c in enumerate(option.get("color") or []):
        if isinstance(c, str) and not _HEX.match(c):
            problems.append(f"color.{i} 必须是 #RRGGBB")
    for i, s in enumerate(option.get("series") or []):
        c = (s.get("itemStyle") or {}).get("color") if isinstance(s, dict) else None
        if isinstance(c, str) and not _HEX.match(c):
            problems.append(f"series.{i}.itemStyle.color 必须是 #RRGGBB")


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
    if not isinstance(spec, dict) or set(spec) != {"v", "kind", "truncated", "option"}:
        return ["spec 结构应为 {v, kind, truncated, option}"]
    if spec["v"] != SPEC_VERSION:
        problems.append(f"不支持的 spec 版本 {spec['v']!r}")
    if spec["kind"] not in KINDS:
        problems.append(f"未知图型 {spec['kind']!r}")
    if not isinstance(spec["truncated"], bool):
        problems.append("truncated 应为布尔值")
    option = spec["option"]
    if not isinstance(option, dict) or not isinstance(option.get("series"), list) or not option["series"]:
        return problems + ["option.series 应为非空数组"]
    _walk(option, _ALLOWED, [], problems)
    _check_enums(option, problems)
    _check_data(option, problems)
    try:
        json.dumps(spec, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        problems.append(f"不是严格 JSON：{e}")
    return problems
