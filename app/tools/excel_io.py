"""xlsx 读取（阶段 7.5 第 2 步，docs/roadmap/phase75-assess.md §2.1）。

原则：**读出来的 DataFrame 与「同一份内容的 CSV 经 read_csv_with_encoding 读出来」形态一致**——
表头命名（空表头 → `Unnamed: k`、重名 → `x.1`）、整数/浮点推断、缺失标记（NA、#N/A 等按 pandas
默认 na_values 读成 NaN）、整行空白跳过，都和 CSV 路径同一套规则。CSV 路径不在读取时清洗的东西
（标题行、两行表头、合计行、千分位 / 百分号 / 货币符号文本、尾部备注），这里也不清洗，交给分析链路，
和扰动评测（docs/eval/perturb.md）的口径一致；但 xlsx 能看到的结构信号（合并单元格、公式、单元格格式）
用来做两件事：能安全修正的修正，修不了的明确告知。

逐项处理方式（矩阵见 tests/test_excel_io.py）：

| 情况 | 处理 | 告知 |
|---|---|---|
| 公式没有缓存值 | **拒绝**（FormulaNoCacheError）：否则读成空值，聚合算成 0 不报错 | 错误文案：用 Excel / WPS 打开保存一次 |
| 表头前的空行 / 左侧空列 | 跳过（read_csv 也跳过空行；空列在表外，不含数据） | 用户提示 |
| 横跨全表的合并标题行 | 跳过（合并区域是确定的结构信号） | 用户提示 + 模型注解（标题里常有单位） |
| 不合并、只有一格的首行 | 不动（与 CSV 一致，列名会是 Unnamed） | 用户提示 |
| 表头里的合并单元格（多行表头） | 合并成一行列名（上层-下层） | 用户提示 |
| 表头里只有横向合并、下一行是数据 | 合并格的名字填到整片区域，重名按 `.1` 消歧 | 用户提示 |
| 没有合并的两行表头 | 不动（与 CSV 一致） | 第二行全是文字、下面是数字时提示 |
| 数据区的合并单元格 | 不填充（与 read_excel 一致：除左上角都是空值） | 用户提示 + 模型注解 |
| 日期格式的单元格 | 读成 ISO 文本（与 CSV 里的日期一样是文本列） | 无 |
| 没有日期格式、但像日期序列号的整数列 | 不转换（判不准） | 用户提示 + 模型注解 |
| 百分比格式的数字 | 读出底层小数 | 用户提示 + 模型注解 |
| 千分位 / 货币格式的数字 | 读出底层数值（格式只影响显示） | 无 |
| 文本形式的千分位 / 百分号 / 货币数字 | 不转换（与 CSV 一致） | 用户提示 |
| 最后一行是合计（文字或求和公式） | 不删（与 CSV 一致） | 用户提示 + 模型注解 |
| Excel 错误值（#DIV/0! 等） | 按文本读入（#N/A 按 na_values 是 NaN） | 用户提示 + 模型注解 |
| 空 sheet | 跳过 | 用户提示；全部为空 → 拒绝 |
| 隐藏 sheet | 跳过（INCLUDE_HIDDEN_SHEETS 可改） | 用户提示 |
| 重复列名 / 空列 | 与 CSV 一致（`x.1` / `Unnamed: k`） | 用户提示 |
| 文本形式的数字（如 00123） | **保持文本**——这是唯一有意偏离 CSV 的地方：CSV 读成整数会丢前导零 | 无 |

用户提示进 `df.attrs[WARNINGS_ATTR]`（上传预览、加载说明里显示）；模型注解进 `df.attrs[NOTES_ATTR]`，
由 `describe_df` 附在表结构说明后面。模型注解**只写列名，不写单元格取值**（出境审计口径，
app/eval/egress.py），唯一例外是被跳过的标题行文本（截断到 MAX_CELL_CHARS），因为单位常写在标题里。

不支持 .xls：旧版二进制格式要额外的 xlrd 依赖，且没有本文件依赖的 XML 结构（合并区域、公式缓存）可以
直接核对；上传时明确拒绝，提示另存为 .xlsx 或 CSV。
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import posixpath
import re
import warnings
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.tools.dataset import DatasetError   # dataset.py 只在函数里 import 本模块，不成环

# ---------------------------------------------------------------- 可配置项（待 S 拍板，见 DEVLOG）
# 解压后体积上限：xlsx 是 zip，解压后常是原文件的数倍，openpyxl 又要把整本读进内存。
# 按 zip 各成员声明的 file_size 之和判；zipfile 读成员时不会读出超过声明长度的数据，所以伪造头部也撑不爆。
# 默认 300 MB（S 2026-11-19 定）：解压后 1 GB 大约是千万级单元格，桌面 sidecar 内存会到 GB 级；
# 先按 300 MB 上线，量完真实大文件的内存峰值再谈放宽。CSV 的单文件 1 GB 上限（app/server/app.py）不受影响。
MAX_XLSX_UNCOMPRESSED_BYTES = int(os.getenv("DATACHAT_MAX_XLSX_BYTES", str(300 * 1024 * 1024)))
INCLUDE_HIDDEN_SHEETS = False     # 隐藏 / 深度隐藏的 sheet 默认不读
SHEET_NAME_SEP = "."              # 多 sheet 时表名 = 文件名 + SEP + sheet 名
HEADER_JOIN = "-"                 # 多行表头合并成一行时的连接符
MAX_HEADER_ROWS = 3               # 合并单元格推出来的表头最多几行；更深的不猜，提示

EXCEL_SUFFIXES = (".xlsx",)
WARNINGS_ATTR = "datachat_load_warnings"   # 给用户看的读取提示（list[str]）
from app.tools.schema import MODEL_NOTES_ATTR as NOTES_ATTR   # 给模型看的结构注解（list[str]，不含取值），describe_df 读

# pandas read_csv 默认的缺失标记（pandas._libs.parsers.STR_NA_VALUES，写死一份免得依赖私有模块）
NA_STRINGS = frozenset({"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
                        "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"})
_TOTAL_TEXT = re.compile(r"^\s*(合计|总计|小计|总和|共计|total|grand total|sum)\b", re.I)
_SUM_FORMULA = re.compile(r"\b(SUM|SUBTOTAL|AGGREGATE)\s*\(", re.I)
_DATE_HEADER = re.compile(r"日期|时间|年月|date|time|day", re.I)
_TEXT_NUMBER = re.compile(r"^\s*[¥￥$€£]?\s*[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?\s*%?\s*(元|万元)?\s*$")
_TEXT_NUMBER_DECORATED = re.compile(r"[,%¥￥$€£元]")
SERIAL_RANGE = (20000, 80000)     # 1954-10 … 2119-01 的 Excel 日期序列号


class ExcelError(DatasetError, ValueError):
    """xlsx 结构问题，文案是给用户看的中文（不带路径）。"""


class XlsxTooLargeError(ExcelError):
    pass


class XlsxInvalidError(ExcelError):
    pass


class FormulaNoCacheError(ExcelError):
    pass


class NoSheetError(ExcelError):
    pass


def is_excel(path) -> bool:
    return os.fspath(path).lower().endswith(EXCEL_SUFFIXES)


# ---------------------------------------------------------------- 体积
def uncompressed_size(path) -> int:
    try:
        with zipfile.ZipFile(path) as z:
            return sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as e:
        raise XlsxInvalidError("不是有效的 xlsx 文件（可能设置了打开密码，或是改了扩展名的 .xls）") from e


def check_size(path, limit: int | None = None) -> int:
    limit = MAX_XLSX_UNCOMPRESSED_BYTES if limit is None else limit
    size = uncompressed_size(path)
    if size > limit:
        raise XlsxTooLargeError(f"xlsx 解压后 {size / 1024 ** 2:.0f} MB，超过上限 {limit // 1024 ** 2} MB。"
                                "请拆分文件，或另存为 CSV 后上传")
    return size


# ---------------------------------------------------------------- XML 结构扫描（合并、公式缓存、错误值）
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el, name):
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


_REF = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_ref(ref: str) -> tuple[int, int]:
    m = _REF.match(ref.upper())
    if not m:
        raise ValueError(ref)
    return int(m.group(2)), _col_index(m.group(1))


def _a1(r: int, c: int) -> str:
    return f"{_col_letters(c)}{r}"


@dataclass
class Merge:
    min_row: int
    min_col: int
    max_row: int
    max_col: int

    @property
    def ref(self) -> str:
        return f"{_a1(self.min_row, self.min_col)}:{_a1(self.max_row, self.max_col)}"


@dataclass
class SheetInfo:
    name: str
    state: str                    # visible | hidden | veryHidden
    part: str                     # zip 内的 xml 路径
    has_values: bool = False
    merges: list = field(default_factory=list)
    uncached: list = field(default_factory=list)      # 公式无缓存值的单元格 (row, col)
    sum_rows: set = field(default_factory=set)        # 含求和类公式的行号
    error_cells: list = field(default_factory=list)   # (row, col)


def _sheet_parts(z: zipfile.ZipFile) -> list[SheetInfo]:
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError as e:
        raise XlsxInvalidError("不是有效的 xlsx 文件（缺少工作簿结构）") from e
    targets = {}
    for rel in rels:
        if _local(rel.tag) == "Relationship" and (rel.get("Type") or "").endswith("/worksheet"):
            t = rel.get("Target") or ""
            t = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
            targets[rel.get("Id")] = t
    out = []
    for el in wb.iter():
        if _local(el.tag) == "sheet":
            rid = _attr(el, "id")
            if rid in targets:      # chartsheet / dialogsheet 不是表，直接不列
                out.append(SheetInfo(name=el.get("name"), state=el.get("state") or "visible", part=targets[rid]))
    return out


_HAS_VALUE = re.compile(rb"<(?:\w+:)?v>[^<]|<(?:\w+:)?t(?:\s[^>]*)?>[^<]")
_HAS_STRUCT = re.compile(rb"<(?:\w+:)?f[\s>/]|\st=\"e\"|<(?:\w+:)?mergeCell[\s>/]")


def _quick_flags(z: zipfile.ZipFile, part: str) -> tuple[bool, bool]:
    """字节级快扫：(有没有值, 有没有公式 / 错误值 / 合并区域)。后者为假时省掉逐格解析（大表上约占读取时间的三分之一）。"""
    has_value = has_struct = False
    tail = b""
    with z.open(part) as f:
        while chunk := f.read(1 << 20):
            buf = tail + chunk
            has_value = has_value or bool(_HAS_VALUE.search(buf))
            has_struct = has_struct or bool(_HAS_STRUCT.search(buf))
            if has_value and has_struct:
                break
            tail = buf[-64:]
    return has_value, has_struct


def _scan_sheet(z: zipfile.ZipFile, info: SheetInfo) -> None:
    """流式扫一遍 sheet XML：有没有值、合并区域、没缓存值的公式、求和公式所在行、错误值。"""
    has_value, has_struct = _quick_flags(z, info.part)
    if not has_struct:
        info.has_values = has_value
        return
    shared = {}       # 共享公式 si → 主公式文本
    with z.open(info.part) as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            tag = _local(el.tag)
            if tag == "c":
                ref = el.get("r")
                t = el.get("t") or "n"
                fel = vel = isel = None
                for ch in el:
                    lt = _local(ch.tag)
                    if lt == "f":
                        fel = ch
                    elif lt == "v":
                        vel = ch
                    elif lt == "is":
                        isel = ch
                vtext = vel.text if vel is not None else None
                if (vtext not in (None, "")) or (isel is not None and "".join(isel.itertext())):
                    info.has_values = True
                if ref is None:
                    el.clear()
                    continue
                rc = _parse_ref(ref)
                if fel is not None:
                    ftext = fel.text or ""
                    si = fel.get("si")
                    if si is not None:
                        if ftext:
                            shared[si] = ftext
                        else:
                            ftext = shared.get(si, "")
                    # 公式格的 <v> 是缓存值。字符串结果为空串时 Excel 写 t="str" + 空 <v>，那是真的空串，不算缺缓存
                    if vtext in (None, "") and t not in ("str", "inlineStr"):
                        info.uncached.append(rc)
                    if _SUM_FORMULA.search(ftext):
                        info.sum_rows.add(rc[0])
                if t == "e" and vtext:
                    info.error_cells.append(rc)
                el.clear()
            elif tag == "mergeCell":
                ref = el.get("ref") or ""
                if ":" in ref:
                    (r1, c1), (r2, c2) = (_parse_ref(x) for x in ref.split(":", 1))
                    info.merges.append(Merge(min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)))
            elif tag == "row":
                el.clear()


def inspect(path) -> tuple[list[SheetInfo], list[SheetInfo], list[str]]:
    """返回 (要读的 sheet, 全部 sheet, 跳过说明)。只读 XML，不建 DataFrame；字典挂载也用它定表名。"""
    check_size(path)
    try:
        with zipfile.ZipFile(path) as z:
            infos = _sheet_parts(z)
            for info in infos:
                try:
                    _scan_sheet(z, info)
                except KeyError as e:
                    raise XlsxInvalidError(f"工作表「{info.name}」的数据缺失，文件可能已损坏") from e
                except ET.ParseError as e:
                    raise XlsxInvalidError(f"工作表「{info.name}」无法解析，文件可能已损坏") from e
    except zipfile.BadZipFile as e:
        raise XlsxInvalidError("不是有效的 xlsx 文件（可能设置了打开密码，或是改了扩展名的 .xls）") from e
    selected, skipped = [], []
    for info in infos:
        hidden = info.state != "visible"
        if hidden and not INCLUDE_HIDDEN_SHEETS:
            skipped.append(f"工作表「{info.name}」是隐藏的，已跳过")
        elif not info.has_values:
            skipped.append(f"工作表「{info.name}」是空的，已跳过")
        else:
            selected.append(info)
    return selected, infos, skipped


def table_names(stem: str, sheets: list[str]) -> list[str]:
    """表名规则（待 S 拍板）：只读出一张表时表名 = 文件名（和 CSV 一致），多张时 = 文件名.sheet名。
    「几张」按实际读出的算：默认新建工作簿带的空 Sheet2/Sheet3、隐藏的辅助表不让单表文件变成多表。"""
    if len(sheets) == 1:
        return [stem]
    return [f"{stem}{SHEET_NAME_SEP}{s}" for s in sheets]


# ---------------------------------------------------------------- 值 → DataFrame（与 read_csv 同规则）
def _is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and v == "")


def _text(v) -> str:
    """单元格值 → CSV 里会写出的文本（用于混合列、表头）。"""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, _dt.datetime):
        return v.date().isoformat() if v.time() == _dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return str(v)
    if isinstance(v, float):
        if math.isfinite(v) and v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def _norm(v):
    """单元格值标准化：日期 → ISO 文本；缺失标记 → None（与 read_csv 的 na_values 一致）。"""
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time, _dt.timedelta)):
        return _text(v)
    if isinstance(v, str) and v in NA_STRINGS:
        return None
    return v


def _column(vals: list) -> pd.Series:
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
    # 混合（数字 + 文字等）：CSV 读进来整列是文本，这里同样转成文本
    return pd.Series([np.nan if v is None else _text(v) for v in vals])


def _csv_names(raw: list) -> tuple[list[str], dict]:
    """表头 → 列名，与 read_csv 相同：空 → `Unnamed: k`，重名 → `x.1`（pandas _dedup_names 的算法）。"""
    names = []
    for j, v in enumerate(raw):
        v = None if v is None else (_text(v) if not isinstance(v, str) else v)
        names.append(f"Unnamed: {j}" if v is None or v == "" else v)
    counts: dict = {}
    out, dups = [], {}
    for col in names:
        cur = counts.get(col, 0)
        orig = col
        while cur > 0:
            counts[col] = cur + 1
            col = f"{col}.{cur}"
            cur = counts.get(col, 0)
        if col != orig:
            dups.setdefault(orig, []).append(col)
        out.append(col)
        counts[col] = cur + 1
    return out, dups


# ---------------------------------------------------------------- 单个 sheet
@dataclass
class SheetTable:
    sheet: str
    df: pd.DataFrame
    warnings: list
    notes: list


def _clip(s: str, n: int) -> str:
    from app.tools.schema import clip
    return clip(s, n)


def _cols_text(cols) -> str:
    from app.tools.schema import MAX_NAME_CHARS
    return "、".join(f"「{_clip(str(c), MAX_NAME_CHARS)}」" for c in cols)


def _build_sheet(info: SheetInfo, grid: dict, fmts: dict) -> SheetTable | None:
    """grid: {row: {col: value}}（只放非空值）；fmts: {(row, col): number_format}（只放数字格）。"""
    warns, notes = [], []
    rows = sorted(r for r, cells in grid.items() if cells)
    if not rows:
        return None
    merges_at = {}                       # 左上角 → Merge
    for m in info.merges:
        merges_at[(m.min_row, m.min_col)] = m

    def box(rs):
        cs = [c for r in rs for c in grid.get(r, {})]
        return min(cs), max(cs)

    top = rows[0]
    c_lo, _ = box(rows)

    # 1. 横跨全表的合并标题行（可以连着几行，比如标题 + 副标题）
    titles = []
    while len(titles) < MAX_HEADER_ROWS:
        cells = grid.get(top, {})
        rest = [r for r in rows if r > top]
        if len(cells) != 1 or not rest:
            break
        (col, val), = cells.items()
        m = merges_at.get((top, col))
        if m is None or m.max_col == m.min_col:
            break
        rest = [r for r in rows if r > m.max_row]
        if not rest:
            break
        lo, hi = box(rest)
        if not (m.min_col <= lo and m.max_col >= hi):
            break
        titles.append((top, m, val))
        top = rest[0]
    if titles:
        rows = [r for r in rows if r >= top]
        refs = "、".join(f"第 {t[0]} 行" if t[1].max_row == t[0] else f"第 {t[0]}–{t[1].max_row} 行" for t in titles)
        warns.append(f"{refs}是横跨全表的合并标题，已跳过，表头从第 {top} 行开始")
        from app.tools.schema import MAX_CELL_CHARS
        notes.append("表格上方的标题（已跳过，不是数据）：" +
                     " / ".join(f"「{_clip(_text(t[2]), MAX_CELL_CHARS)}」" for t in titles))
    c_lo, c_hi = box(rows)
    if top > 1 and not titles:
        warns.append(f"表头前有空行，已跳过，表头从第 {top} 行开始")
    if c_lo > 1:
        warns.append(f"表格从第 {_col_letters(c_lo)} 列开始，左侧的空列已跳过")
    width = c_hi - c_lo + 1

    # 2. 表头：合并单元格推出表头有几行
    depth = 1
    for m in info.merges:
        if m.min_row == top and m.min_col >= c_lo and m.max_col <= c_hi:
            if m.max_col > m.min_col:
                depth = max(depth, m.max_row - top + 2)
            else:
                depth = max(depth, m.max_row - top + 1)
    horizontal_only = False
    if depth > 1:
        # 横向合并下面要真有一行子表头（文字），否则下一行是数据，表头仍是一行
        sub = top + depth - 1
        hz = [m for m in info.merges if m.min_row == top and m.max_col > m.min_col
              and m.min_col >= c_lo and m.max_col <= c_hi]
        sub_ok = all(isinstance(grid.get(sub, {}).get(c), str)
                     for m in hz for c in range(m.min_col, m.max_col + 1) if m.max_row < sub)
        vert = any(m.min_row == top and m.max_row > top for m in info.merges)
        if not sub_ok and not vert:
            depth, horizontal_only = 1, True
    if depth > MAX_HEADER_ROWS:
        warns.append(f"表头的合并单元格跨了 {depth} 行，超出能自动识别的 {MAX_HEADER_ROWS} 行，"
                     f"只按前 {MAX_HEADER_ROWS} 行合并列名，请核对列名")
        depth = MAX_HEADER_ROWS
    h_end = top + depth - 1

    def header_value(r, c):
        v = grid.get(r, {}).get(c)
        if v is not None:
            return v
        for m in info.merges:       # 合并区域内的非左上角格：取左上角的值
            if m.min_row <= r <= m.max_row and m.min_col <= c <= m.max_col and m.min_row >= top:
                return grid.get(m.min_row, {}).get(m.min_col)
        return None

    if depth > 1:
        raw = []
        for c in range(c_lo, c_hi + 1):
            parts = []
            for r in range(top, h_end + 1):
                v = header_value(r, c)
                if v is None:
                    continue
                t = _text(v)
                if not parts or parts[-1] != t:
                    parts.append(t)
            raw.append(HEADER_JOIN.join(parts) if parts else None)
        warns.append(f"第 {top}–{h_end} 行是带合并单元格的多行表头，已合并成一行列名（上层{HEADER_JOIN}下层）")
        joined = [v for v in raw if v is not None and HEADER_JOIN in v]
        if joined:
            # 列名里的「-」是拼出来的，模型容易拆开写或当成减号；注解只写列名，不含取值
            from app.tools.schema import MAX_NAME_CHARS
            ex = _clip(joined[0], MAX_NAME_CHARS)
            notes.append(f"注意：{_cols_text(joined)}列的列名由多行表头用「{HEADER_JOIN}」连接而成，列名本身含"
                         f"「{HEADER_JOIN}」；取值要把整个列名写进方括号，如 df['{ex}']（多表时 dfs[表名]['{ex}']），不要拆开或写成属性访问。")
    elif horizontal_only:
        raw = [header_value(top, c) for c in range(c_lo, c_hi + 1)]
        warns.append("表头里有横向合并的单元格，合并格的名字已填到它覆盖的每一列（重名的列按 .1、.2 区分）")
    else:
        raw = [grid.get(top, {}).get(c) for c in range(c_lo, c_hi + 1)]
        nonempty = [v for v in raw if not _is_empty(v)]
        if len(nonempty) == 1 and width >= 2 and len(rows) > 1:
            warns.append(f"第 {top} 行只有一个单元格有值，可能是标题行而不是表头（未合并单元格，按原样读入）")
    names, dups = _csv_names(raw)
    for orig, renamed in dups.items():
        if not orig.startswith("Unnamed: "):
            warns.append(f"列名「{orig}」重复，后面的读作 " + "、".join(f"「{x}」" for x in renamed))

    # 3. 数据行
    data_rows = [r for r in rows if r > h_end]
    skipped_blank = sum(1 for r in range(h_end + 1, data_rows[-1] + 1) if r not in grid or not grid[r]) \
        if data_rows else 0
    if skipped_blank:
        warns.append(f"数据中间有 {skipped_blank} 个整行空白，已跳过（与 CSV 的空行处理一致）")
    cols = [[_norm(grid.get(r, {}).get(c)) for r in data_rows] for c in range(c_lo, c_hi + 1)]
    series = {}
    for name, vals in zip(names, cols):
        series[name] = _column(vals)
    df = pd.DataFrame(series, index=pd.RangeIndex(len(data_rows)))

    # 4. 告知项
    data_merges = [m for m in info.merges if m.min_row > h_end and m.min_col <= c_hi and m.max_col >= c_lo]
    if data_merges:
        mcols = sorted({names[c - c_lo] for m in data_merges for c in range(max(m.min_col, c_lo), min(m.max_col, c_hi) + 1)},
                       key=names.index)
        refs = "、".join(m.ref for m in data_merges[:3]) + ("等" if len(data_merges) > 3 else "")
        warns.append(f"数据区有 {len(data_merges)} 处合并单元格（{refs}），按 Excel 的规则只有左上角有值，"
                     f"其余格子读成空值，未自动填充。涉及列：{_cols_text(mcols)}")
        notes.append(f"注意：{_cols_text(mcols)}列在 Excel 里有合并单元格，合并区域除第一格外读成了空值；"
                     "如果合并表示同一个分组，按分组计算前先向下填充（ffill）。")
    empty_cols = [n for n, vals in zip(names, cols) if all(v is None for v in vals)]
    if empty_cols:
        warns.append(f"有 {len(empty_cols)} 列整列为空：{_cols_text(empty_cols)}（与 CSV 一致，保留）")
    pct_cols, serial_cols, textnum_cols, err_cols = [], [], [], []
    for j, (name, c) in enumerate(zip(names, range(c_lo, c_hi + 1))):
        nums = [(r, v) for r, v in zip(data_rows, cols[j]) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums:
            pct = sum(1 for r, _v in nums if "%" in (fmts.get((r, c)) or ""))
            if pct * 2 >= len(nums):
                pct_cols.append(name)
            if (len(nums) == len([v for v in cols[j] if v is not None]) and _DATE_HEADER.search(name)
                    and all(float(v).is_integer() and SERIAL_RANGE[0] <= v <= SERIAL_RANGE[1] for _r, v in nums)):
                serial_cols.append(name)
        strs = [v for v in cols[j] if isinstance(v, str)]
        if strs and len(strs) == len([v for v in cols[j] if v is not None]):
            shaped = [s for s in strs if _TEXT_NUMBER.match(s)]
            if len(shaped) * 10 >= len(strs) * 9 and any(_TEXT_NUMBER_DECORATED.search(s) for s in shaped):
                textnum_cols.append(name)
    data_set = set(data_rows)
    for r, c in info.error_cells:
        if r in data_set and c_lo <= c <= c_hi:
            n = names[c - c_lo]
            if n not in err_cols:
                err_cols.append(n)
    if pct_cols:
        warns.append(f"{_cols_text(pct_cols)}在 Excel 里按百分比显示，读到的是底层小数（显示 12.3% 的读作 0.123）")
        notes.append(f"注意：{_cols_text(pct_cols)}列在 Excel 中按百分比格式显示，这里读到的是对应的小数（未乘以一百）。")
    if serial_cols:
        warns.append(f"{_cols_text(serial_cols)}的值像 Excel 日期序列号（没有设日期格式），未自动转换")
        notes.append(f"注意：{_cols_text(serial_cols)}列的取值像 Excel 的日期序列号（以天计的整数），不是普通数值；"
                     "需要日期时按 Excel 的日期起点换算。")
    if textnum_cols:
        warns.append(f"{_cols_text(textnum_cols)}是文本形式的数字（带千分位、百分号或货币符号），与 CSV 一样未自动转换")
    if err_cols:
        warns.append(f"{_cols_text(err_cols)}含 Excel 错误值（如 #DIV/0!），按文本读入；#N/A 读作空值")
        notes.append(f"注意：{_cols_text(err_cols)}列含 Excel 错误值（以 # 开头的文本），计算前需要先处理。")

    # 合计行 / 尾部备注 / 第二行表头：只提示，不改（与 CSV 一致）
    if data_rows:
        last = data_rows[-1]
        first = next((grid[last][c] for c in sorted(grid[last]) if c_lo <= c <= c_hi), None)
        if last in info.sum_rows or (isinstance(first, str) and _TOTAL_TEXT.match(first)):
            why = "求和公式" if last in info.sum_rows else "文字"
            warns.append(f"最后一行（第 {last} 行）看起来是合计行（{why}），与 CSV 一致保留，聚合前需要排除")
            from app.tools.schema import _summary_note
            if not _summary_note(df):      # 数值列等于上方之和时 describe_df 已有一条同义注解，不重复
                notes.append("注意：表的最后一行看起来是合计行，求和、计数、均值之前先排除它。")
        tail = []
        for r in reversed(data_rows):
            cells = [c for c in grid[r] if c_lo <= c <= c_hi]
            if width >= 3 and cells == [c_lo] and isinstance(grid[r][c_lo], str):
                tail.append(r)
            else:
                break
        if tail and len(tail) < len(data_rows):
            warns.append(f"末尾 {len(tail)} 行只有第一列有文字，可能是备注，与 CSV 一致保留")
        if depth == 1 and len(data_rows) >= 3:
            second = grid.get(data_rows[0], {})
            below = data_rows[1:]
            if second and all(isinstance(v, str) for v in second.values()):
                numeric_below = [c for c in second
                                 if sum(isinstance(grid.get(r, {}).get(c), (int, float)) for r in below) * 2 > len(below)]
                if numeric_below:
                    warns.append(f"第 {data_rows[0]} 行全是文字、下面同列是数字，可能也是表头（两行表头），按原样读入")
    if not data_rows:
        warns.append("只有表头，没有数据行")
    df.attrs[WARNINGS_ATTR] = warns
    if notes:
        df.attrs[NOTES_ATTR] = notes
    return SheetTable(sheet=info.name, df=df, warnings=warns, notes=notes)


def _load_grid(ws) -> tuple[dict, dict]:
    grid: dict = {}
    fmts: dict = {}
    for row in ws.iter_rows():
        for cell in row:
            v = getattr(cell, "value", None)
            if _is_empty(v):
                continue
            r, c = cell.row, cell.column
            grid.setdefault(r, {})[c] = v
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nf = getattr(cell, "number_format", None)
                if nf and nf != "General":
                    fmts[(r, c)] = nf
    return grid, fmts


@dataclass
class ExcelBook:
    tables: list            # [SheetTable]
    skipped: list           # 跳过的 sheet 的说明


def read_xlsx(path) -> ExcelBook:
    """读一个 xlsx：每个要读的 sheet 一张表。任何 sheet 有没缓存值的公式 → 拒绝整本。"""
    selected, infos, skipped = inspect(path)
    bad = [(i, i.uncached) for i in selected if i.uncached]
    if bad:
        total = sum(len(u) for _i, u in bad)
        where = "、".join(f"「{i.name}」{_a1(*u[0])}" for i, u in bad[:3])
        raise FormulaNoCacheError(
            f"有 {total} 个公式单元格没有计算结果（如{where}），文件可能是程序生成、没在 Excel 里打开保存过。"
            "直接读会把它们当成空值、合计算成 0。请用 Excel 或 WPS 打开文件后保存一次，再重新上传")
    if not selected:
        raise NoSheetError(f"工作簿里没有可读的数据表（{len(infos)} 个工作表都是空的或隐藏的）")
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # openpyxl 对不支持的扩展（数据验证等）发 UserWarning，与数据无关
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    tables = []
    try:
        for info in selected:
            grid, fmts = _load_grid(wb[info.name])
            t = _build_sheet(info, grid, fmts)
            if t is None:
                skipped.append(f"工作表「{info.name}」是空的，已跳过")
                continue
            tables.append(t)
    finally:
        wb.close()
    if not tables:
        raise NoSheetError(f"工作簿里没有可读的数据表（{len(infos)} 个工作表都是空的或隐藏的）")
    for t in tables:         # 跳过的 sheet 对每张表都提示一次（单表时用户只看得到这一张）
        t.warnings[:0] = list(skipped)
    return ExcelBook(tables=tables, skipped=skipped)


def selected_sheet_names(path) -> list[str]:
    """要读的 sheet 名（只扫 XML）。字典挂载用它定表名，与 read_xlsx 的选表是同一个判据。"""
    return [i.name for i in inspect(path)[0]]
