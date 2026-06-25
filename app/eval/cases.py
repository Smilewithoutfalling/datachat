"""50条标注测试用例，覆盖聚合/过滤/关联/时序四类分析场景。

每个用例包含自然语言问题 + 标准答案代码。
"""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    category: str          # aggregation | filtering | correlation | timeseries
    question: str           # 中文自然语言问题
    ground_truth: str       # pandas代码，执行后 result = 期望结果
    keywords: list = field(default_factory=list)   # 生成代码应包含的关键词
    has_chart: bool = False


# ============================================================
# 聚合类 (15条)
# ============================================================
AGG_CASES = [
    EvalCase(
        id="agg_001", category="aggregation",
        question="哪个地区的总销售额最高？",
        ground_truth="result = (df['units'] * df['price']).groupby(df['region']).sum().idxmax()",
        keywords=["groupby", "sum"],
    ),
    EvalCase(
        id="agg_002", category="aggregation",
        question="各产品的平均单价是多少？",
        ground_truth="result = df.groupby('product')['price'].mean().round(2)",
        keywords=["groupby", "mean"],
    ),
    EvalCase(
        id="agg_003", category="aggregation",
        question="总共有多少条销售记录？",
        ground_truth="result = len(df)",
        keywords=["len"],
    ),
    EvalCase(
        id="agg_004", category="aggregation",
        question="销量（件数）最高的地区是哪个？",
        ground_truth="result = df.groupby('region')['units'].sum().idxmax()",
        keywords=["groupby", "sum", "units"],
    ),
    EvalCase(
        id="agg_005", category="aggregation",
        question="每个地区各产品的总销量",
        ground_truth="result = df.groupby(['region', 'product'])['units'].sum()",
        keywords=["groupby", "sum"],
    ),
    EvalCase(
        id="agg_006", category="aggregation",
        question="各地区的销售总额是多少？画柱状图。",
        ground_truth="result = (df['units'] * df['price']).groupby(df['region']).sum()",
        keywords=["groupby", "sum", "plot", "bar"],
        has_chart=True,
    ),
    EvalCase(
        id="agg_007", category="aggregation",
        question="平均每个订单卖了多少件商品？",
        ground_truth="result = df['units'].mean()",
        keywords=["mean"],
    ),
    EvalCase(
        id="agg_008", category="aggregation",
        question="最高单价和最低单价分别是多少？",
        ground_truth="result = (df['price'].max(), df['price'].min())",
        keywords=["max", "min"],
    ),
    EvalCase(
        id="agg_009", category="aggregation",
        question="各产品的总销量占比分别是多少？",
        ground_truth="result = (df.groupby('product')['units'].sum() / df['units'].sum()).round(4)",
        keywords=["groupby", "sum"],
    ),
    EvalCase(
        id="agg_010", category="aggregation",
        question="总销售额是多少元？",
        ground_truth="result = int((df['units'] * df['price']).sum())",
        keywords=["sum"],
    ),
    EvalCase(
        id="agg_011", category="aggregation",
        question="每个产品在各地区的平均单价",
        ground_truth="result = df.groupby(['product', 'region'])['price'].mean().round(2)",
        keywords=["groupby", "mean"],
    ),
    EvalCase(
        id="agg_012", category="aggregation",
        question="哪个产品的总销量最大？",
        ground_truth="result = df.groupby('product')['units'].sum().idxmax()",
        keywords=["groupby", "sum", "idxmax"],
    ),
    EvalCase(
        id="agg_013", category="aggregation",
        question="各地区销售总额的中位数是多少？",
        ground_truth="result = (df['units'] * df['price']).groupby(df['region']).sum().median()",
        keywords=["groupby", "sum", "median"],
    ),
    EvalCase(
        id="agg_014", category="aggregation",
        question="每个地区有多少条销售记录？",
        ground_truth="result = df['region'].value_counts()",
        keywords=["value_counts"],
    ),
    EvalCase(
        id="agg_015", category="aggregation",
        question="平均每个地区的销售额是多少？",
        ground_truth="result = (df['units'] * df['price']).groupby(df['region']).sum().mean()",
        keywords=["groupby", "sum", "mean"],
    ),
]

# ============================================================
# 过滤类 (12条)
# ============================================================
FILT_CASES = [
    EvalCase(
        id="filt_001", category="filtering",
        question="销量大于100件的记录有多少条？",
        ground_truth="result = int((df['units'] > 100).sum())",
        keywords=["df[", ">"],
    ),
    EvalCase(
        id="filt_002", category="filtering",
        question="列出华东地区的所有销售记录，按日期排序。",
        ground_truth="result = df[df['region'] == '华东'].sort_values('date')[['date', 'region', 'product', 'units', 'price']]",
        keywords=["region", "sort_values"],
    ),
    EvalCase(
        id="filt_003", category="filtering",
        question="单价在50到100元之间的产品有哪些记录？",
        ground_truth="result = df[(df['price'] >= 50) & (df['price'] <= 100)][['product', 'price']].drop_duplicates()",
        keywords=["price", "&"],
    ),
    EvalCase(
        id="filt_004", category="filtering",
        question="销售额最高的5条记录是哪些？",
        ground_truth="result = df.assign(sales=df['units'] * df['price']).nlargest(5, 'sales')[['date', 'region', 'product', 'units', 'price']]",
        keywords=["nlargest", "sort_values"],
    ),
    EvalCase(
        id="filt_005", category="filtering",
        question="产品A在华北地区的所有销售记录",
        ground_truth="result = df[(df['product'] == 'A') & (df['region'] == '华北')][['date', 'units', 'price']]",
        keywords=["product", "region", "&"],
    ),
    EvalCase(
        id="filt_006", category="filtering",
        question="销量最少的那条记录是什么？",
        ground_truth="result = df.nsmallest(1, 'units')[['date', 'region', 'product', 'units']]",
        keywords=["nsmallest", "sort_values", "min"],
    ),
    EvalCase(
        id="filt_007", category="filtering",
        question="销售额超过5000元的订单有哪些？按销售额从高到低排列。",
        ground_truth="result = df.assign(sales=df['units'] * df['price']).query('sales > 5000').sort_values('sales', ascending=False)[['date', 'region', 'product', 'units', 'price']]",
        keywords=["sales", "sort_values", ">"],
    ),
    EvalCase(
        id="filt_008", category="filtering",
        question="日期在2024年4月及之后的记录有哪些？",
        ground_truth="result = df[df['date'] >= '2024-04-01'][['date', 'region', 'product', 'units']]",
        keywords=["date", ">="],
    ),
    EvalCase(
        id="filt_009", category="filtering",
        question="华东或华南地区的记录有多少条？",
        ground_truth="result = int(df['region'].isin(['华东', '华南']).sum())",
        keywords=["isin", "region"],
    ),
    EvalCase(
        id="filt_010", category="filtering",
        question="产品B且销量大于80件的记录",
        ground_truth="result = df[(df['product'] == 'B') & (df['units'] > 80)][['date', 'region', 'units']]",
        keywords=["product", "units", "&"],
    ),
    EvalCase(
        id="filt_011", category="filtering",
        question="2024年第一季度的所有记录有多少条？",
        ground_truth="result = int(((df['date'] >= '2024-01-01') & (df['date'] <= '2024-03-31')).sum())",
        keywords=["date", ">=", "<=", "&"],
    ),
    EvalCase(
        id="filt_012", category="filtering",
        question="单价不等于35元的记录有多少条？",
        ground_truth="result = int((df['price'] != 35.0).sum())",
        keywords=["price", "!="],
    ),
]

# ============================================================
# 关联类 (10条)
# ============================================================
CORR_CASES = [
    EvalCase(
        id="corr_001", category="correlation",
        question="各地区的产品销量分布是怎样的？",
        ground_truth="result = pd.crosstab(df['region'], df['product'], values=df['units'], aggfunc='sum').fillna(0).astype(int)",
        keywords=["crosstab", "pivot_table"],
    ),
    EvalCase(
        id="corr_002", category="correlation",
        question="各地区销售额占总销售额的百分比是多少？",
        ground_truth="total = (df['units'] * df['price']).sum(); result = ((df['units'] * df['price']).groupby(df['region']).sum() / total * 100).round(2)",
        keywords=["groupby", "sum", "/"],
    ),
    EvalCase(
        id="corr_003", category="correlation",
        question="每个产品在各地区的销售额占比",
        ground_truth="result = df.assign(sales=df['units'] * df['price']).groupby(['product', 'region'])['sales'].sum().groupby(level=0).apply(lambda x: (x / x.sum() * 100).round(2))",
        keywords=["groupby", "sum"],
    ),
    EvalCase(
        id="corr_004", category="correlation",
        question="销量和单价之间有相关性吗？请计算相关系数。",
        ground_truth="result = df['units'].corr(df['price']).round(4)",
        keywords=["corr"],
    ),
    EvalCase(
        id="corr_005", category="correlation",
        question="各地区各产品的销售总额交叉表",
        ground_truth="result = df.assign(sales=df['units'] * df['price']).pivot_table(values='sales', index='region', columns='product', aggfunc='sum', fill_value=0).astype(int)",
        keywords=["pivot_table"],
    ),
    EvalCase(
        id="corr_006", category="correlation",
        question="每个地区有多少种不同的产品在销售？",
        ground_truth="result = df.groupby('region')['product'].nunique()",
        keywords=["nunique", "groupby"],
    ),
    EvalCase(
        id="corr_007", category="correlation",
        question="分析各产品在不同地区的销量标准差，判断分布是否均匀。",
        ground_truth="result = df.groupby('product')['units'].std().round(2)",
        keywords=["groupby", "std"],
    ),
    EvalCase(
        id="corr_008", category="correlation",
        question="对比各地区产品A的总销售额。",
        ground_truth="result = df[df['product'] == 'A'].assign(sales=lambda x: x['units'] * x['price']).groupby('region')['sales'].sum().astype(int)",
        keywords=["product", "A", "groupby", "sum"],
    ),
    EvalCase(
        id="corr_009", category="correlation",
        question="哪个地区的平均单价最高？",
        ground_truth="result = df.groupby('region')['price'].mean().idxmax()",
        keywords=["groupby", "mean", "idxmax"],
    ),
    EvalCase(
        id="corr_010", category="correlation",
        question="各地区各产品的销售额，画堆叠柱状图。",
        ground_truth="result = df.assign(sales=df['units'] * df['price']).groupby(['region', 'product'])['sales'].sum()",
        keywords=["groupby", "sum", "bar", "plot"],
        has_chart=True,
    ),
]

# ============================================================
# 时序类 (13条)
# ============================================================
TS_CASES = [
    EvalCase(
        id="ts_001", category="timeseries",
        question="每月的总销售额变化趋势是怎样的？画折线图。",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = (df.assign(sales=df['units'] * df['price']).set_index('date')['sales'].resample('ME').sum())",
        keywords=["resample", "plot", "date"],
        has_chart=True,
    ),
    EvalCase(
        id="ts_002", category="timeseries",
        question="哪个季度的销售额最高？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df.assign(sales=df['units'] * df['price'], quarter=df['date'].dt.quarter).groupby('quarter')['sales'].sum().idxmax()",
        keywords=["quarter", "groupby", "sum"],
    ),
    EvalCase(
        id="ts_003", category="timeseries",
        question="3月份的销量相比1月份增长了多少？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); jan = df[df['date'].dt.month == 1]['units'].sum(); mar = df[df['date'].dt.month == 3]['units'].sum(); result = int(mar - jan)",
        keywords=["month", "sum", "units"],
    ),
    EvalCase(
        id="ts_004", category="timeseries",
        question="产品A的月度销量变化情况",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df[df['product'] == 'A'].set_index('date')['units'].resample('ME').sum()",
        keywords=["product", "A", "resample"],
    ),
    EvalCase(
        id="ts_005", category="timeseries",
        question="每月的订单数量是多少？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df.set_index('date').resample('ME').size()",
        keywords=["resample", "size", "count"],
    ),
    EvalCase(
        id="ts_006", category="timeseries",
        question="4月份各产品的销售额排名",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df[df['date'].dt.month == 4].assign(sales=df['units'] * df['price']).groupby('product')['sales'].sum().sort_values(ascending=False)",
        keywords=["month", "groupby", "sum", "sort_values"],
    ),
    EvalCase(
        id="ts_007", category="timeseries",
        question="销售额最高的月份和最低的月份分别是哪个月？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); s = df.assign(sales=df['units'] * df['price']).set_index('date')['sales'].resample('ME').sum(); result = (str(s.idxmax())[:7], str(s.idxmin())[:7])",
        keywords=["resample", "sum", "idxmax", "idxmin"],
    ),
    EvalCase(
        id="ts_008", category="timeseries",
        question="每月各地区销售额的变化趋势",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df.assign(sales=df['units'] * df['price']).pivot_table(values='sales', index=df['date'].dt.month, columns='region', aggfunc='sum', fill_value=0).astype(int)",
        keywords=["pivot_table", "month", "groupby"],
    ),
    EvalCase(
        id="ts_009", category="timeseries",
        question="第一季度和第二季度的销售总额分别是多少？哪个季度更高？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); df['quarter'] = df['date'].dt.quarter; result = df.assign(sales=df['units'] * df['price']).groupby('quarter')['sales'].sum().astype(int)",
        keywords=["quarter", "groupby", "sum"],
    ),
    EvalCase(
        id="ts_010", category="timeseries",
        question="哪个月份销量增长最快（环比增长率最高）？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); monthly = df.set_index('date')['units'].resample('ME').sum(); result = int(str(monthly.diff().idxmax())[5:7]) if len(monthly) > 1 else 1",
        keywords=["resample", "sum", "diff"],
    ),
    EvalCase(
        id="ts_011", category="timeseries",
        question="每月平均单价的走势是怎样的？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df.set_index('date')['price'].resample('ME').mean().round(2)",
        keywords=["resample", "mean", "price"],
    ),
    EvalCase(
        id="ts_012", category="timeseries",
        question="产品B在1-3月的累计销售额是多少？",
        ground_truth="df['date'] = pd.to_datetime(df['date']); mask = (df['product'] == 'B') & (df['date'].dt.month.isin([1, 2, 3])); result = int((df.loc[mask, 'units'] * df.loc[mask, 'price']).sum())",
        keywords=["product", "B", "sum", "month"],
    ),
    EvalCase(
        id="ts_013", category="timeseries",
        question="按周汇总销量",
        ground_truth="df['date'] = pd.to_datetime(df['date']); result = df.set_index('date')['units'].resample('W').sum()",
        keywords=["resample", "sum", "W"],
    ),
]

ALL_CASES = AGG_CASES + FILT_CASES + CORR_CASES + TS_CASES

CATEGORY_MAP = {
    "aggregation": "聚合",
    "filtering": "过滤",
    "correlation": "关联",
    "timeseries": "时序",
}
