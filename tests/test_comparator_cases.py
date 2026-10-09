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
    # ---- 阶段 1.5（B24）：阶段 1 真实评测里被误判的写法，按模型实际输出复刻 ----
    ("ts_001", MONTHLY + "result = pd.DataFrame({'年月': m.index.strftime('%Y-%m'), '销售额': m.values})"),  # 中文列名
    ("ts_004", "df['date'] = pd.to_datetime(df['date'])\n"
               "u = df[df['product'] == 'A'].set_index('date')['units'].resample('ME').sum()\n"
               "result = pd.DataFrame({'month': u.index.strftime('%Y-%m'), 'units': u.values, 'diff': u.diff().values})"),
    ("ts_005", "df['date'] = pd.to_datetime(df['date'])\n"
               "c = df.groupby(df['date'].dt.strftime('%Y-%m')).size()\n"
               "result = pd.DataFrame({'月份': c.index, '订单数量': c.values})"),
    ("ts_006", "df['date'] = pd.to_datetime(df['date'])\n"
               "s = df[df['date'].dt.month == 4].assign(sales=df['units'] * df['price']).groupby('product')['sales'].sum()"
               ".sort_values(ascending=False)\n"
               "result = pd.DataFrame({'产品': s.index, '销售额': s.values, '排名': range(1, len(s) + 1)})"),
    ("ts_011", "df['date'] = pd.to_datetime(df['date'])\n"
               "g = df.groupby(df['date'].dt.strftime('%Y-%m'))\n"
               "result = pd.DataFrame({'month': list(g.groups), 'avg_price_weighted': (g.apply(lambda x: (x.units*x.price).sum()/x.units.sum())).values,"
               " 'avg_price_simple': g['price'].mean().values})"),
    ("ts_013", "df['date'] = pd.to_datetime(df['date'])\n"
               "w = df.set_index('date')['units'].resample('W').sum()\n"
               "result = pd.DataFrame({'week_start': w.index - pd.Timedelta(days=6), 'units': w.values})"),   # 周起始日标签
    ("corr_002", "s = (df['units'] * df['price']).groupby(df['region']).sum()\n"
                 "result = pd.DataFrame({'region': s.index, '销售额': s.values, '销售额占比(%)': s.values / s.sum() * 100})"
                 ".sort_values('销售额', ascending=False)"),                                      # 多带一列
    ("corr_008", "d = df[df['product'] == 'A'].assign(sales=lambda x: x['units'] * x['price'])\n"
                 "s = d.groupby('region')['sales'].sum().sort_values(ascending=False)\n"
                 "result = pd.DataFrame({'地区': s.index, '产品A总销售额': s.values})"),
    ("agg_009", "s = df.groupby('product')['units'].sum()\n"
                "result = pd.DataFrame({'product': s.index, '销量占比(%)': (s / s.sum() * 100).round(2).values})"),  # 占比：百分数
    ("corr_003", "s = df.assign(sales=df['units'] * df['price']).pivot_table(index='product', columns='region', values='sales', aggfunc='sum')\n"
                 "result = s.div(s.sum(axis=1), axis=0).round(4)"),                                 # 占比：比例宽表
    ("ts_002", "df['date'] = pd.to_datetime(df['date'])\n"
               "q = df.assign(sales=df['units'] * df['price']).groupby('Q' + df['date'].dt.quarter.astype(str))['sales'].sum()\n"
               "result = q[q == q.max()]"),                                                        # 'Q2' vs 2
    ("ts_010", "df['date'] = pd.to_datetime(df['date'])\n"
               "m = df.set_index('date')['units'].resample('ME').sum().pct_change()\n"
               "result = str(m.idxmax())[:7]"),                                           # '2024-05' vs 5
    ("ts_003", "df['date'] = pd.to_datetime(df['date'])\n"
               "j = df[df['date'].dt.month == 1]['units'].sum(); r = df[df['date'].dt.month == 3]['units'].sum()\n"
               "result = pd.DataFrame({'年份': [2024], '1月销量': [j], '3月销量': [r], '增长量': [r - j]})"),  # 单行汇总
    ("ts_007", MONTHLY + "result = pd.DataFrame({'类型': ['最高', '最低'], '月份': [str(m.idxmax())[:7], str(m.idxmin())[:7]],"
                         " '销售额': [m.max(), m.min()]})"),                                       # 两行表 vs 元组
    ("filt_003", "result = df[(df['price'] >= 50) & (df['price'] <= 100)].reset_index(drop=True)"),  # gold 修正后：全部记录
    ("corr_007", "t = df.groupby(['product', 'region'])['units'].sum()\n"
                 "result = t.groupby(level=0).agg(['std', 'mean']).rename(columns={'std': '销量标准差'})"),
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
    # ---- 阶段 1.5：新规则不能放过的错误 ----
    ("agg_013", "result = df.assign(s=df['units'] * df['price']).groupby('region')['s'].sum()"),  # 整列碰巧含中位数
    ("agg_013", "result = df.assign(s=df['units'] * df['price']).groupby('region')['s'].median()"),  # 口径错
    ("agg_002", "d = df.assign(s=df['units'] * df['price']).groupby('product')[['s', 'units']].sum()\n"
                "result = pd.DataFrame({'product': d.index, '平均单价': d['s'] / d['units']})"),           # 加权均价 ≠ 简单均价
    ("corr_001", "t = pd.crosstab(df['region'], df['product'], values=df['units'], aggfunc='sum')\n"
                 "result = t.div(t.sum(axis=1), axis=0) * 100"),                                       # 件数 vs 占比
    ("agg_015", "result = df.assign(s=df['units'] * df['price']).groupby('region')['s'].mean()"),      # 理解错
    ("ts_010", "df['date'] = pd.to_datetime(df['date'])\n"
               "m = df.set_index('date')['units'].resample('ME').sum().pct_change()\n"
               "result = str(m.idxmin())[:7]"),                                           # 月份错
    ("ts_007", MONTHLY + "result = pd.DataFrame({'月份': [str(m.idxmin())[:7], str(m.idxmax())[:7]]})"),  # 顺序反
]


def _exec(code):
    result, _, err = run_code(code, DF.copy(), "/tmp/_cmp_case.png")
    assert err is None, err
    return result


@pytest.mark.parametrize("cid,code", SHOULD_PASS, ids=[f"{c}-{i}" for i, (c, _) in enumerate(SHOULD_PASS)])
def test_equivalent_forms_judged_correct(cid, code):
    case = CASES[cid]
    assert results_equal(_exec(code), _exec(case.ground_truth), ordered=case.ordered,
                         percent_equiv=case.percent_equiv)


@pytest.mark.parametrize("cid,code", SHOULD_FAIL, ids=[f"{c}-{i}" for i, (c, _) in enumerate(SHOULD_FAIL)])
def test_wrong_answers_judged_wrong(cid, code):
    case = CASES[cid]
    assert not results_equal(_exec(code), _exec(case.ground_truth), ordered=case.ordered,
                             percent_equiv=case.percent_equiv)


@pytest.mark.parametrize("cid,code,expect", [(c, k, True) for c, k in SHOULD_PASS] + [(c, k, False) for c, k in SHOULD_FAIL],
                         ids=lambda x: x if isinstance(x, str) and len(x) < 10 else "")
def test_dump_load_keeps_judgement(cid, code, expect):
    """B26：报告里存的结构化结果还原后，--rescore 的判定要与在线一致。"""
    from app.eval.report import dump_obj, load_obj
    import json
    case = CASES[cid]
    restored = load_obj(json.loads(json.dumps(dump_obj(_exec(code)), default=str)))
    assert results_equal(restored, _exec(case.ground_truth), ordered=case.ordered,
                         percent_equiv=case.percent_equiv) is expect
