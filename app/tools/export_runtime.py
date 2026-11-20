"""导出脚本的运行时（阶段 7.5 第 2 步「代码导出」）。

**本文件的源码会原样嵌进导出的 .py**（app/tools/export.py 读本文件、去掉这段模块说明后拼进去），所以：
- 只许 import 标准库、numpy、pandas、matplotlib、openpyxl（干净 venv 里只有这几个），**不许 import app.***；
- 顶层名字一律 `_dc_` 开头，免得和模型代码里的变量撞名（模型代码在导出脚本里是顶层代码）；
- 读数规则必须与 DataChat 一致，逐项对照：
  CSV  → app/tools/csv_io.py（BOM → 严格 utf-8 → 严格 gb18030，去掉开头的 \\ufeff，pd.read_csv 默认参数）；
  xlsx → app/tools/excel_io.py 的「结构」部分（隐藏 / 空 sheet 跳过、横跨全表的合并标题行跳过、
         合并单元格推出的多行表头用「-」连接、横向合并填满、Unnamed / .1 列名、NA 标记、日期 → ISO 文本、
         混合列 → 文本、文本形式的数字如 00123 保持文本、表名 = 文件名[.sheet 名]）；
         只做结构，不产出读取提示 / 模型注解（那是给界面和 prompt 的，不影响取值）；
  表的组织 → app/tools/dataset.py 的 load_data（单文件 → df；多表 → dfs，表名排序）。
  与 DataChat 的一致性由 tests/test_export.py 的对照测试钉住（同一批 xlsx 用两边读，DataFrame 逐值相等）。
- 不做的事：公式无缓存值的检查（DataChat 上传时已拒绝这类文件；换了数据文件靠 sha256 提示）、体积上限。

chart() 是一个只依赖 pandas + matplotlib 的最小实现：签名与 DataChat 的 chart(kind, df, x=, y=, series=, title=) 一致，
五种图型，每次调用落一张 PNG；和 DataChat 一样永不抛异常（参数不对时打印原因、不出图）。
它只保证「出得来、数字取自同一张表」，样式不追求与界面上的 ECharts 一致。
"""
# ===================== DataChat 导出运行时（开始） =====================
import codecs as _dc_codecs
import datetime as _dc_dt
import hashlib as _dc_hashlib
import io as _dc_io
import math as _dc_math
import os as _dc_os
import sys as _dc_sys

import numpy as np
import pandas as pd

# 输出到管道 / 文件时，Python 按系统区域编码写（英文 Windows 是 cp1252），中文的 print 会抛 UnicodeEncodeError、脚本中断。
# 不是控制台的流一律改成 UTF-8；控制台（isatty）在 Windows 上走宽字符接口，本来就能显示中文，不动。
for _dc_stream in (_dc_sys.stdout, _dc_sys.stderr):
    try:
        if _dc_stream is not None and not _dc_stream.isatty():
            _dc_stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass

_DC_NA_STRINGS = frozenset({"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
                            "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"})
_DC_INCLUDE_HIDDEN_SHEETS = False
_DC_SHEET_NAME_SEP = "."
_DC_HEADER_JOIN = "-"
_DC_MAX_HEADER_ROWS = 3
_DC_BOMS = [(_dc_codecs.BOM_UTF32_LE, "utf-32"), (_dc_codecs.BOM_UTF32_BE, "utf-32"),
            (_dc_codecs.BOM_UTF8, "utf-8-sig"), (_dc_codecs.BOM_UTF16_LE, "utf-16"),
            (_dc_codecs.BOM_UTF16_BE, "utf-16")]


def _dc_sha256(path):
    h = _dc_hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dc_locate(data_dir, filename, script_dir):
    """先找 DATA_DIR，再找脚本所在目录。"""
    for d in (data_dir, script_dir):
        if d:
            p = _dc_os.path.join(d, filename)
            if _dc_os.path.isfile(p):
                return p
    raise FileNotFoundError(f"找不到数据文件 {filename!r}：请把它放在脚本旁边，或修改脚本顶部的 DATA_DIR")


# ---------------------------------------------------------------- CSV（同 app/tools/csv_io.py）
def _dc_read_csv(path):
    with open(path, "rb") as f:
        data = f.read()
    enc = None
    for bom, name in _DC_BOMS:
        if data.startswith(bom):
            enc = name
            break
    if enc is None:
        for name in ("utf-8", "gb18030"):
            try:
                data.decode(name, errors="strict")
                enc = name
                break
            except UnicodeDecodeError:
                continue
    if enc is None:
        raise ValueError(f"无法识别 {_dc_os.path.basename(path)} 的编码（已试 BOM、utf-8、gb18030）")
    text = data.decode(enc, errors="strict")
    if text.startswith("\ufeff"):
        text = text[1:]
    return pd.read_csv(_dc_io.StringIO(text))


# ---------------------------------------------------------------- xlsx（同 app/tools/excel_io.py 的结构部分）
def _dc_text(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, _dc_dt.datetime):
        return v.date().isoformat() if v.time() == _dc_dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, (_dc_dt.date, _dc_dt.time)):
        return v.isoformat()
    if isinstance(v, _dc_dt.timedelta):
        return str(v)
    if isinstance(v, float):
        if _dc_math.isfinite(v) and v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def _dc_norm(v):
    if isinstance(v, (_dc_dt.datetime, _dc_dt.date, _dc_dt.time, _dc_dt.timedelta)):
        return _dc_text(v)
    if isinstance(v, str) and v in _DC_NA_STRINGS:
        return None
    return v


def _dc_column(vals):
    nn = [v for v in vals if v is not None]
    if not nn:
        return pd.Series([np.nan] * len(vals), dtype="float64")
    if all(isinstance(v, bool) for v in nn):
        if len(nn) == len(vals):
            return pd.Series(vals, dtype="bool")
        return pd.Series([np.nan if v is None else v for v in vals], dtype=object)
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nn):
        if len(nn) == len(vals) and all(isinstance(v, int) for v in nn) \
                and all(-2 ** 63 <= v < 2 ** 63 for v in nn):
            return pd.Series(vals, dtype="int64")
        return pd.Series([np.nan if v is None else float(v) for v in vals], dtype="float64")
    if all(isinstance(v, str) for v in nn):
        return pd.Series([np.nan if v is None else v for v in vals])
    return pd.Series([np.nan if v is None else _dc_text(v) for v in vals])


def _dc_csv_names(raw):
    names = []
    for j, v in enumerate(raw):
        v = None if v is None else (_dc_text(v) if not isinstance(v, str) else v)
        names.append(f"Unnamed: {j}" if v is None or v == "" else v)
    counts, out = {}, []
    for col in names:
        cur = counts.get(col, 0)
        while cur > 0:
            counts[col] = cur + 1
            col = f"{col}.{cur}"
            cur = counts.get(col, 0)
        out.append(col)
        counts[col] = cur + 1
    return out


def _dc_build_sheet(merges, grid):
    """merges: [(min_row, min_col, max_row, max_col)]；grid: {row: {col: value}}（只放非空值）。"""
    rows = sorted(r for r, cells in grid.items() if cells)
    if not rows:
        return None
    merges_at = {(m[0], m[1]): m for m in merges}

    def box(rs):
        cs = [c for r in rs for c in grid.get(r, {})]
        return min(cs), max(cs)

    top = rows[0]
    titles = 0
    while titles < _DC_MAX_HEADER_ROWS:          # 横跨全表的合并标题行
        cells = grid.get(top, {})
        rest = [r for r in rows if r > top]
        if len(cells) != 1 or not rest:
            break
        (col, _val), = cells.items()
        m = merges_at.get((top, col))
        if m is None or m[3] == m[1]:
            break
        rest = [r for r in rows if r > m[2]]
        if not rest:
            break
        lo, hi = box(rest)
        if not (m[1] <= lo and m[3] >= hi):
            break
        titles += 1
        top = rest[0]
    if titles:
        rows = [r for r in rows if r >= top]
    c_lo, c_hi = box(rows)

    depth = 1                                     # 合并单元格推出表头有几行
    for m in merges:
        if m[0] == top and m[1] >= c_lo and m[3] <= c_hi:
            depth = max(depth, m[2] - top + 2) if m[3] > m[1] else max(depth, m[2] - top + 1)
    horizontal_only = False
    if depth > 1:
        sub = top + depth - 1
        hz = [m for m in merges if m[0] == top and m[3] > m[1] and m[1] >= c_lo and m[3] <= c_hi]
        sub_ok = all(isinstance(grid.get(sub, {}).get(c), str)
                     for m in hz for c in range(m[1], m[3] + 1) if m[2] < sub)
        vert = any(m[0] == top and m[2] > top for m in merges)
        if not sub_ok and not vert:
            depth, horizontal_only = 1, True
    depth = min(depth, _DC_MAX_HEADER_ROWS)
    h_end = top + depth - 1

    def header_value(r, c):
        v = grid.get(r, {}).get(c)
        if v is not None:
            return v
        for m in merges:
            if m[0] <= r <= m[2] and m[1] <= c <= m[3] and m[0] >= top:
                return grid.get(m[0], {}).get(m[1])
        return None

    if depth > 1:
        raw = []
        for c in range(c_lo, c_hi + 1):
            parts = []
            for r in range(top, h_end + 1):
                v = header_value(r, c)
                if v is None:
                    continue
                t = _dc_text(v)
                if not parts or parts[-1] != t:
                    parts.append(t)
            raw.append(_DC_HEADER_JOIN.join(parts) if parts else None)
    elif horizontal_only:
        raw = [header_value(top, c) for c in range(c_lo, c_hi + 1)]
    else:
        raw = [grid.get(top, {}).get(c) for c in range(c_lo, c_hi + 1)]
    names = _dc_csv_names(raw)
    data_rows = [r for r in rows if r > h_end]
    cols = [[_dc_norm(grid.get(r, {}).get(c)) for r in data_rows] for c in range(c_lo, c_hi + 1)]
    return pd.DataFrame({n: _dc_column(v) for n, v in zip(names, cols)}, index=pd.RangeIndex(len(data_rows)))


def _dc_read_xlsx(path):
    """→ [(sheet 名, DataFrame)]，只含读出来的 sheet（隐藏的、空的跳过）。"""
    import warnings
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible" and not _DC_INCLUDE_HIDDEN_SHEETS:
                continue
            grid = {}
            for row in ws.iter_rows():
                for cell in row:
                    v = getattr(cell, "value", None)
                    if v is None or (isinstance(v, str) and v == ""):
                        continue
                    grid.setdefault(cell.row, {})[cell.column] = v
            merges = [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges]
            df = _dc_build_sheet(merges, grid)
            if df is not None:
                out.append((ws.title, df))
    finally:
        wb.close()
    if not out:
        raise ValueError(f"{_dc_os.path.basename(path)} 里没有可读的数据表")
    return out


def _dc_excel_tables(stem, path):
    sheets = _dc_read_xlsx(path)
    if len(sheets) == 1:
        return [(stem, sheets[0][1])]
    return [(f"{stem}{_DC_SHEET_NAME_SEP}{s}", d) for s, d in sheets]


# ---------------------------------------------------------------- 数据集（同 app/tools/dataset.py 的 load_data）
def _dc_load(data_dir, files, multi_source, script_dir, check_sha256=True):
    """files: [(文件名, 导出时的 sha256 或 None)]。multi_source：数据集是多个文件（→ 一律 dfs）。
    返回 DataFrame（单表）或 {表名: DataFrame}（多表）。"""
    paths = []
    for name, sha in files:
        p = _dc_locate(data_dir, name, script_dir)
        if check_sha256 and sha and _dc_sha256(p) != sha:
            print(f"注意：{name} 与导出时的文件内容不同（sha256 不一致），结果可能和 DataChat 里不一样",
                  file=_dc_sys.stderr)
        paths.append(p)
    is_xlsx = [p.lower().endswith(".xlsx") for p in paths]
    if not multi_source:
        p = paths[0]
        if not is_xlsx[0]:
            return _dc_read_csv(p)
        named = _dc_excel_tables(_dc_os.path.splitext(_dc_os.path.basename(p))[0], p)
        return named[0][1] if len(named) == 1 else dict(named)
    by_name = sorted((_dc_os.path.splitext(_dc_os.path.basename(p))[0], p, x) for p, x in zip(paths, is_xlsx))
    data = {}
    for name, p, x in by_name:
        if x:
            for tname, d in _dc_excel_tables(name, p):
                data[tname] = d
        else:
            data[name] = _dc_read_csv(p)
    return data


# ---------------------------------------------------------------- chart()：只依赖 pandas + matplotlib 的最小实现
_DC_KINDS = ("bar", "line", "area", "pie", "scatter")
_DC_MAX_CHARTS = 4


class _DcChart:
    """chart(kind, df, x=None, y=None, series=None, title=None)：每次调用落一张 PNG 到 out_dir。永不抛异常。"""

    def __init__(self, out_dir, stem):
        self.out_dir, self.stem = out_dir, stem
        self.calls = 0
        self.saved = []
        self.errors = []

    def __call__(self, kind=None, df=None, x=None, y=None, series=None, title=None):
        self.calls += 1
        try:
            if len(self.saved) >= _DC_MAX_CHARTS:
                raise ValueError(f"每次执行最多 {_DC_MAX_CHARTS} 张图")
            path = _dc_os.path.join(self.out_dir, f"{self.stem}_chart{len(self.saved) + 1}.png")
            self._draw(kind, df, x, y, series, title, path)
            self.saved.append(path)
            print(f"[chart] 已保存 {path}", file=_dc_sys.stderr)
        except Exception as e:  # noqa: BLE001 —— 与 DataChat 一致：chart() 出错不打断代码
            self.errors.append(str(e))
            print(f"[chart] 第 {self.calls} 次 chart() 未出图：{e}", file=_dc_sys.stderr)
        return None

    @staticmethod
    def _frame(df):
        if isinstance(df, pd.Series):
            name = df.name if df.name is not None else "值"
            idx = df.index.name if df.index.name is not None else "类别"
            if idx == name:
                idx = f"{idx}_"
            return pd.DataFrame({idx: list(df.index), name: df.to_numpy()}), idx
        if isinstance(df, pd.DataFrame):
            return df, None
        raise TypeError(f"df 必须是 DataFrame 或 Series，收到 {type(df).__name__}")

    def _draw(self, kind, df, x, y, series, title, path):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        if kind not in _DC_KINDS:
            raise ValueError(f"不支持的图型 {kind!r}；可用：{', '.join(_DC_KINDS)}")
        frame, default_x = self._frame(df)
        if x is None:
            x = default_x
        if frame.empty:
            raise ValueError("数据为空，不出图")
        xs = pd.Series(list(frame.index), index=frame.index) if x is None else frame[x]
        if y is None:
            cand = [c for c in frame.columns if c not in (x, series) and pd.api.types.is_numeric_dtype(frame[c])
                    and not pd.api.types.is_bool_dtype(frame[c])]
            if len(cand) != 1:
                raise ValueError("没给 y，且无法唯一确定数值列")
            ys = cand
        else:
            ys = list(y) if isinstance(y, (list, tuple)) else [y]
        if series is not None:                         # 长表 → 宽表：每组一个系列
            wide = frame.assign(_dc_x=xs.to_numpy()).pivot(index="_dc_x", columns=series, values=ys[0])
            labels, cols = list(wide.index), {str(c): wide[c].to_numpy() for c in wide.columns}
        else:
            labels, cols = list(xs), {str(c): frame[c].to_numpy() for c in ys}
        fig = Figure(figsize=(8, 5), dpi=120)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        if kind == "pie":
            name, vals = next(iter(cols.items()))
            ax.pie(vals, labels=[str(v) for v in labels], autopct="%1.1f%%")
            ax.axis("equal")
        elif kind == "scatter":
            for name, vals in cols.items():
                ax.scatter(labels, vals, label=name)
            ax.set_xlabel(str(x))
        else:
            pos = np.arange(len(labels))
            n = len(cols)
            for i, (name, vals) in enumerate(cols.items()):
                if kind == "bar":
                    w = 0.8 / n
                    ax.bar(pos - 0.4 + w * (i + 0.5), vals, width=w, label=name)
                else:
                    ax.plot(pos, vals, marker="o" if len(labels) <= 60 else None, label=name)
                    if kind == "area":
                        ax.fill_between(pos, vals, alpha=0.25)
            ax.set_xticks(pos)
            ax.set_xticklabels([str(v) for v in labels], rotation=30 if len(labels) > 8 else 0, ha="right"
                               if len(labels) > 8 else "center")
        if kind != "pie" and len(cols) > 1:
            ax.legend()
        if title:
            ax.set_title(str(title))
        fig.savefig(path, bbox_inches="tight")


def _dc_setup_matplotlib():
    """中文字体兜底（与 DataChat 的候选字体同一批）；找不到就用 matplotlib 默认字体（中文可能显示成方框）。"""
    from matplotlib import font_manager, rcParams
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/System/Library/Fonts/PingFang.ttc"):
        if _dc_os.path.exists(p):
            try:
                font_manager.fontManager.addfont(p)
                rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=p).get_name(), "DejaVu Sans"]
                rcParams["font.family"] = "sans-serif"
                break
            except Exception:  # noqa: BLE001
                continue
    rcParams["axes.unicode_minus"] = False
# ===================== DataChat 导出运行时（结束） =====================
