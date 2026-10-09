"""用真实评测用例检查比较器的两个方向（B12）：
- 形态不同但内容正确的写法应判对（防"虚低"）；
- 顺序错、标签错、口径错应判错（防"虚高"）。
这里的 variant 代码模拟模型常见的不同写法，在 data/sample_eval.csv 上真实执行。
"""
import os

import pytest

from app.eval.cases import ALL_CASES
from app.eval.comparator import results_equal
from app.tools.csv_io import read_csv
from app.tools.sandbox import run_code
from conftest import ROOT

CASES = {c.id: c for c in ALL_CASES}
DF = read_csv(os.path.join(ROOT, "data", "sample_eval.csv"))

SALES = "s = (df['units'] * df['price']).groupby(df['region']).sum()\n"
MONTHLY = ("df['date'] = pd.to_datetime(df['date'])\n"
           "m = df.assign(sales=df['units'] * df['price']).set_index('date')['sales'].resample('ME').sum()\n")

SHOULD_PASS = [
    ("agg_001", SALES + "result = (s.idxmax(), s.max())"),                                # (标签, 数值)
    ("agg_001", SALES + "result = s.sort_values(ascending=False).head(1)"),               # 1 项 Series
    ("agg_001", SALES + "result = {'region': s.idxmax(), 'sales': s.max()}"),             # 二项 dict
    ("agg_002", "result = df.groupby('product', as_index=False)['price'].mean()"),       # reset_index 形态 + 未 round
    ("agg_005", "result = df.pivot_table(index='region', columns='product', values='units', aggfunc='sum')"),
    ("agg_008", "result = {'最高单价': df['price'].max(), '最低单价': df['price'].min()}"),
    ("agg_008", "result = [df['price'].max(), df['price'].min()]"),
    ("agg_010", "result = (df['units'] * df['price']).sum()"),                             # float vs int()
    ("agg_014", "result = df.groupby('region').size()"),                                    # value_counts 顺序不计分
    ("filt_002", "result = df[df['region'] == '华东'].sort_values('date').reset_index(drop=True)"),  # 多列 + reset
    ("filt_004", "result = df.assign(sales=df['units'] * df['price']).sort_values('sales', ascending=False).head(5)"),
    ("corr_001", "result = df.groupby(['region', 'product'])['units'].sum()"),            # 长表 vs 交叉表
    ("corr_009", "result = df.groupby('region')['price'].mean().sort_values().tail(1)"),
    ("ts_001", "df['date'] = pd.to_datetime(df['date'])\n"
               "result = df.assign(s=df['units'] * df['price']).groupby(df['date'].dt.to_period('M'))['s'].sum()"),
    ("ts_001", "df['date'] = pd.to_datetime(df['date'])\n"
               "result = df.assign(s=df['units'] * df['price']).groupby(df['date'].dt.strftime('%Y-%m'))['s'].sum()"),
    ("ts_007", MONTHLY + "result = (m.idxmax(), m.idxmin())"),                             # Timestamp vs 'YYYY-MM'
    ("ts_007", MONTHLY + "result = (m.idxmax().to_period('M'), m.idxmin().to_period('M'))"),
]

SHOULD_FAIL = [
    ("agg_001", SALES + "result = s.idxmin()"),                                             # 标签错
    ("agg_001", SALES + "result = list(s.index)"),                                          # 列出全部地区不算答对
    ("agg_002", "result = df.groupby('product')['units'].mean()"),                         # 口径错
    ("filt_004", "result = df.assign(sales=df['units'] * df['price']).nsmallest(5, 'sales')"),
    ("filt_007", "d = df.assign(sales=df['units'] * df['price'])\n"
                 "result = d[d['sales'] > 5000].sort_values('sales')[['date', 'region', 'product', 'units', 'price']]"),  # 排序方向错
    ("ts_006", "df['date'] = pd.to_datetime(df['date'])\n"
               "result = df[df['date'].dt.month == 4].assign(sales=df['units'] * df['price'])"
               ".groupby('product')['sales'].sum().sort_values()"),                         # 排名反了
    ("corr_002", "total = (df['units'] * df['price']).sum()\n"
                 "result = (df['units'] * df['price']).groupby(df['region']).sum() / total"),  # 比例 vs 百分比
    ("ts_003", "df['date'] = pd.to_datetime(df['date'])\n"
               "result = int(df[df['date'].dt.month == 1]['units'].sum() - df[df['date'].dt.month == 3]['units'].sum())"),
]


def _exec(code):
    result, _, err = run_code(code, DF.copy(), "/tmp/_cmp_case.png")
    assert err is None, err
    return result


@pytest.mark.parametrize("cid,code", SHOULD_PASS, ids=[f"{c}-{i}" for i, (c, _) in enumerate(SHOULD_PASS)])
def test_equivalent_forms_judged_correct(cid, code):
    case = CASES[cid]
    assert results_equal(_exec(code), _exec(case.ground_truth), ordered=case.ordered)


@pytest.mark.parametrize("cid,code", SHOULD_FAIL, ids=[f"{c}-{i}" for i, (c, _) in enumerate(SHOULD_FAIL)])
def test_wrong_answers_judged_wrong(cid, code):
    case = CASES[cid]
    assert not results_equal(_exec(code), _exec(case.ground_truth), ordered=case.ordered)
