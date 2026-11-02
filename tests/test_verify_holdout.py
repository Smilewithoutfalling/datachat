"""`verify_holdout.load_raw` 的数据源分支测试。

守的是**读取契约**，不是数值 —— 每加一个数据源，最容易错的不是答案算错，而是
"读进来的类型和脏化表那边不一样"，于是同一句 raw_code 在两边算出不同结果，
或者干脆抛异常。第一批的 m06 就栽在这上面（verify 用 dtype=str、agent 走 load_data
推断类型，`可住人数 >= 4` 变成字符串比较，标准答案自洽地错）。

这批新增两个数据源：
- `retail`（UCI 502 Online Retail II）—— 发票号有 'C' 前缀（取消单）、商品编码有 'M'，
  必须按 str 读；让 pandas 推断会得到 object 里混 int，`.str.startswith` 在整数行上给 NaN。
- `food`（USDA FDC SR Legacy）—— 五张表，键用中文表名，列名保留英文原文。

测试用**临时造的最小包**，不依赖题库目录里的 100MB 真数据：这条路径要能在 CI 里跑。
"""
import io
import zipfile

import pandas as pd
import pytest

import scripts.holdout.verify_holdout as V


# ---------------------------------------------------------------- retail

def _write_retail_zip(cache_dir, rows):
    """造一个只有两张 sheet 的最小 xlsx 包。

    第一张（Year 2009-2010）故意放一行噪声，用来证明实现只读第二张。
    """
    df = pd.DataFrame(rows)
    noise = df.iloc[:1].assign(Invoice="NOISE", StockCode="NOISE")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        noise.to_excel(w, sheet_name="Year 2009-2010", index=False)
        df.to_excel(w, sheet_name="Year 2010-2011", index=False)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache_dir / "online_retail_ii.zip", "w") as z:
        z.writestr("online_retail_II.xlsx", buf.getvalue())


def test_load_raw_retail_keeps_invoice_and_stockcode_as_str(tmp_path):
    """数字发票号必须仍是字符串。

    不传 dtype 时 pandas 会把 '536365' 读成 int64，那一行 `.str.startswith('C')`
    给 NaN、`~c` 抛 TypeError —— raw_code 直接跑不了。这条测试就是钉这个。
    """
    rows = {
        "Invoice": ["536365", "C536379"],
        "StockCode": ["85123A", "10002"],
        "Description": ["WHITE HANGING HEART", "RED WOOLLY HOTTIE"],
        "Quantity": [6, -1],
        "InvoiceDate": pd.to_datetime(["2010-12-01 08:26", "2010-12-01 09:41"]),
        "Price": [2.55, 2.55],
        "Customer ID": [17850.0, 14527.0],
        "Country": ["United Kingdom", "United Kingdom"],
    }
    _write_retail_zip(tmp_path / "data" / "_cache", rows)

    out = V.load_raw(str(tmp_path), "retail")

    assert out["Invoice"].tolist() == ["536365", "C536379"]
    assert out["StockCode"].tolist() == ["85123A", "10002"]
    assert out["Invoice"].str.startswith("C").tolist() == [False, True], "取消单要能直接筛出来"
    assert out["Quantity"].tolist() == [6, -1], "数量是真数值，不该被转成字符串"


def test_load_raw_retail_takes_only_the_second_sheet(tmp_path):
    """两张 sheet 在 2010-12-01~12-09 有 22,523 行重叠，拼一起同一笔交易算两遍。

    第一张故意放一行**不同的**数据：如果实现改成"读全部 sheet 再 concat"，这里会变成 2 行。
    """
    # 第一张表放 3 行噪声，第二张表放 1 行；正确实现只返回 1 行。
    df = pd.DataFrame({
        "Invoice": ["A1", "A2", "A3"],
        "StockCode": ["X", "Y", "Z"],
        "Description": ["d", "d", "d"],
        "Quantity": [1, 2, 3],
        "InvoiceDate": pd.to_datetime(["2009-12-01 08:00"] * 3),
        "Price": [1.0, 2.0, 3.0],
        "Customer ID": [1.0, 2.0, 3.0],
        "Country": ["United Kingdom"] * 3,
    })
    cache = tmp_path / "data" / "_cache"
    cache.mkdir(parents=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Year 2009-2010", index=False)
        df.iloc[:1].to_excel(w, sheet_name="Year 2010-2011", index=False)
    with zipfile.ZipFile(cache / "online_retail_ii.zip", "w") as z:
        z.writestr("online_retail_II.xlsx", buf.getvalue())

    out = V.load_raw(str(tmp_path), "retail")

    assert len(out) == 1, f"只该读 Year 2010-2011 那张，实际 {len(out)} 行"
    assert out["Invoice"].tolist() == ["A1"]


def test_load_raw_retail_reports_missing_zip(tmp_path):
    with pytest.raises(SystemExit) as e:
        V.load_raw(str(tmp_path), "retail")
    assert "online_retail_ii.zip" in str(e.value.code)


# ---------------------------------------------------------------- food

FOOD_TABLES = {
    "food": ["fdc_id", "description", "food_category_id"],
    "food_category": ["id", "code", "description"],
    "nutrient": ["id", "name", "unit_name"],
    "food_nutrient": ["id", "fdc_id", "nutrient_id", "amount"],
    "food_portion": ["id", "fdc_id", "seq_num", "amount", "modifier"],
}


def test_load_raw_food_returns_five_tables_under_chinese_keys(tmp_path):
    """键是中文表名（`dfs['食品']`），列名是英文原文 —— 这与脏化表的契约必须一致。"""
    cache = tmp_path / "data" / "_cache"
    cache.mkdir(parents=True)
    with zipfile.ZipFile(cache / "sr_legacy_food_csv_2018-04.zip", "w") as z:
        for name, cols in FOOD_TABLES.items():
            body = ",".join(cols) + "\n" + ",".join("1" for _ in cols) + "\n"
            z.writestr(V.FOOD_PREFIX + name + ".csv", body)

    out = V.load_raw(str(tmp_path), "food")

    assert set(out) == {"食品", "食品类别", "营养素", "营养成分", "份量"}
    assert list(out["食品"].columns) == ["fdc_id", "description", "food_category_id"]
    assert len(out["营养成分"]) == 1


def test_load_raw_food_reports_missing_zip(tmp_path):
    with pytest.raises(SystemExit) as e:
        V.load_raw(str(tmp_path), "food")
    assert "sr_legacy_food_csv_2018-04.zip" in str(e.value.code)


# ---------------------------------------------------------------- 兜底

def test_load_raw_still_rejects_unknown_dataset(tmp_path):
    """加分支不能把兜底吃掉 —— 拼错数据集名要当场退出，不是返回 None 让下游 500 行后炸。"""
    with pytest.raises(SystemExit) as e:
        V.load_raw(str(tmp_path), "no_such_set")
    assert "不认识的 dataset" in str(e.value.code)
    assert "no_such_set" in str(e.value.code)
