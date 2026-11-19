"""阶段 7.5 第 2 步：Excel（xlsx）输入的验收矩阵（docs/roadmap/phase75-assess.md §2.1）。

fixture 全部用 openpyxl 在 tmp_path 里现场生成，仓库里不放二进制文件。

两部分：
1. perturb.py 的 9 个变体各出一份 xlsx（同一份单元格内容，像用户在 Excel 里录入：数字形态的写成数字，
   其余写成文本），断言读出来的 DataFrame 与 CSV 版**完全相等**（列名、dtype、取值）——CSV 已有的处理口径
   在 xlsx 上保持一致；另外断言每个变体给出的读取提示。
2. xlsx 独有项：真合并单元格、表头不在首行、公式无缓存值、日期序列号、空 sheet、隐藏 sheet、多 sheet 选表，
   以及体积上限、字典挂载、上传接口。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sys
import zipfile

import openpyxl
import pandas as pd
import pytest

from app.tools import excel_io
from app.tools.dataset import (DuplicateTableError, TableReadError, access_rule, describe_data, load_data,
                               load_warnings)
from app.tools.excel_io import (FormulaNoCacheError, NoSheetError, XlsxInvalidError, XlsxTooLargeError,
                                check_size, read_xlsx)
from app.tools.schema import MODEL_NOTES_ATTR, describe_df

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import perturb  # noqa: E402

ORDERS = os.path.join(REPO, "data", "eval", "orders.csv")


# ---------------------------------------------------------------- 工具
def _cell(text):
    """CSV 文本 → 用户在 Excel 里录入后的单元格：纯数字形态的存成数字（Excel 录入「0.10」存的就是 0.1），其余存文本。"""
    if text == "":
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _xlsx_rows(table):
    """含千分位 / 百分号文本的列整列存文本：模拟业务系统把格式化后的文本写进 xlsx（这正是该变体要测的形态；
    若在 Excel 里手敲「1,234」，Excel 会存成带格式的数字，那一种见 test_number_formats_and_text_numbers）。"""
    width = max(len(r) for r in table)
    text_cols = {j for r in table[1:] for j, v in enumerate(r) if re.fullmatch(r"-?[\d,]+(\.\d+)?%?", v or "")
                 and ("," in v or "%" in v)}
    return [[(v or None) if j in text_cols else _cell(v) for j, v in enumerate(r)] + [None] * (width - len(r))
            for r in table]


def write_xlsx(path, sheets, *, raw=False):
    """sheets: {sheet名: 行列表}；raw=False 时每格按 _cell 转换。返回 workbook（方便再加格式后自己 save）。"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append([v if raw else _cell(v) for v in r])
    wb.save(path)
    return wb


def patch_sheet_xml(path, part, fn):
    """改 zip 里某个 sheet 的 XML（openpyxl 写不出公式缓存值，用它模拟 Excel 保存过的文件）。"""
    tmp = str(path) + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == part:
                data = fn(data.decode()).encode()
            zout.writestr(item, data)
    os.replace(tmp, path)


def assert_same_as_csv(df_x, df_csv):
    """列名、取值、dtype 全等。唯一放宽：数值列的 int64 / float64 —— Excel 里数字不分整数和浮点
    （录入 2463.0 存的就是 2463），CSV 文本「2463.0」会让 read_csv 判成 float，这不是读取差异而是 Excel 本身没这个信息。"""
    pd.testing.assert_frame_equal(df_x, df_csv, check_dtype=False)
    for c in df_csv.columns:
        a, b = df_x[c].dtype, df_csv[c].dtype
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            continue
        assert a == b, (c, a, b)


def orders_table():
    """与 perturb.main 相同的取数方式：load_data 读原表，再逐格转回文本。"""
    data, _ = load_data(ORDERS)
    header = [str(c) for c in data.columns]
    rows = [[("" if v is None or (isinstance(v, float) and v != v) else (
        f"{v:g}" if isinstance(v, float) else str(v))) for v in rec]
            for rec in data.itertuples(index=False, name=None)]
    return header, rows


# ---------------------------------------------------------------- 1. perturb 9 变体：xlsx == CSV
# 每个变体的期望读取提示：(必须出现的片段, ...)；空元组 = 不应有任何提示
PERTURB_EXPECT = {
    "merged_header": ("可能是标题行",),        # 未合并的标题行：与 CSV 一致按原样读，只提示
    "two_row_header": ("可能也是表头",),       # 未合并的两行表头：同上
    "total_row": ("合计行",),                  # 合计行：与 CSV 一致保留，提示
    "thousand_sep": ("文本形式的数字",),        # 文本千分位：与 CSV 一致不转换，提示
    "percent_str": ("文本形式的数字",),         # 文本百分号：同上
    "date_compact": (),                        # 紧凑日期整数：与 CSV 一致，无提示
    "dup_columns": ("列名「order_date」重复",),  # 重名：与 CSV 一致加 .1，提示
    "empty_col": ("整列为空",),                 # 空列：与 CSV 一致 Unnamed，提示
    "footer_note": ("备注",),                   # 尾部备注：与 CSV 一致保留，提示
}


def test_perturb_expectations_cover_all_kinds():
    assert set(PERTURB_EXPECT) == set(perturb.KINDS) and len(perturb.KINDS) == 9


@pytest.mark.parametrize("kind", perturb.KINDS)
def test_perturb_variant_xlsx_matches_csv(tmp_path, kind):
    header, rows = orders_table()
    table = perturb.TRANSFORM[kind](header, rows)
    csv_path, xlsx_path = tmp_path / f"o.{kind}.csv", tmp_path / f"o.{kind}.xlsx"
    perturb._write_csv(csv_path, table, quote_all=kind in perturb.QUOTE_ALWAYS)
    write_xlsx(xlsx_path, {"Sheet1": _xlsx_rows(table)}, raw=True)
    df_csv, _ = load_data(str(csv_path))
    df_x, desc = load_data(str(xlsx_path))
    assert_same_as_csv(df_x, df_csv)
    assert desc.startswith(f"{len(df_csv)} 行 × {len(df_csv.columns)} 列，xlsx 工作表「Sheet1」")
    w = load_warnings(df_x)
    if not PERTURB_EXPECT[kind]:
        assert w == []
    for frag in PERTURB_EXPECT[kind]:
        assert any(frag in x for x in w), (kind, w)
    assert load_warnings(df_csv) == []          # CSV 路径没有提示，attrs 为空
    assert df_csv.attrs == {}


# ---------------------------------------------------------------- 2. xlsx 独有项
def _report_book(path):
    """真合并单元格的典型报表：合并标题 + 空行 + 两行表头（纵向 / 横向合并）+ 数据区纵向合并 + 百分比格式。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "销售"
    ws.append(["2024年销售明细（单位：元）"])
    ws.merge_cells("A1:D1")
    ws.append([])
    ws.append(["日期", "地区", "金额", None])
    ws.append([None, None, "线上", "线下占比"])
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:B4")
    ws.merge_cells("C3:D3")
    ws.append([dt.date(2024, 1, 5), "华东", 100, 0.5])
    ws.append([dt.date(2024, 1, 6), None, 200, 0.25])
    ws.append([dt.date(2024, 1, 7), "华北", 300, 0.125])
    ws.merge_cells("B5:B6")
    for r in (5, 6, 7):
        ws.cell(r, 4).number_format = "0.0%"
    wb.save(path)


def test_real_merged_title_and_header(tmp_path):
    p = tmp_path / "report.xlsx"
    _report_book(p)
    df, _ = load_data(str(p))
    # 标题行跳过；A3:A4 / B3:B4 纵向合并 → 单名；C3:D3 横向合并 → 上层-下层
    assert list(df.columns) == ["日期", "地区", "金额-线上", "金额-线下占比"]
    assert df["日期"].tolist() == ["2024-01-05", "2024-01-06", "2024-01-07"]   # 日期格式 → ISO 文本，同 CSV
    assert df["金额-线上"].dtype == "int64" and df["金额-线上"].sum() == 600
    w = load_warnings(df)
    assert any("合并标题，已跳过" in x for x in w)
    assert any("多行表头" in x for x in w)
    # 数据区合并：不填充（与 read_excel 一致），明确提示
    assert pd.isna(df.loc[1, "地区"])
    assert any("数据区有 1 处合并单元格（B5:B6）" in x and "「地区」" in x for x in w)
    assert any("百分比" in x and "「金额-线下占比」" in x for x in w)
    notes = df.attrs[MODEL_NOTES_ATTR]
    assert any("2024年销售明细（单位：元）" in n for n in notes)       # 单位在标题里，给模型
    assert any("「地区」列在 Excel 里有合并单元格" in n and "ffill" in n for n in notes)
    assert any("百分比格式" in n for n in notes)


def test_model_notes_reach_prompt_without_cell_values(tmp_path):
    p = tmp_path / "report.xlsx"
    _report_book(p)
    df, _ = load_data(str(p))
    text = describe_data(df)
    for n in df.attrs[MODEL_NOTES_ATTR]:
        assert n in text
    # 结构注解只引用列名：注解里不出现数据区取值（出境审计口径）
    joined = "".join(n for n in df.attrs[MODEL_NOTES_ATTR] if not n.startswith("表格上方的标题"))
    for v in ("华东", "华北", "2024-01-05"):
        assert v not in joined
    # CSV 的 describe_df 不受影响：没有 attrs 时与改动前逐字一致（逐字比对由 test_schema / 指纹测试钉住）
    plain = df.copy()
    plain.attrs = {}
    assert all(n not in describe_df(plain) for n in df.attrs[MODEL_NOTES_ATTR])


def test_header_not_in_first_row(tmp_path):
    """表头前有空行、左侧有空列：跳过（read_csv 同样跳过空行），提示表头起点。"""
    p = tmp_path / "offset.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["C4"], ws["D4"] = "城市", "销量"
    ws["C5"], ws["D5"] = "北京", 3
    ws["C6"], ws["D6"] = "上海", 4
    wb.save(p)
    df, _ = load_data(str(p))
    assert list(df.columns) == ["城市", "销量"] and df["销量"].tolist() == [3, 4]
    w = load_warnings(df)
    assert any("表头前有空行" in x and "第 4 行" in x for x in w)
    assert any("第 C 列开始" in x for x in w)


def test_unmerged_title_row_kept_like_csv(tmp_path):
    """标题行没合并：判不准，按 CSV 口径原样读（列名是标题 + Unnamed），只提示。"""
    rows = [["销售报表"], ["城市", "销量"], ["北京", "3"]]
    p = tmp_path / "t.xlsx"
    write_xlsx(p, {"S": rows})
    df, _ = load_data(str(p))
    assert list(df.columns) == ["销售报表", "Unnamed: 1"]
    assert any("可能是标题行" in x for x in load_warnings(df))


def test_header_horizontal_merge_over_data(tmp_path):
    """表头里横向合并、下一行就是数据：表头仍是一行，合并格的名字填到覆盖的每列，重名按 .1。"""
    p = tmp_path / "h.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["城市", "联系电话", None])
    ws.merge_cells("B1:C1")
    ws.append(["北京", 1, 2])
    ws.append(["上海", 3, 4])
    wb.save(p)
    df, _ = load_data(str(p))
    assert list(df.columns) == ["城市", "联系电话", "联系电话.1"]
    assert len(df) == 2
    assert any("横向合并" in x for x in load_warnings(df))


def test_formula_without_cached_value_is_rejected(tmp_path):
    """公式没有缓存值（程序生成、没在 Excel 里保存过）：拒绝，提示打开保存一次——不能读成空值求和成 0。"""
    p = tmp_path / "f.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["城市", "数量", "金额"])
    ws.append(["北京", 2, "=B2*10"])
    ws.append(["上海", 3, "=B3*10"])
    wb.save(p)
    # 前提：openpyxl 的 data_only 读法确实会把这两格读成 None（不报错）——这正是要防的静默错误
    raw = openpyxl.load_workbook(p, data_only=True).active
    assert raw["C2"].value is None and raw["C3"].value is None
    with pytest.raises(FormulaNoCacheError) as e:
        load_data(str(p))
    assert "2 个公式单元格没有计算结果" in str(e.value) and "C2" in str(e.value)
    assert "保存一次" in str(e.value)
    # 多表数据集里同样拒绝，并定位到文件
    d = tmp_path / "dir"
    d.mkdir()
    shutil.copy(p, d / "f.xlsx")
    with pytest.raises(TableReadError) as e2:
        load_data(str(d))
    assert e2.value.filename == "f.xlsx"
    from app.core.errors import dataset_message
    assert dataset_message(e2.value).startswith("表 f.xlsx：有 2 个公式单元格没有计算结果")


def test_formula_with_cached_value_reads_cache(tmp_path):
    """Excel 保存过的公式带缓存值：照常读缓存值；字符串结果为空串（t="str" + 空 <v>）不算缺缓存。"""
    p = tmp_path / "f.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["城市", "数量", "金额", "备注"])
    ws.append(["北京", 2, "=B2*10", '=IF(B2>5,"多","")'])
    ws.append(["上海", 3, "=B3*10", '=IF(B3>5,"多","")'])
    wb.save(p)

    def add_cache(xml):
        xml = xml.replace("<f>B2*10</f><v />", "<f>B2*10</f><v>20</v>").replace("<f>B3*10</f><v />", "<f>B3*10</f><v>30</v>")
        return re.sub(r'<c r="(D\d)"><f>([^<]*)</f><v ?/>', r'<c r="\1" t="str"><f>\2</f><v></v>', xml)
    patch_sheet_xml(p, "xl/worksheets/sheet1.xml", add_cache)
    df, _ = load_data(str(p))
    assert df["金额"].tolist() == [20, 30] and df["金额"].sum() == 50
    assert df["备注"].isna().all()


def test_total_row_from_sum_formula(tmp_path):
    """末行是 SUM 公式算出的合计：保留（与 CSV 一致），提示；describe_df 已有同义注解时不重复。"""
    p = tmp_path / "t.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["城市", "销量"])
    ws.append(["北京", 2])
    ws.append(["上海", 3])
    ws.append([None, "=SUM(B2:B3)"])
    wb.save(p)
    patch_sheet_xml(p, "xl/worksheets/sheet1.xml",
                    lambda x: x.replace("<f>SUM(B2:B3)</f><v />", "<f>SUM(B2:B3)</f><v>5</v>"))
    df, _ = load_data(str(p))
    assert len(df) == 3
    assert any("合计行（求和公式）" in x for x in load_warnings(df))
    text = describe_df(df)
    assert text.count("合计") + text.count("各行之和") >= 1


def test_date_serials(tmp_path):
    """日期格式的格 → ISO 文本（带时间的保留时间）；没设日期格式的序列号整数 → 不转换，提示。"""
    p = tmp_path / "d.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["下单日期", "到货时间", "入库日期", "数量"])
    ws.append([dt.date(2024, 1, 5), dt.datetime(2024, 1, 6, 8, 30), 45296, 45296])
    ws.append([dt.date(2024, 2, 1), dt.datetime(2024, 2, 2, 0, 0), 45323, 45323])
    wb.save(p)
    df, _ = load_data(str(p))
    assert df["下单日期"].tolist() == ["2024-01-05", "2024-02-01"]
    assert df["到货时间"].tolist() == ["2024-01-06 08:30:00", "2024-02-02"]
    assert df["入库日期"].tolist() == [45296, 45323]          # 判不准，不转换
    w = load_warnings(df)
    assert any("日期序列号" in x and "「入库日期」" in x for x in w)
    assert not any("「数量」" in x for x in w)               # 列名不像日期的不提示
    assert any("日期序列号" in n for n in df.attrs[MODEL_NOTES_ATTR])


def test_number_formats_and_text_numbers(tmp_path):
    """千分位 / 货币格式的数字读底层数值，不提示；文本形式的「¥1,234」与 CSV 一致不转换，提示；
    文本形式的「00123」保持文本（有意偏离 CSV：CSV 会读成整数丢前导零）。"""
    p = tmp_path / "n.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["编号", "金额", "单价", "报价"])
    ws.append(["00123", 1234567, 12.5, "¥1,234.00"])
    ws.append(["00456", 2345678, 99.9, "¥2,000.00"])
    for r in (2, 3):
        ws.cell(r, 2).number_format = "#,##0"
        ws.cell(r, 3).number_format = '"¥"#,##0.00'
    wb.save(p)
    df, _ = load_data(str(p))
    assert df["编号"].tolist() == ["00123", "00456"]
    assert df["金额"].tolist() == [1234567, 2345678] and df["金额"].dtype == "int64"
    assert df["单价"].tolist() == [12.5, 99.9]
    assert df["报价"].tolist() == ["¥1,234.00", "¥2,000.00"]
    w = load_warnings(df)
    assert any("文本形式的数字" in x and "「报价」" in x for x in w)
    assert not any("「金额」" in x or "「单价」" in x for x in w)


def test_error_values(tmp_path):
    """Excel 错误值：#N/A 按 read_csv 的 na_values 是空值；其余（#DIV/0!）按文本读入，提示。"""
    p = tmp_path / "e.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["城市", "比率", "查找"])
    ws.append(["北京", 0.5, "#N/A"])
    ws.append(["上海", "#DIV/0!", "x"])
    wb.save(p)
    df, _ = load_data(str(p))
    assert df["比率"].tolist() == ["0.5", "#DIV/0!"]          # 混合列整列文本，同 CSV
    assert pd.isna(df.loc[0, "查找"])
    assert any("错误值" in x and "「比率」" in x for x in load_warnings(df))


def test_empty_and_hidden_sheets(tmp_path, monkeypatch):
    """空 sheet、隐藏 sheet 跳过并提示；剩一张时表名 = 文件名（单表，变量 df）；全部不可读 → 拒绝。"""
    p = tmp_path / "book.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "数据"
    ws.append(["a", "b"])
    ws.append([1, 2])
    wb.create_sheet("Sheet2")                       # 默认新建工作簿常见的空 sheet
    h = wb.create_sheet("辅助")
    h.append(["k", "v"])
    h.append([1, 1])
    h.sheet_state = "hidden"
    wb.save(p)
    df, desc = load_data(str(p))
    assert isinstance(df, pd.DataFrame) and list(df.columns) == ["a", "b"]
    assert "xlsx 工作表「数据」" in desc
    w = load_warnings(df)
    assert "工作表「Sheet2」是空的，已跳过" in w and "工作表「辅助」是隐藏的，已跳过" in w

    monkeypatch.setattr(excel_io, "INCLUDE_HIDDEN_SHEETS", True)
    data, _ = load_data(str(p))
    assert set(data) == {"book.数据", "book.辅助"}
    monkeypatch.setattr(excel_io, "INCLUDE_HIDDEN_SHEETS", False)

    empty = tmp_path / "empty.xlsx"
    wb2 = openpyxl.Workbook()
    wb2.create_sheet("x")
    wb2.save(empty)
    with pytest.raises(NoSheetError) as e:
        load_data(str(empty))
    assert "没有可读的数据表" in str(e.value)


def test_multi_sheet_tables(tmp_path):
    """多 sheet：每个 sheet 一张表，表名 = 文件名.sheet名，代码里用 dfs；sheet 顺序即工作簿顺序。"""
    p = tmp_path / "shop.xlsx"
    write_xlsx(p, {"订单": [["oid", "uid"], ["1", "u1"], ["2", "u2"]], "用户": [["uid", "city"], ["u1", "北京"]]})
    data, desc = load_data(str(p))
    assert list(data) == ["shop.订单", "shop.用户"]
    assert data["shop.订单"]["oid"].tolist() == [1, 2]
    assert desc.startswith("2 张表：shop.订单 2×2（xlsx），shop.用户 1×2（xlsx）")
    assert "dfs['shop.订单']" in access_rule(data)
    # 目录里 xlsx 与 CSV 混放：xlsx 展开成多表，CSV 照旧
    d = tmp_path / "dir"
    d.mkdir()
    shutil.copy(p, d / "shop.xlsx")
    (d / "extra.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    data, desc = load_data(str(d))
    assert list(data) == ["extra", "shop.订单", "shop.用户"]
    # 展开后的表名与 CSV 撞名 → 拒绝
    (d / "shop.订单.csv").write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(DuplicateTableError):
        load_data(str(d))


def test_dictionary_mounting(tmp_path):
    """字典：先找 foo.<sheet>.dict.csv，找不到退回 foo.dict.csv（对全部 sheet 生效）；单表时无前缀、不分组。"""
    from app.tools.dictionary import load_retriever
    p = tmp_path / "shop.xlsx"
    write_xlsx(p, {"订单": [["oid", "amt"], ["1", "2"]], "用户": [["uid", "city"], ["u1", "北京"]]})
    (tmp_path / "shop.订单.dict.csv").write_text("field,description\namt,订单实付金额\n", encoding="utf-8")
    (tmp_path / "shop.dict.csv").write_text("field,description\ncity,用户所在城市\n", encoding="utf-8")
    r = load_retriever(str(p))
    fields = {f for f, _d in r.entries}
    assert fields == {"shop.订单.amt", "shop.用户.city"}          # 订单用专属字典，用户退回通用字典
    one = tmp_path / "one.xlsx"
    write_xlsx(one, {"S": [["amt"], ["1"]]})
    (tmp_path / "one.dict.csv").write_text("field,description\namt,金额\n", encoding="utf-8")
    r1 = load_retriever(str(one))
    assert [f for f, _d in r1.entries] == ["amt"] and r1._groups is None
    (tmp_path / "one.S.dict.csv").write_text("field,description\namt,专属说明\n", encoding="utf-8")
    assert load_retriever(str(one)).entries == [("amt", "专属说明")]


def test_dictionary_dotted_sheet_and_file_names(tmp_path):
    """字典路径是按「文件名去扩展名 + . + sheet 名 + .dict.csv」拼出来的，不从文件名反解析，
    所以 sheet 名带点（2024.Q1）、文件名带点（fy.2024.report）都不会错配：
    2024.Q1 的专属字典不会被名为 2024 的 sheet 拿走，其余 sheet 退回通用字典。"""
    from app.tools.dictionary import excel_dict_paths, load_retriever
    d = tmp_path / "ds"
    d.mkdir()
    p = d / "fy.2024.report.xlsx"
    write_xlsx(p, {"2024.Q1": [["amt"], ["1"]], "2024": [["amt"], ["2"]], "汇总": [["city"], ["北京"]]})
    assert excel_dict_paths(str(p), "2024.Q1") == [str(d / "fy.2024.report.2024.Q1.dict.csv"),
                                                   str(d / "fy.2024.report.dict.csv")]
    (d / "fy.2024.report.2024.Q1.dict.csv").write_text("field,description\namt,一季度实付\n", encoding="utf-8")
    (d / "fy.2024.report.dict.csv").write_text("field,description\ncity,城市\n", encoding="utf-8")
    data, _ = load_data(str(p))
    assert list(data) == ["fy.2024.report.2024.Q1", "fy.2024.report.2024", "fy.2024.report.汇总"]
    want = {"fy.2024.report.2024.Q1.amt": "一季度实付",
            "fy.2024.report.2024.city": "城市", "fy.2024.report.汇总.city": "城市"}
    for src in (str(p), str(d)):                      # 单文件、目录两种挂法结果一样
        r = load_retriever(src)
        assert dict(r.entries) == want
    data_dir, _ = load_data(str(d))                   # 目录里的 .dict.csv 不会被当成表
    assert list(data_dir) == list(data)
    # 单 sheet + 两边都带点：无前缀，专属字典优先
    one = tmp_path / "a.b.xlsx"
    write_xlsx(one, {"x.y": [["amt"], ["1"]]})
    (tmp_path / "a.b.dict.csv").write_text("field,description\namt,通用\n", encoding="utf-8")
    assert load_retriever(str(one)).entries == [("amt", "通用")]
    (tmp_path / "a.b.x.y.dict.csv").write_text("field,description\namt,专属\n", encoding="utf-8")
    assert load_retriever(str(one)).entries == [("amt", "专属")]


def test_multirow_header_note_tells_bracket_access(tmp_path):
    """多行表头用「-」连接成列名时，模型注解提醒列名含「-」、要用 df['上层-下层'] 整体取值；单行表头不加。"""
    p = tmp_path / "report.xlsx"
    _report_book(p)
    df, _ = load_data(str(p))
    notes = [n for n in df.attrs[MODEL_NOTES_ATTR] if "多行表头" in n]
    assert len(notes) == 1
    n = notes[0]
    assert "「金额-线上」" in n and "「金额-线下占比」" in n and "df['金额-线上']" in n
    assert "「日期」" not in n and "「地区」" not in n          # 没被连接的列不点名
    assert n in describe_data(df)                               # 注解进 prompt
    for v in ("华东", "华北", "100"):                           # 只有列名，没有取值
        assert v not in n
    q = tmp_path / "plain.xlsx"
    write_xlsx(q, {"S": [["a-b", "c"], ["1", "2"]]})
    plain, _ = load_data(str(q))
    assert not any("多行表头" in x for x in plain.attrs.get(MODEL_NOTES_ATTR, []))


def test_xlsx_text_cell_keeps_leading_zeros(tmp_path):
    """文本格里的 00123 读出来仍是文本 "00123"，前导零不丢。

    工号、账号、机构码、邮编这类字段都依赖这一点：用户在 Excel 里特意存成文本，就是为了保住前导零。
    这是 xlsx 唯一一处有意和 CSV 不一致的地方（CSV 会读成整数 123）。不要为了「和 CSV 对齐」或
    「数字列推断更聪明」把它优化掉——读成整数会静默改坏标识符，后面的关联、筛选全错，而且没有报错。
    """
    p = tmp_path / "staff.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["工号", "机构码", "金额"])
    ws.append(["00123", "0010", 5])
    ws.append(["04567", "0200", 6])
    for r in (2, 3):
        for c in (1, 2):
            ws.cell(r, c).number_format = "@"          # 文本格式，与 Excel 里「设置为文本」一致
    wb.save(p)
    df, _ = load_data(str(p))
    assert df["工号"].tolist() == ["00123", "04567"]
    assert df["机构码"].tolist() == ["0010", "0200"]
    for c in ("工号", "机构码"):                          # 是文本列，不是数值列（pandas 3 下 dtype 为 str）
        assert not pd.api.types.is_numeric_dtype(df[c]) and all(isinstance(v, str) for v in df[c])
    assert df["金额"].tolist() == [5, 6]                 # 真数字照常是数值


def test_size_limit_uses_uncompressed_size(tmp_path, monkeypatch):
    """体积按解压后（zip 各成员 file_size 之和）判，超限拒绝；坏 zip 明确报错。"""
    p = tmp_path / "big.xlsx"
    write_xlsx(p, {"S": [["a"], *[[str(i)] for i in range(2000)]]})
    unz = excel_io.uncompressed_size(p)
    assert unz > os.path.getsize(p)                   # 解压后确实比文件大，按压缩体积判会放过
    assert check_size(p) == unz
    with pytest.raises(XlsxTooLargeError):
        check_size(p, limit=unz - 1)
    monkeypatch.setattr(excel_io, "MAX_XLSX_UNCOMPRESSED_BYTES", unz - 1)
    with pytest.raises(XlsxTooLargeError) as e:
        load_data(str(p))
    assert "解压后" in str(e.value)
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(XlsxInvalidError):
        load_data(str(bad))


def test_default_limit_is_300mb():
    """默认上限解压后 300 MB（S 2026-11-19 定：1 GB 解压后约千万级单元格，sidecar 内存到 GB 级）。"""
    assert excel_io.MAX_XLSX_UNCOMPRESSED_BYTES == 300 * 1024 ** 2 or os.getenv("DATACHAT_MAX_XLSX_BYTES")


def test_two_blank_rows_inside_data_skipped(tmp_path):
    """数据中间的整行空白：跳过（read_csv / read_excel 同样跳过空行），提示。"""
    rows = [["a", "b"], ["1", "2"], [], ["3", "4"]]
    p = tmp_path / "b.xlsx"
    write_xlsx(p, {"S": rows})
    df, _ = load_data(str(p))
    assert df["a"].tolist() == [1, 3]
    assert any("整行空白" in x for x in load_warnings(df))


# ---------------------------------------------------------------- 3. 上传接口
def _client(tmp_path):
    from fastapi.testclient import TestClient
    from app.server.app import create_app
    return TestClient(create_app(str(tmp_path / "home"), "t0ken")), {"Authorization": "Bearer t0ken"}


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_upload_xlsx_preview_and_warnings(tmp_path):
    c, H = _client(tmp_path)
    p = tmp_path / "report.xlsx"
    _report_book(p)
    r = c.post("/datasets", files=[("files", ("report.xlsx", open(p, "rb"), XLSX_MIME))], headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tables"] == {"df": ["日期", "地区", "金额-线上", "金额-线下占比"]}
    assert d["summary"] == "3 行 × 4 列，编码 xlsx"
    t = d["preview"]["tables"][0]
    assert t["encoding"] == "xlsx" and t["rows"][0][0] == "2024-01-05"
    assert any("合并单元格" in x for x in t["warnings"]) and any("report.xlsx：" in x for x in d["warnings"])
    assert "error" not in d


def test_upload_multi_sheet_xlsx(tmp_path):
    c, H = _client(tmp_path)
    p = tmp_path / "shop.xlsx"
    write_xlsx(p, {"订单": [["oid"], ["1"]], "用户": [["uid"], ["u1"]]})
    r = c.post("/datasets", files=[("files", ("shop.xlsx", open(p, "rb"), XLSX_MIME))], headers=H)
    d = r.json()
    assert set(d["tables"]) == {"shop.订单", "shop.用户"}
    assert d["summary"].startswith("2 张表：")
    assert "warnings" not in d


def test_upload_formula_without_cache_shows_error(tmp_path):
    """上传本身成功（文件落盘），详情里明确报错——与 CSV 读坏时的行为一致。"""
    c, H = _client(tmp_path)
    p = tmp_path / "f.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.active.append([1, "=A2*2"])
    wb.save(p)
    d = c.post("/datasets", files=[("files", ("f.xlsx", open(p, "rb"), XLSX_MIME))], headers=H).json()
    assert "公式单元格没有计算结果" in d["error"] and "保存一次" in d["error"]


def test_upload_rejects_xls_bad_zip_and_oversize(tmp_path, monkeypatch):
    c, H = _client(tmp_path)
    r = c.post("/datasets", files=[("files", ("old.xls", b"x", "application/vnd.ms-excel"))], headers=H)
    assert r.status_code == 400 and ".xls" in r.json()["detail"] and "另存为 .xlsx" in r.json()["detail"]
    r = c.post("/datasets", files=[("files", ("a.txt", b"x", "text/plain"))], headers=H)
    assert r.status_code == 400 and "只支持 CSV 或 xlsx" in r.json()["detail"]
    r = c.post("/datasets", files=[("files", ("bad.xlsx", b"not a zip", XLSX_MIME))], headers=H)
    assert r.status_code == 400 and "不是有效的 xlsx" in r.json()["detail"]
    p = tmp_path / "big.xlsx"
    write_xlsx(p, {"S": [["a"], *[[str(i)] for i in range(500)]]})
    monkeypatch.setattr(excel_io, "MAX_XLSX_UNCOMPRESSED_BYTES", excel_io.uncompressed_size(p) - 1)
    r = c.post("/datasets", files=[("files", ("big.xlsx", open(p, "rb"), XLSX_MIME))], headers=H)
    assert r.status_code == 413 and "解压后" in r.json()["detail"]
    assert c.get("/datasets", headers=H).json() == []           # 被拒的都没留下数据集
    assert os.listdir(tmp_path / "home" / "datasets") == []


def test_csv_upload_response_has_no_new_keys(tmp_path):
    """CSV 数据集的详情响应不多 warnings 键（前端与已有测试看到的形状不变）。"""
    c, H = _client(tmp_path)
    d = c.post("/datasets", files=[("files", ("s.csv", b"a,b\n1,2\n", "text/csv"))], headers=H).json()
    assert "warnings" not in d and "warnings" not in d["preview"]["tables"][0]


# ---------------------------------------------------------------- 4. 分析链路（假模型）
def test_analyze_xlsx_single_and_multi(tmp_path):
    from app.core import LLMConfig, analyze
    from tests.test_core_analyze import wf_model
    fast = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
    p = tmp_path / "report.xlsx"
    _report_book(p)
    res = analyze(str(p), "线上金额合计", chat_model=wf_model(["result = int(df['金额-线上'].sum())"]), llm_config=fast)
    assert res.ok and res.result == 600
    q = tmp_path / "shop.xlsx"
    write_xlsx(q, {"订单": [["oid", "amt"], ["1", "2"], ["2", "3"]], "用户": [["uid"], ["u1"]]})
    res = analyze(str(q), "金额合计", chat_model=wf_model(["result = int(dfs['shop.订单']['amt'].sum())"]),
                  llm_config=fast)
    assert res.ok and res.result == 5
    bad = tmp_path / "f.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.active.append([1, "=A2*2"])
    wb.save(bad)
    res = analyze(str(bad), "b 的合计", chat_model=wf_model(["result = df['b'].sum()"]), llm_config=fast)
    assert not res.ok and res.error_kind == "dataset" and "保存一次" in res.error
