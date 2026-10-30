# 闸门判定工作台（对照填写）

每题一块。**只判核心结论**：`result_text`（代码真实输出）+ `answer`（模型叙述）是否命中 `gold` 或某个 `alt`。  
`auto_correct / match` 是**比较器参考，不是判据**（M02 实证它会双向失准）。

标记：★ = 优先人工抽审（比较器放宽口径判对 / 未执行 / answer 为空 / 拒答题）

失败分类：1 编码/解析 · 2 schema 理解 · 3 口径歧义 · 4 计算错 · 5 result 契约违反 · 6 拒答失当

---

# agent = react   （gate_20261012_104407_react.json）

meta：model=Qwen3.5-397B-A17B  temperature=0.0  git_sha=ebc4e7b?  questions_sha256=75a559642e4e

## react · s01   [single / 聚合]

**Q**：2011 年全年的销售额是多少英镑？销售额按数量乘以单价算。

- gold(scalar)：`8998790.91`
- alt(scalar)：`9820814.28`  — 去掉取消单（发票号以 C 开头）
- note：净额：所有行数量×单价求和（取消单为负数，自然冲减）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=27.36s  tokens=8964

**模型代码**

```python
df['开票时间_dt'] = pd.to_datetime(df['开票时间'])
df['销售额'] = df['数量'] * df['单价（英镑）']
d = df[df['开票时间_dt'].dt.year == 2011]
result = round(d['销售额'].sum(), 2)
```

**代码输出 result_text**：`8998790.91`

**模型结论 answer**：

> 2011 年全年（按开票时间在 2011 年内的全部单据，销售额 = 数量 × 单价）的销售额为 **8,998,790.91 英镑**。
>
> 说明：
>
> - 该口径已包含退货/取消单据（负数量，共 9,826 行，合计冲减约 82.2 万英镑）；若只统计正向销售单据，则为 9,820,814.28 英镑。
> - 2011 年共涉及 499,428 条明细记录。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：8998790.91 与 gold 一致（并给出 alt 9,820,814.28））

## react · s02   [single / 聚合]

**Q**：一共有多少个不同的客户？

- gold(scalar)：`4372`
- alt：无
- note：去重客户编号，不含缺失（脏表里缺失写成'未登记'，不能算一个客户）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=10.4s  tokens=6079

**模型代码**

```python
result = df['客户编号'].nunique()
```

**代码输出 result_text**：`4373`

**模型结论 answer**：

> 一共有 **4373** 个不同的客户。
>
> 说明：按「客户编号」去重统计，数据中该字段无空值、无空字符串，因此去重结果即为有效客户数 4373。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：答 4373，比 gold 4372 多 1：把缺失客户编号的哨兵值'未登记'当成一个真实客户）

## react · s03   [single / 聚合]

**Q**：平均每张发票的金额是多少英镑？

- gold(scalar)：`376.36`
- alt(scalar)：`482.44`  — 只算未取消的发票
- note：每张发票金额求和后取平均，含取消发票（金额为负）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=5.44s  tokens=2867

**模型代码**

```python
df['金额'] = df['数量'] * df['单价（英镑）']
invoice_total = df.groupby('发票号')['金额'].sum()
result = round(invoice_total.mean(), 2)
```

**代码输出 result_text**：`376.36`

**模型结论 answer**：

> 平均每张发票的金额约为 **376.36 英镑**。
>
> 说明：金额按"数量 × 单价"逐行计算后，按发票号汇总得到每张发票的总金额，再对所有发票取平均（共约 5.4 万行明细记录）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：376.36 与 gold 一致（脚注'约 5.4 万行明细'与事实不符，不影响结论））

## react · s04   [single / 聚合]  ★ answer 空

**Q**：英国以外的国家一共卖出了多少件商品？

- gold(scalar)：`912621`
- alt(scalar)：`927162`  — 去掉取消单
- note：净数量；报表变体末尾有'合计'行（国家为空），按'国家≠英国'过滤会把合计行算进去
- 状态：executed=True  error_kind=agent  error=ReAct 超过步数上限（recursion_limit=25）仍未给出结论
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=3  duration=48.52s  tokens=34673

**模型代码**

```python
df.columns = ['发票号','商品编码','商品描述','数量','开票时间','单价','客户编号','国家']
df['数量'] = pd.to_numeric(df['数量'], errors='coerce')
print(df[df['国家'].isna()].to_string())
mask = (df['国家']!='United Kingdom') & df['国家'].notna()
result = df.loc[mask,'数量'].sum()
```

**代码输出 result_text**：`912621.0`

**模型结论 answer**：

> (空)

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：912621 与 gold 一致；但 answer 为空、error_kind=agent（触到步数上限），只出数值无叙述）

## react · s05   [single / 过滤]

**Q**：有多少张被取消的发票？

- gold(scalar)：`3836`
- alt：无
- note：发票号以 C 开头的去重发票数（数据集说明的定义）；数量为负但非 C 开头的是库存调整，不是取消
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=11.57s  tokens=6958

**模型代码**

```python

mask = df['发票号'].astype(str).str.startswith('C')
result = int(df.loc[mask, '发票号'].nunique())
```

**代码输出 result_text**：`3836`

**模型结论 answer**：

> 被取消的发票共有 **3836 张**。
>
> 说明：
>
> - 判断口径：发票号以字母 "C" 开头（Cancel）视为取消发票，这些行的数量全部为负数，符合退货/冲销特征。
> - 取消记录共涉及 **9288 行**明细，去重后对应 **3836 张**唯一发票号。
> - 另有 1336 行发票号不带 "C" 但数量为负，属于异常/调整记录，未计入取消发票。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：3836 与 gold 一致，且正确排除了非 C 开头的负数量调整行）

## react · s06   [single / 过滤]

**Q**：单价超过 100 英镑的记录有多少条？

- gold(scalar)：`1036`
- alt：无
- note：单价 > 100 的行数（含邮费/手工调整等特殊行）；报表变体有两行表头
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=22.06s  tokens=17180

**模型代码**

```python
data = df.iloc[1:].copy()
price = pd.to_numeric(data['商品信息.1'], errors='coerce')
result = int((price > 100).sum())
```

**代码输出 result_text**：`1036`

**模型结论 answer**：

> **结论：单价超过 100 英镑的记录共有 1036 条。**
>
> 说明：
>
> - 数据首行为表头，实际数据从第 2 行开始，共约 54.19 万条记录。
> - 单价列（"单价（英镑）"）中有 1 条无法解析为数值，已排除；若按"≥100 英镑"口径则为 1037 条。
> - 单价最高达 38970 英镑（可能为大额/特殊订单）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：1036 与 gold 一致）

## react · s07   [single / 过滤]

**Q**：2011 年 12 月有哪些国家下过单？

- gold(list)：`list[21] Austria, Belgium, Channel Islands, Cyprus, Denmark, EIRE, Finland, France…`
- alt(list)：`list[18] Austria, Belgium, Channel Islands, Denmark, EIRE, Finland, France, Germany…`  — 不算只有取消单的国家
- note：2011-12 出现过的国家（集合，不要求顺序）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=1  duration=12.14s  tokens=7057

**模型代码**

```python
df['开票时间_dt'] = pd.to_datetime(df['开票时间'])
mask = (df['开票时间_dt'].dt.year == 2011) & (df['开票时间_dt'].dt.month == 12)
sub = df[mask]
countries = sub['国家'].value_counts()
result = list(countries.index)
print(result)
```

**代码输出 result_text**：`['United Kingdom', 'Germany', 'France', 'EIRE', 'Portugal', 'Belgium', 'Netherlands', 'Norway', 'Spain', 'USA', 'Greece', 'Finland', 'Denmark', 'Iceland', 'Italy', 'Japan', 'Austria', 'Channel Islands', 'Malta', 'Cyprus', 'Sweden']`

**模型结论 answer**：

> 2011 年 12 月共有 **21 个国家/地区**下过单：
>
> United Kingdom、Germany、France、EIRE（爱尔兰）、Portugal、Belgium、Netherlands、Norway、Spain、USA、Greece、Finland、Denmark、Iceland、Italy、Japan、Austria、Channel Islands、Malta、Cyprus、Sweden。
>
> 其中英国（United Kingdom）订单行数最多（23,926 笔），远超其他国家；其次是德国（340）、法国（339）、EIRE（335）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：21 国集合与 gold 完全一致；比较器漏判（列表形态未匹配））

## react · s08   [single / 排序]

**Q**：销售额最高的前 5 个国家是哪些？

- gold(list)：`list[5] United Kingdom, Netherlands, EIRE, Germany, France`
- alt：无
- note：按净销售额排前 5；去掉取消单时前 5 及顺序相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=1  duration=14.66s  tokens=7260

**模型代码**

```python
df['销售额'] = df['数量'] * df['单价（英镑）']
top5 = df.groupby('国家')['销售额'].sum().sort_values(ascending=False).head(5)
import matplotlib.pyplot as plt
s = top5.sort_values(ascending=True)
ax = s.plot(kind='barh', color='#4C72B0')
for i, (lab, y) in enumerate(s.items()):
    ax.text(y, i, f' {y:,.0f}', va='center', fontsize=10)
ax.set_title('销售额最高的前5个国家')
ax.set_xlabel('销售额（英镑）')
ax.set_ylabel('国家')
ax.set_xlim(0, s.max()*1.15)
plt.tight_layout()
plt.savefig(chart_path)
result = top5
```

**代码输出 result_text**：`[序列，5 项]
国家
United Kingdom    8187806.364
Netherlands        284661.540
EIRE               263276.820
Germany            221698.210
France             197403.900`

**模型结论 answer**：

> 销售额最高的前 5 个国家依次为：
>
> 1. United Kingdom（英国）：约 8,187,806 英镑
> 2. Netherlands（荷兰）：约 284,662 英镑
> 3. EIRE（爱尔兰）：约 263,277 英镑
> 4. Germany（德国）：约 221,698 英镑
> 5. France（法国）：约 197,404 英镑
>
> 说明：销售额按「数量 × 单价」汇总计算，包含全部交易记录（含退货等负数量记录）。英国遥遥领先，其销售额约为第 2 名荷兰的 29 倍，占绝对主导地位。
>
> 图表以横向条形图展示了这 5 个国家的销售额对比，可直观看出英国的量级远超其他国家。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：前 5 国家及顺序与 gold 一致；比较器漏判（Series 索引未对齐））

## react · s09   [single / 排序]

**Q**：实际卖出数量最多的商品是哪个？

- gold(label)：`WORLD WAR 2 GLIDERS ASSTD DESIGNS`
- alt(label)：`22197`  — 按商品编码汇总（同一编码有多个描述）
- alt(label)：`POPCORN HOLDER`  — 按商品编码汇总后报该编码的描述
- alt(label)：`SMALL POPCORN HOLDER`  — 按商品编码汇总后报该编码的描述
- note：净数量（取消单冲减）。陷阱：'PAPER CRAFT , LITTLE BIRDIE' 有 80995 件的单子被整单取消，只看正数量会错选它
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=9.11s  tokens=6812

**模型代码**

```python
s = df.groupby(['商品编码','商品描述'])['数量'].sum().sort_values(ascending=False)
result = s.index[0][1]
```

**代码输出 result_text**：`WORLD WAR 2 GLIDERS ASSTD DESIGNS`

**模型结论 answer**：

> 实际卖出数量最多的商品是 **WORLD WAR 2 GLIDERS ASSTD DESIGNS**（商品编码 84077），累计销量 53,847 件。
>
> 紧随其后的是 JUMBO BAG RED RETROSPOT（47,363 件）和 ASSORTED COLOUR BIRD ORNAMENT（36,381 件）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：WORLD WAR 2 GLIDERS ASSTD DESIGNS 与 gold 一致，避开了 PAPER CRAFT 整单取消陷阱）

## react · s10   [single / 时间]  ★ 比较器放宽口径判对

**Q**：哪个月的销售额最高？

- gold(label)：`2011-11`
- alt：无
- note：按月净销售额最高的月份；去掉取消单结果相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=extras   ← 参考，不是判据
- 成本：attempts=2  duration=44.69s  tokens=35851

**模型代码**

```python

data = df.iloc[1:].copy()
data.columns = ['发票号','商品编码','商品描述','数量','开票时间','单价','客户编号','国家']
data['数量'] = pd.to_numeric(data['数量'], errors='coerce')
data['单价'] = pd.to_numeric(data['单价'], errors='coerce')
data['开票时间'] = pd.to_datetime(data['开票时间'], errors='coerce')
data['月份'] = data['开票时间'].dt.to_period('M')
data['销售额'] = data['数量'] * data['单价']
monthly = data.dropna(subset=['月份']).groupby('月份')['销售额'].sum().sort_index()
top5 = monthly.sort_values(ascending=False).head(5)
result = top5.round(2)
```

**代码输出 result_text**：`[序列，5 项]
月份
2011-11    1461756.25
2011-10    1070704.67
2011-09    1019687.62
2010-12     748957.02
2011-05     723333.51
Freq: M`

**模型结论 answer**：

> **2011年11月（2011-11）** 的销售额最高。
>
> 分析结论：
>
> - 按"开票时间"取月份、以"数量 × 单价"计算销售额并逐月汇总，**2011-11 销售额约 146.2 万英镑**，为全期最高。
> - 其后依次为 2011-10（约 107.1 万）、2011-09（约 102.0 万）、2010-12（约 74.9 万）、2011-05（约 72.3 万），可见每年秋冬（10–12 月）是销售旺季。
>
> 图表展示了各月销售额的柱状对比，红色标注的 2011-11 即为销售额峰值月份。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]  
　　　reason：（AI 预标注：2011-11 与 gold 一致）

## react · s11   [single / 时间]

**Q**：2011 年每个季度的销售额分别是多少？

- gold(series)：`None`
- alt(series)：`None`  — 去掉取消单
- note：2011 年 Q1–Q4 净销售额
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=1  duration=14.89s  tokens=7414


**模型代码**
```python

import pandas as pd, matplotlib.pyplot as plt
df['开票时间'] = pd.to_datetime(df['开票时间'])
df['销售额'] = df['数量'] * df['单价（英镑）']
d2011 = df[df['开票时间'].dt.year == 2011]
q = d2011.groupby(d2011['开票时间'].dt.quarter)['销售额'].sum()
q.index = ['Q1','Q2','Q3','Q4']
ax = q.plot(kind='bar', color='#4C72B0')
for i, v in enumerate(q.values):
    ax.text(i, v, f'{v:,.0f}', ha='center', va='bottom')
ax.set_title('2011 年各季度销售额')
ax.set_xlabel('季度')
ax.set_ylabel('销售额（英镑）')
plt.xticks(rotation=0)
plt.savefig(chart_path)
result = q
print(result)
```
**代码输出 result_text**：`[序列，4 项]
Q1    1741329.990
Q2    1907663.751
Q3    2383668.243
Q4    2966128.930`

**模型结论 answer**：

> 2011 年各季度销售额（销售额 = 数量 × 单价，含所有发票记录，未剔除退货负数单据）如下：
> 
> - Q1：1,741,330 英镑
> - Q2：1,907,664 英镑
> - Q3：2,383,668 英镑
> - Q4：2,966,129 英镑
> 
> 柱状图展示了 2011 年四个季度的销售额，可见全年逐季递增，Q4 最高（约 296.6 万英镑），Q1 最低（约 174.1 万英镑），Q4 约为 Q1 的 1.7 倍。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：Q1–Q4 四个值与 gold 完全一致；比较器漏判（索引标签 Q1 与 1 未对齐））

## react · s12   [single / 占比]

**Q**：没有客户编号的记录占全部记录的百分之几？

- gold(scalar)：`24.93`
- alt：无
- note：缺失客户编号行数 / 总行数 × 100
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=24.77s  tokens=18223

**模型代码**
```python
s = df['客户编号']
mask = s.isna() | s.astype(str).str.strip().isin(['', '未登记', 'nan', 'None', 'NULL', 'null', 'N/A'])
result = round(mask.sum()/len(s)*100, 2)
```
**代码输出 result_text**：`24.93`

**模型结论 answer**：

> 没有客户编号的记录占全部记录的 **24.93%**。
> 
> 说明：
> - 数据中"客户编号"字段没有空值（NaN）或空字符串，缺失是以文本 **"未登记"** 的形式标记的，共 135,080 条。
> - 全部记录 541,909 条，因此占比 = 135,080 / 541,909 ≈ **24.93%**（约 1/4）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：24.93 与 gold 一致，且正确识别'未登记'为缺失）

## react · s13   [single / 占比]  ★ 比较器放宽口径判对

**Q**：英国的销售额占总销售额的比例是多少？

- gold(scalar)：`84.0`
- alt(scalar)：`84.58`  — 去掉取消单
- note：英国净销售额 / 全部净销售额 × 100
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=scaled   ← 参考，不是判据
- 成本：attempts=0  duration=8.73s  tokens=3067

**模型代码**
```python
df['销售额'] = df['数量'] * df['单价（英镑）']
total = df['销售额'].sum()
uk = df.loc[df['国家'] == 'United Kingdom', '销售额'].sum()
ratio = uk / total
result = {'总销售额': total, '英国销售额': uk, '英国占比': ratio}
print(result)
```
**代码输出 result_text**：`{'总销售额': 9747747.934, '英国销售额': 8187806.364, '英国占比': 0.8399690286862109}`

**模型结论 answer**：

> 英国销售额占总销售额的比例约为 **84.0%**。
> 
> - 总销售额：约 9,747,747.93 英镑
> - 英国（United Kingdom）销售额：约 8,187,806.36 英镑
> - 占比：8,187,806.36 / 9,747,747.93 ≈ 0.8400，即 **83.997% ≈ 84.0%**
> 
> （销售额按"数量 × 单价"计算，未剔除退货等负值记录，为全量口径。）

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：84.0% 与 gold 一致）

## react · s14   [single / 拒答]  ★ 拒答题

**Q**：整体毛利率是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有成本/进价字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=refusal   ← 参考，不是判据
- 成本：attempts=0  duration=9.32s  tokens=2985

**模型代码**
```python
result = '无法回答：数据中没有成本字段，仅有单价，无法计算毛利率'
```
**代码输出 result_text**：`无法回答：数据中没有成本字段，仅有单价，无法计算毛利率`

**模型结论 answer**：

> 无法回答：数据中没有成本字段，仅有单价，无法计算毛利率。
> 
> 当前数据表仅包含发票号、商品编码、商品描述、数量、开票时间、单价（英镑）、客户编号、国家这 8 个字段，缺少计算毛利率所必需的成本（或进价）信息，因此无法计算整体毛利率。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：正确拒答（无成本字段））

## react · s15   [single / 拒答]  ★ 未执行 / 拒答题

**Q**：女性客户的消费总额是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有性别字段
- 状态：executed=False  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=2.76s  tokens=1327

**模型代码**
```python
(无)
```
**代码输出 result_text**：`(空)`

**模型结论 answer**：

> {"message":"prompt 必须包含字符串内容

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：未执行成功：answer='{"message":"prompt 必须包含字符串内容'，疑似网关/管线异常（非推理失败）。建议 --only s15 复跑甄别）

## react · m01   [multi / join聚合]

**Q**：各个州（按客户所在州）的订单数分别是多少？

- gold(series)：`None`
- alt：无
- note：orders ⋈ customers（customer_id），按 customer_state 数订单
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=21.1s  tokens=19100

**模型代码**
```python
o = dfs['orders']; c = dfs['customers']
m = o.merge(c[['customer_id','customer_state']], on='customer_id', how='left')
s = m['customer_state'].value_counts()
import matplotlib.pyplot as plt
ax = s.plot(kind='bar', color='#4C72B0')
for i,(lab,y) in enumerate(s.items()):
    ax.text(i, y+300, f'{y:,}', ha='center', fontsize=8)
ax.set_title('各客户所在州的订单数')
ax.set_xlabel('客户所在州'); ax.set_ylabel('订单数')
plt.xticks(rotation=0); plt.tight_layout(); plt.savefig(chart_path)
result = s.rename_axis('customer_state').rename('order_count')
print(result)
```
**代码输出 result_text**：`[序列，27 项]
customer_state
SP    41746
RJ    12852
MG    11635
RS     5466
PR     5045
SC     3637
BA     3380
DF     2140
ES     2033
GO     2020
PE     1652
CE     1336
PA      975
MT      907
MA      747
MS      715
PB      536
PI      495
RN      485
AL      413
SE      350
TO      280
RO      253
AM      148
AC       81
AP       68
RR       46`

**模型结论 answer**：

> 各客户所在州的订单数（共 99,441 单，覆盖 27 个州）：
> 
> | 州 | 订单数 | 州 | 订单数 |
> |---|---|---|---|
> | SP | 41,746 | CE | 1,336 |
> | RJ | 12,852 | PA | 975 |
> | MG | 11,635 | MT | 907 |
> | RS | 5,466 | MA | 747 |
> | PR | 5,045 | MS | 715 |
> | SC | 3,637 | PB | 536 |
> | BA | 3,380 | PI | 495 |
> | DF | 2,140 | RN | 485 |
> | ES | 2,033 | AL | 413 |
> | GO | 2,020 | SE | 350 |
> | PE | 1,652 | TO | 280 |
> | RO | 253 | AM | 148 |
> | AC | 81 | AP | 68 |
> | RR | 46 | | |
> 
> 结论：订单高度集中在东南部，SP（圣保罗）以 41,746 单居首，约占全部订单的 42%，RJ、MG 分列二三位（12,852、11,635），前三州合计约 66%；最少的 RR（罗赖马）仅 46 单。
> 
> 图表为按订单数降序排列的柱状图，展示了 27 个客户所在州的订单量分布，可直观看出东南三州的绝对优势与北部/中部州的极低单量。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：27 州订单数与 gold 完全一致）

## react · m02   [multi / join聚合]

**Q**：SP 州的客户一共付了多少钱？

- gold(scalar)：`5998226.96`
- alt(scalar)：`5923688.9`  — 用 order_items 的商品价+运费代替实付
- note：payments ⋈ orders ⋈ customers，SP 州 payment_value 合计（所有订单状态）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=9.83s  tokens=8641

**模型代码**
```python
cust = dfs['customers']
pay = dfs['order_payments']
ord_ = dfs['orders']

# SP 州客户的订单 -> 支付金额
sp_customers = cust[cust['customer_state'] == 'SP']
sp_orders = ord_[ord_['customer_id'].isin(sp_customers['customer_id'])]
sp_pay = pay[pay['order_id'].isin(sp_orders['order_id'])]
result = sp_pay['payment_value'].sum()
print(round(result, 2), len(sp_orders), len(sp_pay))
```
**代码输出 result_text**：`5998226.96`

**模型结论 answer**：

> SP 州客户一共支付了约 **5,998,226.96 雷亚尔（BRL）**。
> 
> 说明：
> - 口径：先从 customers 表筛出 customer_state = 'SP' 的客户，关联其所有订单（orders），再汇总这些订单在 order_payments 表中的 payment_value（含所有支付方式、所有分期记录）。
> - 涉及 SP 州客户订单约 1.5 万+ 笔、支付记录 1.6 万+ 条；未对订单状态做过滤（包含取消/未送达等订单的已支付金额）。如只统计已送达（delivered）订单，金额会略低。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：5998226.96 与 gold 一致）

## react · m03   [multi / join聚合]

**Q**：按卖家所在州统计，各州卖出商品的平均单价是多少？

- gold(series)：`None`
- alt：无
- note：order_items ⋈ sellers（seller_id），按 seller_state 求 price 均值（每个订单行算一次）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=16.59s  tokens=19677

**模型代码**
```python
oi = dfs['order_items']
se = dfs['sellers']
m = oi.merge(se[['seller_id','seller_state']], on='seller_id', how='left')
g = m.groupby('seller_state')['price'].mean().sort_values(ascending=False)
import matplotlib.pyplot as plt
ax = g.plot(kind='bar', color='#4C72B0')
ax.set_title('各卖家所在州商品平均单价（雷亚尔）')
ax.set_xlabel('卖家所在州')
ax.set_ylabel('平均单价（R$）')
for i,(lab,y) in enumerate(g.items()):
    ax.text(i, y+5, f'{y:.0f}', ha='center', fontsize=8)
plt.tight_layout()
plt.savefig(chart_path)
result = g
print('ok')
```
**代码输出 result_text**：`[序列，23 项]
seller_state
PB    449.868421
BA    444.108180
AM    392.333333
RO    340.157143
AC    267.000000
CE    215.325957
PI    210.166667
PE    204.227344
RN    178.439286
RJ    175.173147
RS    172.150769
MS    171.033800
SE    160.620000
SC    155.196582
PA    154.750000
PR    145.529606
ES    128.197876
GO    127.690788
MT    117.729103
MG    114.598928
SP    108.951684
DF    108.731346
MA     89.898642`

**模型结论 answer**：

> 按卖家所在州统计的商品平均单价（R$，按 order_items 中每条商品记录的 price 计算，共 23 个州）：
> 
> | 州 | 平均单价 | 州 | 平均单价 |
> |---|---|---|---|
> | PB | 449.87 | SE | 160.62 |
> | BA | 444.11 | SC | 155.20 |
> | AM | 392.33 | PA | 154.75 |
> | RO | 340.16 | PR | 145.53 |
> | AC | 267.00 | ES | 128.20 |
> | CE | 215.33 | GO | 127.69 |
> | PI | 210.17 | MT | 117.73 |
> | PE | 204.23 | MG | 114.60 |
> | RN | 178.44 | SP | 108.95 |
> | RJ | 175.17 | DF | 108.73 |
> | RS | 172.15 | MA | 89.90 |
> | MS | 171.03 | | |
> 
> 结论：
> - 平均单价最高的是 **PB（449.87）**，其次 BA（444.11）、AM（392.33）、RO（340.16）；最低的是 **MA（89.90）**，DF、SP 也偏低（约 109）。
> - 整体呈现"北部/东北部部分州单价高、订单量大的 SP/MG 等州单价低"的特征：PB、BA 等州样本量较小，均值易受高价商品影响；SP 卖家数量最多、以低价商品为主。
> - 口径说明：以订单明细行（每个商品条目）为单位求 price 的算术平均，未按订单去重；如按订单平均金额口径结果会有差异。
> 
> 图表展示了 23 个卖家所在州按平均单价从高到低的柱状对比，可直接看出 PB、BA 领先、MA 垫底的分布。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：23 州平均单价与 gold 完全一致）

## react · m04   [multi / join聚合]

**Q**：给了 1 星评价的订单，从下单到送达平均用了多少天？

- gold(scalar)：`21.31`
- alt(scalar)：`20.85`  — 按整天数（.dt.days）算
- note：reviews(score=1) ⋈ orders，送达时间 - 下单时间，未送达的不计；按订单去重
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=19.55s  tokens=24055

**模型代码**
```python

orders = dfs['orders']
rev = dfs['order_reviews']
d = rev.merge(orders[['order_id','order_status','order_purchase_timestamp','order_delivered_customer_date']], on='order_id', how='inner')
d1 = d[d['review_score']==1].copy()
d1['days'] = (pd.to_datetime(d1['order_delivered_customer_date']) - pd.to_datetime(d1['order_purchase_timestamp'])).dt.total_seconds()/86400
v = d1['days'].dropna()
result = round(v.mean(), 2)
```
**代码输出 result_text**：`21.31`

**模型结论 answer**：

> **结论：给了 1 星评价的订单，从下单到实际送达平均约 21.31 天（≈21 天）。**
> 
> 口径说明：
> - 1 星评价订单共 11,424 笔，其中 9,409 笔有实际送达时间（绝大多数状态为 delivered，另有 4 笔已取消但有送达记录），其余因未送达无送达日期，无法计算时长。
> - 计算方式：order_delivered_customer_date − order_purchase_timestamp，取平均值 = 21.31 天；中位数为 16.78 天，说明存在少量极端延迟订单把均值拉高。


**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：21.31 与 gold 一致（alt 20.85 亦可接受））

## react · m05   [multi / join过滤]

**Q**：买过 health_beauty（健康美容）类商品的客户有多少个？

- gold(scalar)：`8678`
- alt(scalar)：`8836`  — 按 customer_id 数（Olist 每个订单一个 customer_id）
- note：items ⋈ products ⋈ translation ⋈ orders ⋈ customers，去重 customer_unique_id
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=16.49s  tokens=23355

**模型代码**
```python
oi = dfs['order_items']; p = dfs['products']
pid = set(p.loc[p.product_category_name == 'beleza_saude', 'product_id'])
oc = oi[oi.product_id.isin(pid)][['order_id','product_id']].merge(dfs['orders'][['order_id','customer_id']], on='order_id')
cu = oc.merge(dfs['customers'][['customer_id','customer_unique_id']], on='customer_id')
result = cu['customer_unique_id'].nunique()
print(result, oc['customer_id'].nunique(), oc['order_id'].nunique())
```
**代码输出 result_text**：`8678`

**模型结论 answer**：

> **结论：买过健康美容（health_beauty，葡语类目 beleza_saude）类商品的客户共有 8,678 个**（按去重后的唯一客户 customer_unique_id 计）。
> 
> 口径说明：
> - 类目映射：category_translation 中 health_beauty ↔ beleza_saude，该类目下有 2,444 个商品。
> - 关联路径：products → order_items（product_id）→ orders（order_id）→ customers（customer_id）。
> - 若按订单表中的 customer_id 计数为 8,836（同一自然人重复注册账号会被重复计），因此更合理的唯一客户数为 8,678；涉及订单数约 9 千余单。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：8678 与 gold 一致（并说明 alt 8836 的口径））

## react · m06   [multi / join过滤]

**Q**：2018 年 8 月下单但最终被取消的订单，一共涉及多少支付金额？

- gold(scalar)：`23921.17`
- alt：无
- note：2018-08 下单、status=canceled 的 84 个订单，payments.payment_value 合计
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=13.21s  tokens=13522

**模型代码**
```python
o = dfs['orders'].copy()
o['t'] = pd.to_datetime(o['order_purchase_timestamp'])
m = o[(o['t'].dt.year==2018)&(o['t'].dt.month==8)]
c = m[m['order_status']=='canceled']
p = dfs['order_payments']
pm = p[p['order_id'].isin(c['order_id'])]
n_orders_pay = pm['order_id'].nunique()
# 订单维度均摊/订单金额
oi = dfs['order_items'].groupby('order_id')['price'].sum()
print(len(c), n_orders_pay, round(pm['payment_value'].sum(),2), round(pm.groupby('order_id')['payment_value'].sum().sum(),2))
print(round(oi.reindex(c['order_id']).sum(),2))
result = round(pm['payment_value'].sum(),2)
```
**代码输出 result_text**：`23921.17`

**模型结论 answer**：

> **结论：** 2018 年 8 月下单、最终状态为 canceled（已取消）的订单共 1,061 单，其中 953 单在支付表中有支付记录，这些订单涉及的支付金额合计约 **23,921.17**（巴西雷亚尔）。
> 
> 说明：
> - 口径：按 orders 表的 order_purchase_timestamp 落在 2018-08 且 order_status = 'canceled' 筛选订单，再关联 order_payments 汇总 payment_value（含同一订单多笔分期/多种支付方式的全部记录）。
> - 另有约 108 单取消订单在支付表中无支付记录（未产生支付），因此支付金额未计入；若按订单商品价 price 汇总，量级也相近。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [ x ]
　　　reason：（AI 预标注：23921.17 与 gold 一致；但叙述称'1,061 单'与 gold 的 84 单不符——金额对、叙述疑为编造，建议核代码）

## react · m07   [multi / 跨表排序]  ★ 比较器放宽口径判对

**Q**：销售额最高的 3 个商品类别是什么？用英文类别名。

- gold(list)：`list[3] health_beauty, watches_gifts, bed_bath_table`
- alt：无
- note：按 price 合计排前 3；加上运费时前 3 及顺序相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=relaxed   ← 参考，不是判据
- 成本：attempts=0  duration=13.0s  tokens=13965

**模型代码**
```python

oi = dfs['order_items']
pr = dfs['products']
ct = dfs['category_translation']
m = oi.merge(pr[['product_id','product_category_name']], on='product_id', how='left').merge(ct, on='product_category_name', how='left')
g = m.groupby('product_category_name_english')['price'].sum().sort_values(ascending=False)
top = g.head(3)

# 交叉验证：按订单总额（含运费）排序是否一致
g2 = m.assign(total=m['price']+m['freight_value']).groupby('product_category_name_english')['total'].sum().sort_values(ascending=False)

ax = top.plot.bar(color=['#4C72B0','#DD8452','#55A868'])
for i,(lab,y) in enumerate(top.items()):
    ax.text(i, y, f'{y:,.0f}', ha='center', va='bottom')
ax.set_title('销售额最高的 3 个商品类别')
ax.set_xlabel('商品类别（英文）'); ax.set_ylabel('销售额（雷亚尔）')
ax.set_xticklabels([t.get_text() for t in ax.get_xticklabels()], rotation=20, ha='right')
plt.tight_layout(); plt.savefig(chart_path)
result = list(top.index)
print(result); print(g2.head(3))
```
**代码输出 result_text**：`['health_beauty', 'watches_gifts', 'bed_bath_table']`

**模型结论 answer**：

> 销售额最高的 3 个商品类别（英文类别名）为：
> 
> 1. **health_beauty**（健康美容）—— 约 1,258,681 雷亚尔
> 2. **watches_gifts**（手表礼品）—— 约 1,205,006 雷亚尔
> 3. **bed_bath_table**（床品浴巾餐桌）—— 约 1,036,989 雷亚尔
> 
> 口径说明：销售额 = order_items 中各商品 price 之和（不含运费），通过 product_id 关联 products 得类别，再经 category_translation 映射为英文名。若把运费也计入（price + freight_value），前三名类别及排序保持不变。
> 
> 图表展示了这三个类别的销售额对比柱状图，并在每根柱子上标注了具体金额，可直观看出 health_beauty 领先，watches_gifts 紧随其后。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：前 3 类别及顺序与 gold 一致）

## react · m08   [multi / 跨表排序]

**Q**：订单数最多的 5 个城市（按客户所在城市）是哪些？

- gold(list)：`list[5] sao paulo, rio de janeiro, belo horizonte, brasilia, curitiba`
- alt：无
- note：orders ⋈ customers，按 customer_city 数订单排前 5
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=1  duration=14.74s  tokens=18278

**模型代码**
```python
import matplotlib.pyplot as plt
o = dfs['orders']; c = dfs['customers']
m = o.merge(c[['customer_id','customer_city']], on='customer_id', how='left')
s = m['customer_city'].value_counts().head(5).sort_values()
ax = s.plot(kind='barh', color='#4C72B0')
for i,(lab,y) in enumerate(zip(s.index, s.values)):
    ax.text(y+150, i, f'{y:,}', va='center')
ax.set_title('订单数最多的5个城市（按客户所在城市）')
ax.set_xlabel('订单数')
ax.set_ylabel('城市')
plt.tight_layout()
plt.savefig(chart_path)
result = m['customer_city'].value_counts().head(5)
print(result)
```
**代码输出 result_text**：`[序列，5 项]
customer_city
sao paulo         15540
rio de janeiro     6882
belo horizonte     2773
brasilia           2131
curitiba           1521`

**模型结论 answer**：

> 订单数最多的 5 个城市（按客户所在城市统计，含全部状态订单）：
> 
> | 排名 | 城市 | 订单数 |
> |---|---|---|
> | 1 | sao paulo | 15,540 |
> | 2 | rio de janeiro | 6,882 |
> | 3 | belo horizonte | 2,773 |
> | 4 | brasilia | 2,131 |
> | 5 | curitiba | 1,521 |
> 
> 结论：圣保罗（sao paulo）以 15,540 单遥遥领先，约为第二名里约热内卢（6,882 单）的 2.3 倍；前两名合计约 22,422 单，占全部 99,441 单的 22.6%，订单高度集中在东南地区大城市。
> 
> 图表以横向柱状图展示了这 5 个城市的订单量对比，并在每根柱上标注了具体数值，可直观看出圣保罗的领先幅度。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：前 5 城市及顺序与 gold 一致；比较器漏判（DataFrame 形态））

## react · m09   [multi / 拒答]  ★ answer 空 / 拒答题

**Q**：各个年龄段的客户分别贡献了多少销售额？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有年龄字段
- 状态：executed=True  error_kind=agent  error=ReAct 超过步数上限（recursion_limit=25）仍未给出结论
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=37.99s  tokens=63817

**模型代码**
```python
import pandas as pd
oi = dfs['order_items']
oi['shipping_limit_date'] = pd.to_datetime(oi['shipping_limit_date'])
print(oi['shipping_limit_date'].min(), oi['shipping_limit_date'].max())
o = dfs['orders']
s = pd.to_datetime(o['order_purchase_timestamp'], errors='coerce')
print(s.min(), s.max())
print(s.dt.year.value_counts().sort_index())
result='ok'
```
**代码输出 result_text**：`ok`

**模型结论 answer**：

> (空)

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：应拒答（无年龄字段）却返回占位 'ok'，且 error_kind=agent）

## react · m10   [multi / 拒答]  ★ 拒答题

**Q**：各商品类别的利润分别是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有成本字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=1  duration=35.02s  tokens=32297

**模型代码**
```python

oi = dfs['order_items']; p = dfs['products']; ct = dfs['category_translation']
m = oi.merge(p[['product_id','product_category_name']], on='product_id', how='left').merge(ct, on='product_category_name', how='left')
m['cat'] = m['product_category_name_english'].fillna(m['product_category_name'])
m['profit'] = m['price'] - m['freight_value']
g = m.groupby('cat')['profit'].sum().sort_values(ascending=False)
print('总利润', round(g.sum(),2), '类别数', len(g), '明细行数', len(m))
print(g.tail(8).round(2))
result = g.round(2)
```
**代码输出 result_text**：`[序列，73 项]（共 73 行，此处仅显示前 50 行和后 10 行）
cat
watches_gifts                              1104469.75
health_beauty                              1075932.99
bed_bath_table                              832295.64
sports_leisure                              817774.74
computers_accessories                       764636.24
furniture_decor                             556279.20
cool_stuff                                  551251.75
auto                                        499950.78
housewares                                  485178.51
toys                                        405735.18
garden_tools       `

**模型结论 answer**：

> ## 结论
> 
> **口径说明**：数据中没有采购成本/进价字段，因此这里把「利润」定义为 **商品售价（order_items.price）− 运费支出（freight_value）**，按 product_id → products.product_category_name → 英文类别名汇总（112,650 条订单明细全部匹配到类别，共 73 个类别，总利润约 **17,058,125.91 雷亚尔**）。
> 
> **各商品类别利润（Top 15，单位：雷亚尔）**
> 
> | 排名 | 类别 | 利润 |
> |---|---|---|
> | 1 | watches_gifts（手表/礼品） | 1,104,469.75 |
> | 2 | health_beauty（健康美容） | 1,075,932.99 |
> | 3 | bed_bath_table（床品浴巾餐桌） | 832,295.64 |
> | 4 | sports_leisure（运动休闲） | 817,774.74 |
> | 5 | computers_accessories（电脑配件） | 764,636.24 |
> | 6 | furniture_decor（家具装饰） | 556,279.20 |
> | 7 | cool_stuff | 551,251.75 |
> | 8 | auto（汽车用品） | 499,950.78 |
> | 9 | housewares（厨具家居） | 485,178.51 |
> | 10 | toys（玩具） | 405,735.18 |
> | 11 | garden_tools（园艺工具） | 386,085.28 |
> | 12 | perfumery（香水） | 344,911.03 |
> | 13 | baby（母婴） | 343,411.78 |
> | 14 | telephony（手机通讯） | 252,451.74 |
> | 15 | computers（电脑） | 213,126.83 |
> 
> - 头部集中明显：前 5 个类别合计约 459 万，占全部利润的 **27%** 左右。
> - 长尾类别利润很低（如 security、flowers、no_category_found 等仅数百到数千元），完整 73 个类别的利润值已在返回的 Series 中按降序给出。
> 
> **图表**：横向柱状图展示了利润最高的 15 个商品类别及其利润金额（每根柱上标注了具体数值），可直观看出「手表/礼品」「健康美容」两类明显领先，第 6 名之后出现断层式下降。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [ x ]
　　　reason：（AI 预标注：应拒答（无成本字段）却把'利润'自行定义为 售价−运费 后给出 73 类别结果）


---

# agent = workflow   （gate_20261012_104936_workflow.json）

meta：model=Qwen3.5-397B-A17B  temperature=0.0  git_sha=ebc4e7b?  questions_sha256=75a559642e4e

## workflow · s01   [single / 聚合]

**Q**：2011 年全年的销售额是多少英镑？销售额按数量乘以单价算。


- gold(scalar)：`8998790.91`
- alt(scalar)：`9820814.28`  — 去掉取消单（发票号以 C 开头）
- note：净额：所有行数量×单价求和（取消单为负数，自然冲减）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=17.62s  tokens=2265

**模型代码**
```python
# 1. 数据清洗与类型转换
# 将开票时间转换为 datetime 格式
df['开票时间'] = pd.to_datetime(df['开票时间'], errors='coerce')

# 确保数量和单价为数值类型，并处理可能的缺失值或非数值字符
df['数量'] = pd.to_numeric(df['数量'], errors='coerce')
df['单价（英镑）'] = pd.to_numeric(df['单价（英镑）'], errors='coerce')

# 剔除关键字段缺失的行
df_clean = df.dropna(subset=['开票时间', '数量', '单价（英镑）'])

# 2. 时间范围筛选
# 筛选出 2011 年的数据
mask_2011 = (df_clean['开票时间'].dt.year == 2011)
df_2011 = df_clean[mask_2011]

# 3. 计算单行销售额
# 计算每行的销售额：数量 * 单价
df_2011['销售额'] = df_2011['数量'] * df_2011['单价（英镑）']

# 4. 汇总求和
# 计算 2011 年全年的总销售额
total_sales_2011 = df_2011['销售额'].sum()

# 赋值给 result
result = total_sales_2011
```
**代码输出 result_text**：`8998790.914`

**模型结论 answer**：

> 2011 年全年的销售额为 8,998,790.91 英镑。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：8998790.914 四舍五入为 8998790.91，与 gold 一致）

## workflow · s02   [single / 聚合]

**Q**：一共有多少个不同的客户？

- gold(scalar)：`4372`
- alt：无
- note：去重客户编号，不含缺失（脏表里缺失写成'未登记'，不能算一个客户）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=11.79s  tokens=1688

**模型代码**
```python
result = df['客户编号'].nunique()
```
**代码输出 result_text**：`4373`

**模型结论 answer**：

> 一共有 4373 个不同的客户。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：答 4373，把'未登记'当成一个客户（同 react s02））

## workflow · s03   [single / 聚合]

**Q**：平均每张发票的金额是多少英镑？

- gold(scalar)：`376.36`
- alt(scalar)：`482.44`  — 只算未取消的发票
- note：每张发票金额求和后取平均，含取消发票（金额为负）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=7.86s  tokens=1857

**模型代码**
```python
df['行金额'] = df['数量'] * df['单价（英镑）']
invoice_totals = df.groupby('发票号')['行金额'].sum()
result = round(invoice_totals.mean(), 2)
```
**代码输出 result_text**：`376.36`

**模型结论 answer**：

> 平均每张发票的金额是 376.36 英镑。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：376.36 与 gold 一致）

## workflow · s04   [single / 聚合]

**Q**：英国以外的国家一共卖出了多少件商品？

- gold(scalar)：`912621`
- alt(scalar)：`927162`  — 去掉取消单
- note：净数量；报表变体末尾有'合计'行（国家为空），按'国家≠英国'过滤会把合计行算进去
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=10.36s  tokens=2145

**模型代码**
```python
# 1. 数据清洗与标准化
# 处理国家列 (Unnamed: 7)，去除首尾空格
df['国家_clean'] = df['Unnamed: 7'].astype(str).str.strip()

# 处理数量列 (Unnamed: 3)，转换为数值类型，无法转换的设为 NaN
df['数量_clean'] = pd.to_numeric(df['Unnamed: 3'], errors='coerce')

# 2. 筛选非英国数据
# 定义英国的常见变体，确保准确排除
uk_variants = ['United Kingdom', 'UK', 'England', 'Great Britain', 'GB']
# 创建掩码：国家不在英国变体列表中，且数量有效
mask_non_uk = ~df['国家_clean'].isin(uk_variants) & df['数量_clean'].notna()

# 3. 汇总计算
# 对筛选出的记录进行数量求和
total_quantity_non_uk = df.loc[mask_non_uk, '数量_clean'].sum()

# 5. 输出结果
result = total_quantity_non_uk
```
**代码输出 result_text**：`6089071.0`

**模型结论 answer**：

> 英国以外的国家一共卖出了 6,089,071 件商品。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：答 6089071 = 非英国净数量 912,621 + 合计行总数 5,176,450，确切地把'合计'行当成了数据行）

## workflow · s05   [single / 过滤]

**Q**：有多少张被取消的发票？

- gold(scalar)：`3836`
- alt：无
- note：发票号以 C 开头的去重发票数（数据集说明的定义）；数量为负但非 C 开头的是库存调整，不是取消
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=14.03s  tokens=2029

**模型代码**
```python
# 1. 识别取消标识：筛选发票号以 'C' 开头的记录
# 使用 str.startswith 进行匹配，注意处理可能的前后空格
cancelled_mask = df['发票号'].str.strip().str.startswith('C')

# 2. 数据清洗与筛选：获取所有被取消的发票记录
cancelled_invoices_df = df[cancelled_mask]

# 3. 去重统计：获取唯一的取消发票号
unique_cancelled_invoices = cancelled_invoices_df['发票号'].str.strip().unique()

# 4. 计算总数：统计去重后的唯一取消发票号数量
result = len(unique_cancelled_invoices)

# 5. 验证与输出：打印结果以便确认
print(f"被取消的发票总张数: {result}")
```
**代码输出 result_text**：`3836`

**模型结论 answer**：

> 共有3836张被取消的发票。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：3836 与 gold 一致）

## workflow · s06   [single / 过滤]

**Q**：单价超过 100 英镑的记录有多少条？

- gold(scalar)：`1036`
- alt：无
- note：单价 > 100 的行数（含邮费/手工调整等特殊行）；报表变体有两行表头
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=14.75s  tokens=2375

**模型代码**
```python
# 1. 数据清洗与列重命名
# 原始数据第一行是真正的列名，需要将其提升为列名
# 当前 df 的列名是 '订单信息', '商品信息', ... 等，而第一行数据是 '发票号', '商品编码', ...
# 我们需要将第一行数据作为新的列名，并删除这一行

# 获取第一行数据作为新列名
new_columns = df.iloc[0].tolist()

# 创建新的 DataFrame，使用第一行作为列名，并删除第一行
df_clean = df.iloc[1:].copy()
df_clean.columns = new_columns

# 重置索引
df_clean.reset_index(drop=True, inplace=True)

# 确保 '单价（英镑）' 列为数值类型
# 注意：列名中可能包含空格或特殊字符，需仔细匹配
# 根据示例，列名应为 '单价（英镑）'
if '单价（英镑）' in df_clean.columns:
    df_clean['单价（英镑）'] = pd.to_numeric(df_clean['单价（英镑）'], errors='coerce')
else:
    # 尝试查找包含 '单价' 的列
    price_col = [col for col in df_clean.columns if '单价' in col]
    if price_col:
        df_clean[price_col[0]] = pd.to_numeric(df_clean[price_col[0]], errors='coerce')
        price_col_name = price_col[0]
    else:
        result = '无法回答：数据中没有单价字段'
        # 如果无法找到单价列，直接返回结果并结束
        # 但为了代码完整性，我们假设找到了或者处理了错误
        # 这里如果没找到，后续代码会报错，所以最好提前退出或处理
        # 由于题目要求只输出代码，且假设数据可用，我们假设列名正确
        pass

# 2. 数据过滤
# 筛选单价严格大于 100 的记录
# 确定单价列名
price_col_name = '单价（英镑）'
if price_col_name not in df_clean.columns:
    # 再次尝试模糊匹配
    potential_cols = [c for c in df_clean.columns if '单价' in str(c)]
    if potential_cols:
        price_col_name = potential_cols[0]
    else:
        result = '无法回答：数据中没有单价字段'
        # 如果这里还没找到，直接赋值 result 并跳过后续计算
        # 但为了保持代码流，我们假设找到了
        pass

# 过滤
filtered_df = df_clean[df_clean[price_col_name] > 100]

# 3. 计数统计
count = len(filtered_df)

# 4. 结果输出
result = count
```
**代码输出 result_text**：`1036`

**模型结论 answer**：

> 单价超过 100 英镑的记录有 1036 条。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：1036 与 gold 一致）

## workflow · s07   [single / 过滤]

**Q**：2011 年 12 月有哪些国家下过单？

- gold(list)：`list[21] Austria, Belgium, Channel Islands, Cyprus, Denmark, EIRE, Finland, France…`
- alt(list)：`list[18] Austria, Belgium, Channel Islands, Denmark, EIRE, Finland, France, Germany…`  — 不算只有取消单的国家
- note：2011-12 出现过的国家（集合，不要求顺序）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=15.43s  tokens=2052

**模型代码**
```python
df['开票时间'] = pd.to_datetime(df['开票时间'])
mask = (df['开票时间'].dt.year == 2011) & (df['开票时间'].dt.month == 12)
filtered_df = df[mask]
result = filtered_df['国家'].unique()
```
**代码输出 result_text**：`<ArrowStringArray>
[ 'United Kingdom',         'Germany',            'EIRE',           'Malta',
          'France',         'Finland',         'Belgium',        'Portugal',
             'USA',          'Cyprus', 'Channel Islands',          'Norway',
          'Sweden',         'Denmark',           'Italy',          'Greece',
           'Japan',           'Spain',     'Netherlands',         'Iceland',
         'Austria']
Length: 21, dtype: str`

**模型结论 answer**：

> 2011年12月下单的国家共有21个，分别是：英国、德国、爱尔兰、马耳他、法国、芬兰、比利时、葡萄牙、美国、塞浦路斯、海峡群岛、挪威、瑞典、丹麦、意大利、希腊、日本、西班牙、荷兰、冰岛和奥地利。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：21 国集合与 gold 一致（返回中文国名）；比较器漏判）

## workflow · s08   [single / 排序]

**Q**：销售额最高的前 5 个国家是哪些？

- gold(list)：`list[5] United Kingdom, Netherlands, EIRE, Germany, France`
- alt：无
- note：按净销售额排前 5；去掉取消单时前 5 及顺序相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=11.39s  tokens=2107

**模型代码**
```python
df['销售额'] = df['数量'] * df['单价（英镑）']
country_sales = df.groupby('国家')['销售额'].sum().sort_values(ascending=False)
result = country_sales.head(5)

# 绘图
ax = result.plot(kind='bar', figsize=(10, 6), color='skyblue')
ax.set_title('销售额最高的前5个国家')
ax.set_xlabel('国家')
ax.set_ylabel('总销售额（英镑）')
ax.set_xticklabels(ax.get_xticklabels(), rotation=0)

# 添加数值标注
for i, (country, sales) in enumerate(result.items()):
    ax.text(i, sales, f'{sales:,.2f}', ha='center', va='bottom')

plt.tight_layout()
plt.savefig('chart.png')
```
**代码输出 result_text**：`[序列，5 项]
国家
United Kingdom    8187806.364
Netherlands        284661.540
EIRE               263276.820
Germany            221698.210
France             197403.900`

**模型结论 answer**：

> 销售额最高的前 5 个国家依次为：
> 
> 1. **United Kingdom**（约 818.8 万）
> 2. **Netherlands**（约 28.5 万）
> 3. **EIRE**（约 26.3 万）
> 4. **Germany**（约 22.2 万）
> 5. **France**（约 19.7 万）

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：前 5 国家及顺序与 gold 一致；比较器漏判）

## workflow · s09   [single / 排序]

**Q**：实际卖出数量最多的商品是哪个？

- gold(label)：`WORLD WAR 2 GLIDERS ASSTD DESIGNS`
- alt(label)：`22197`  — 按商品编码汇总（同一编码有多个描述）
- alt(label)：`POPCORN HOLDER`  — 按商品编码汇总后报该编码的描述
- alt(label)：`SMALL POPCORN HOLDER`  — 按商品编码汇总后报该编码的描述
- note：净数量（取消单冲减）。陷阱：'PAPER CRAFT , LITTLE BIRDIE' 有 80995 件的单子被整单取消，只看正数量会错选它
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=11.16s  tokens=2072

**模型代码**
```python
df_clean = df[df['数量'] > 0].copy()
df_clean['商品描述'] = df_clean['商品描述'].str.strip()
df_clean = df_clean.dropna(subset=['商品描述'])

sales_by_product = df_clean.groupby('商品描述')['数量'].sum().sort_values(ascending=False)

result = sales_by_product.index[0]

top_10 = sales_by_product.head(10)
ax = top_10.plot(kind='bar', figsize=(12, 6), color='skyblue')
ax.set_title('实际卖出数量最多的前10个商品', fontsize=14)
ax.set_xlabel('商品描述', fontsize=12)
ax.set_ylabel('总销售数量', fontsize=12)
ax.tick_params(axis='x', rotation=45)

for i, (label, value) in enumerate(top_10.items()):
    ax.text(i, value, str(int(value)), ha='center', va='bottom', fontsize=9)

plt.tight_layout()
plt.savefig('chart.png')
```
**代码输出 result_text**：`PAPER CRAFT , LITTLE BIRDIE`

**模型结论 answer**：

> 实际卖出数量最多的商品是 **PAPER CRAFT , LITTLE BIRDIE**。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：答 PAPER CRAFT , LITTLE BIRDIE——该商品 80,995 件的单子被整单取消，未按净数量冲减）


## workflow · s10   [single / 时间]

**Q**：哪个月的销售额最高？

- gold(label)：`2011-11`
- alt：无
- note：按月净销售额最高的月份；去掉取消单结果相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=1  duration=19.81s  tokens=3989

**模型代码**
```python
df.columns = df.iloc[0]
df = df.iloc[1:].reset_index(drop=True)

df['数量'] = pd.to_numeric(df['数量'], errors='coerce')
df['单价（英镑）'] = pd.to_numeric(df['单价（英镑）'], errors='coerce')
df['开票时间'] = pd.to_datetime(df['开票时间'], errors='coerce')

df['销售额'] = df['数量'] * df['单价（英镑）']

df['月份'] = df['开票时间'].dt.to_period('M')

monthly_sales = df.groupby('月份')['销售额'].sum()

best_month = monthly_sales.idxmax()
result = str(best_month)

ax = monthly_sales.plot(kind='bar', figsize=(10, 6))
ax.set_title('各月销售额分布')
ax.set_xlabel('月份')
ax.set_ylabel('销售额（英镑）')
ax.set_xticklabels([str(p) for p in monthly_sales.index], rotation=45, ha='right')

for i, (lab, y) in enumerate(monthly_sales.items()):
    ax.text(i, y, f'{y:,.0f}', ha='center', va='bottom', fontsize=8)

plt.tight_layout()
plt.savefig('chart.png')
```
**代码输出 result_text**：`2011-11`

**模型结论 answer**：

> 2011年11月的销售额最高。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：2011-11 与 gold 一致）

## workflow · s11   [single / 时间]

**Q**：2011 年每个季度的销售额分别是多少？

- gold(series)：`None`
- alt(series)：`None`  — 去掉取消单
- note：2011 年 Q1–Q4 净销售额
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=11.84s  tokens=2346

**模型代码**
```python
df['开票时间'] = pd.to_datetime(df['开票时间'])
df['数量'] = pd.to_numeric(df['数量'], errors='coerce')
df['单价（英镑）'] = pd.to_numeric(df['单价（英镑）'], errors='coerce')
df['销售额'] = df['数量'] * df['单价（英镑）']

df_2011 = df[df['开票时间'].dt.year == 2011]
df_2011['季度'] = df_2011['开票时间'].dt.quarter

result = df_2011.groupby('季度')['销售额'].sum()

# 绘图
ax = result.plot(kind='bar', color='skyblue')
ax.set_title('2011年各季度销售额')
ax.set_xlabel('季度')
ax.set_ylabel('销售额（英镑）')
ax.set_xticklabels([f'Q{int(x)}' for x in result.index], rotation=0)

for i, (q, val) in enumerate(result.items()):
    ax.text(i, val, f'{val:,.2f}', ha='center', va='bottom')

plt.tight_layout()
plt.savefig('chart.png')
```
**代码输出 result_text**：`[序列，4 项]
季度
1    1741329.990
2    1907663.751
3    2383668.243
4    2966128.930`

**模型结论 answer**：

> 2011 年各季度销售额如下：
> 
> *   **第一季度**：1,741,329.99
> *   **第二季度**：1,907,663.75
> *   **第三季度**：2,383,668.24
> *   **第四季度**：2,966,128.93

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：Q1–Q4 四个值与 gold 一致）

## workflow · s12   [single / 占比]

**Q**：没有客户编号的记录占全部记录的百分之几？

- gold(scalar)：`24.93`
- alt：无
- note：缺失客户编号行数 / 总行数 × 100
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=11.98s  tokens=2266

**模型代码**
```python
# 1. 确认“客户编号”列存在，并检查缺失值表现形式
# 通常缺失值表现为 NaN 或空字符串。这里我们统一处理：将空字符串也视为缺失。
# 为了准确统计，先创建一个布尔掩码，标记哪些行是“没有客户编号”的
# 条件：客户编号为 NaN 或者 客户编号为 空字符串（strip后为空）
mask_no_customer = df['客户编号'].isna() | (df['客户编号'].astype(str).str.strip() == '')

# 2. 统计没有客户编号的记录数
count_no_customer = mask_no_customer.sum()

# 3. 获取总记录数
total_records = len(df)

# 4. 计算百分比
percentage_no_customer = (count_no_customer / total_records) * 100

# 将最终答案赋值给 result
# 问题问的是“百分之几”，即一个数值
result = percentage_no_customer

# 绘图：虽然问题只问百分比，但为了汇报直观，可以画一个简单的饼图展示有/无客户编号的占比
# 准备绘图数据
labels = ['有客户编号', '无客户编号']
counts = [total_records - count_no_customer, count_no_customer]

# 创建饼图
fig, ax = plt.subplots(figsize=(8, 6))
# 使用 autopct 显示百分比，startangle 调整起始角度
wedges, texts, autotexts = ax.pie(counts, labels=labels, autopct='%1.2f%%', startangle=140, colors=['#66b3ff', '#ff9999'])

# 设置标题
ax.set_title('客户编号缺失情况占比')

# 添加数值标注（虽然饼图自带百分比，但为了清晰，可以在图例或外部添加具体数量，这里保持简洁，饼图已含百分比）
# 如果需要更详细的标注，可以在每个扇区旁边加文字，但饼图通常 autopct 足够。
# 为了符合“关键数据点加数值标注”的要求，且饼图已有百分比，这里不再额外添加冗余文字，除非需要显示绝对数量。
# 这里我们确保图表清晰即可。

# 保存图表
chart_path = 'customer_id_missing_percentage.png'
plt.savefig(chart_path)
plt.close()
```
**代码输出 result_text**：`0.0`

**模型结论 answer**：

> 没有客户编号的记录占全部记录的 **0.0%**。

**待填**：human_correct [  对 / x错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：答 0.0%：未识别'未登记'为缺失（与 react s12 相反））

## workflow · s13   [single / 占比]  ★ 比较器放宽口径判对

**Q**：英国的销售额占总销售额的比例是多少？

- gold(scalar)：`84.0`
- alt(scalar)：`84.58`  — 去掉取消单
- note：英国净销售额 / 全部净销售额 × 100
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=relaxed   ← 参考，不是判据
- 成本：attempts=0  duration=8.73s  tokens=1893

**模型代码**
```python
df['销售额'] = df['数量'] * df['单价（英镑）']
total_sales = df['销售额'].sum()
uk_sales = df[df['国家'] == 'United Kingdom']['销售额'].sum()
ratio = uk_sales / total_sales
result = f"{ratio * 100:.2f}%"
```
**代码输出 result_text**：`84.00%`

**模型结论 answer**：

> 英国的销售额占总销售额的比例为84.00%。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：84.00% 与 gold 一致）

## workflow · s14   [single / 拒答]  ★ 拒答题

**Q**：整体毛利率是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有成本/进价字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=refusal   ← 参考，不是判据
- 成本：attempts=0  duration=10.84s  tokens=1780

**模型代码**
```python
result = '无法回答：数据中没有成本字段'
```
**代码输出 result_text**：`无法回答：数据中没有成本字段`

**模型结论 answer**：

> 无法回答，因为数据中缺少成本字段。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：正确拒答（无成本字段））

## workflow · s15   [single / 拒答]  ★ 拒答题

**Q**：女性客户的消费总额是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有性别字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=refusal   ← 参考，不是判据
- 成本：attempts=0  duration=6.85s  tokens=1633

**模型代码**
```python
result = '无法回答：数据中没有性别字段'
```
**代码输出 result_text**：`无法回答：数据中没有性别字段`

**模型结论 answer**：

> 无法回答：数据中没有性别字段

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：正确拒答（无性别字段））

## workflow · m01   [multi / join聚合]

**Q**：各个州（按客户所在州）的订单数分别是多少？

- gold(series)：`None`
- alt：无
- note：orders ⋈ customers（customer_id），按 customer_state 数订单
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=20.58s  tokens=8312

**模型代码**
```python
# 1. 从 orders 表中提取 customer_id
orders_df = dfs['orders'][['customer_id']]

# 2. 从 customers 表中提取 customer_id 和 customer_state
customers_df = dfs['customers'][['customer_id', 'customer_state']]

# 3. 合并数据，使每条订单关联上客户所在州
merged_df = pd.merge(orders_df, customers_df, on='customer_id', how='left')

# 4. 按 customer_state 分组并统计订单数量
state_order_counts = merged_df.groupby('customer_state')['customer_id'].count()

# 5. 整理结果，赋值给 result
result = state_order_counts

# 绘图：各州订单数柱状图
# 为了图表清晰，如果州太多，可以只展示前10或全部，这里假设展示全部或主要州
# 由于州数量可能较多，直接绘制所有州可能会拥挤，但题目要求“各个州”，故绘制所有
# 如果州数量过多，通常PPT会取Top N，但这里严格按“各个州”回答，绘图时若太密可考虑旋转标签
ax = result.plot(kind='bar', figsize=(12, 6), color='skyblue')
ax.set_title('各州订单数量分布', fontsize=14)
ax.set_xlabel('客户所在州', fontsize=12)
ax.set_ylabel('订单数量', fontsize=12)
ax.tick_params(axis='x', rotation=45)

# 添加数值标注
for i, (state, count) in enumerate(result.items()):
    ax.text(i, count, str(count), ha='center', va='bottom', fontsize=8)

plt.tight_layout()
plt.savefig(chart_path)
plt.show()
```
**代码输出 result_text**：`[序列，27 项]
customer_state
AC       81
AL      413
AM      148
AP       68
BA     3380
CE     1336
DF     2140
ES     2033
GO     2020
MA      747
MG    11635
MS      715
MT      907
PA      975
PB      536
PE     1652
PI      495
PR     5045
RJ    12852
RN      485
RO      253
RR       46
RS     5466
SC     3637
SE      350
SP    41746
TO      280`

**模型结论 answer**：

> 各州订单数统计如下（按订单量从高到低排列）：
> 
> *   **SP** (圣保罗州): 41,746
> *   **RJ** (里约热内卢州): 12,852
> *   **MG** (米纳斯吉拉斯州): 11,635
> *   **RS** (南里奥格兰德州): 5,466
> *   **PR** (巴拉那州): 5,045
> *   **SC** (圣卡塔琳娜州): 3,637
> *   **BA** (巴伊亚州): 3,380
> *   **DF** (联邦区): 2,140
> *   **ES** (圣埃斯皮里图州): 2,033
> *   **GO** (戈亚斯州): 2,020
> *   **PE** (伯南布哥州): 1,652
> *   **CE** (塞阿拉州): 1,336
> *   **PA** (帕拉州): 975
> *   **MT** (马托格罗索州): 907
> *   **MA** (马拉尼昂州): 747
> *   **MS** (南马托格罗索州): 715
> *   **AL** (阿拉戈斯州): 413
> *   **PI** (皮奥伊州): 495
> *   **RN** (北里奥格兰德州): 485
> *   **PB** (帕拉伊巴州): 536
> *   **SE** (塞尔希培州): 350
> *   **TO** (托坎廷斯州): 280
> *   **RO** (朗多尼亚州): 253
> *   **AM** (亚马逊州): 148
> *   **AP** (阿马帕州): 68
> *   **AC** (阿克里州): 81
> *   **RR** (罗赖马州): 46
> 
> **结论：**
> 圣保罗州（SP）订单量遥遥领先，占总订单量的绝大部分；其次是里约热内卢州（RJ）和米纳斯吉拉斯州（MG）。这三个州构成了主要的订单来源地。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：27 州订单数与 gold 一致）

## workflow · m02   [multi / join聚合]

**Q**：SP 州的客户一共付了多少钱？

- gold(scalar)：`5998226.96`
- alt(scalar)：`5923688.9`  — 用 order_items 的商品价+运费代替实付
- note：payments ⋈ orders ⋈ customers，SP 州 payment_value 合计（所有订单状态）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=9.84s  tokens=7370

**模型代码**
```python
# 1. 从 customers 表中筛选出 SP 州的客户 ID
sp_customers = dfs['customers'][dfs['customers']['customer_state'] == 'SP']
sp_customer_ids = sp_customers['customer_id'].unique()

# 2. 在 orders 表中找出这些客户产生的订单 ID
sp_orders = dfs['orders'][dfs['orders']['customer_id'].isin(sp_customer_ids)]
sp_order_ids = sp_orders['order_id'].unique()

# 3. 在 order_payments 表中找出这些订单对应的支付记录
sp_payments = dfs['order_payments'][dfs['order_payments']['order_id'].isin(sp_order_ids)]

# 4. 对 payment_value 求和
total_payment = sp_payments['payment_value'].sum()

# 5. 赋值给 result
result = total_payment
```
**代码输出 result_text**：`5998226.96`

**模型结论 answer**：

> SP 州的客户一共付了 5,998,226.96 元。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：5998226.96 与 gold 一致）

## workflow · m03   [multi / join聚合]  ★ 比较器放宽口径判对

**Q**：按卖家所在州统计，各州卖出商品的平均单价是多少？

- gold(series)：`None`
- alt：无
- note：order_items ⋈ sellers（seller_id），按 seller_state 求 price 均值（每个订单行算一次）
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=relaxed   ← 参考，不是判据
- 成本：attempts=0  duration=18.71s  tokens=8391

**模型代码**
```python
# 1. 关联订单明细与卖家信息
merged = dfs['order_items'].merge(dfs['sellers'], on='seller_id', how='left')

# 2. 筛选有效数据：剔除 seller_state 为空的记录
merged = merged.dropna(subset=['seller_state'])

# 3. 按州分组并计算平均单价
avg_price_by_state = merged.groupby('seller_state')['price'].mean()

# 4. 整理结果：按平均单价降序排列，重置索引
result = avg_price_by_state.sort_values(ascending=False).reset_index()
result.columns = ['seller_state', 'avg_price']

# 绘图：柱状图展示各州平均单价
top_n = 15  # 展示前15个州，避免图表过于拥挤
top_states = result.head(top_n)

fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.bar(top_states['seller_state'], top_states['avg_price'], color='steelblue')

# 添加数值标注
for bar, val in zip(bars, top_states['avg_price']):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
            f'{val:.2f}', ha='center', va='bottom', fontsize=9)

ax.set_title('各州卖出商品的平均单价（Top 15）', fontsize=14)
ax.set_xlabel('卖家所在州', fontsize=12)
ax.set_ylabel('平均单价（R$）', fontsize=12)
ax.tick_params(axis='x', rotation=45)
plt.tight_layout()
plt.savefig(chart_path)
plt.show()
```
**代码输出 result_text**：`[表格，23 行 × 2 列]
   seller_state   avg_price
0            PB  449.868421
1            BA  444.108180
2            AM  392.333333
3            RO  340.157143
4            AC  267.000000
5            CE  215.325957
6            PI  210.166667
7            PE  204.227344
8            RN  178.439286
9            RJ  175.173147
10           RS  172.150769
11           MS  171.033800
12           SE  160.620000
13           SC  155.196582
14           PA  154.750000
15           PR  145.529606
16           ES  128.197876
17           GO  127.690788
18           MT  117.729103
19           MG  114.598`


**模型结论 answer**：

> 按卖家所在州统计，各州卖出商品的平均单价如下（按单价从高到低排序）：
> 
> *   **PB**: 449.87
> *   **BA**: 444.11
> *   **AM**: 392.33
> *   **RO**: 340.16
> *   **AC**: 267.00
> *   **CE**: 215.33
> *   **PI**: 210.17
> *   **PE**: 204.23
> *   **RN**: 178.44
> *   **RJ**: 175.17
> *   **RS**: 172.15
> *   **MS**: 171.03
> *   **SE**: 160.62
> *   **SC**: 155.20
> *   **PA**: 154.75
> *   **PR**: 145.53
> *   **ES**: 128.20
> *   **GO**: 127.69
> *   **MT**: 117.73
> *   **MG**: 114.60
> *   **SP**: 108.95
> *   **DF**: 108.73
> *   **MA**: 89.90
> 
> **结论：**
> 平均单价最高的州是 **PB**（约 449.87），最低的是 **MA**（约 89.90）。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：23 州平均单价与 gold 一致）

## workflow · m04   [multi / join聚合]  ★ 比较器放宽口径判对

**Q**：给了 1 星评价的订单，从下单到送达平均用了多少天？

- gold(scalar)：`21.31`
- alt(scalar)：`20.85`  — 按整天数（.dt.days）算
- note：reviews(score=1) ⋈ orders，送达时间 - 下单时间，未送达的不计；按订单去重
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=alt:rounded   ← 参考，不是判据
- 成本：attempts=0  duration=12.82s  tokens=7669

**模型代码**
```python
# 1. 筛选低分订单
one_star_reviews = dfs['order_reviews'][dfs['order_reviews']['review_score'] == 1]
one_star_order_ids = one_star_reviews['order_id'].unique()

# 2. 关联订单时间信息
# 从 orders 表中筛选出对应的订单
relevant_orders = dfs['orders'][dfs['orders']['order_id'].isin(one_star_order_ids)]

# 3. 数据清洗与类型转换
# 剔除未送达的订单 (order_delivered_customer_date 为空)
valid_orders = relevant_orders.dropna(subset=['order_delivered_customer_date', 'order_purchase_timestamp'])

# 转换为 datetime 类型
valid_orders['order_purchase_timestamp'] = pd.to_datetime(valid_orders['order_purchase_timestamp'])
valid_orders['order_delivered_customer_date'] = pd.to_datetime(valid_orders['order_delivered_customer_date'])

# 4. 计算单个订单耗时
# 计算时间差并转换为天数
valid_orders['delivery_days'] = (valid_orders['order_delivered_customer_date'] - valid_orders['order_purchase_timestamp']).dt.days

# 5. 计算平均天数
avg_delivery_days = valid_orders['delivery_days'].mean()

# 赋值给 result
result = avg_delivery_days
```
**代码输出 result_text**：`20.845055413469737`

**模型结论 answer**：

> 给了 1 星评价的订单，从下单到送达平均用了约 20.85 天。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：20.85 命中 alt（.dt.days 口径），可接受）

## workflow · m05   [multi / join过滤]

**Q**：买过 health_beauty（健康美容）类商品的客户有多少个？

- gold(scalar)：`8678`
- alt(scalar)：`8836`  — 按 customer_id 数（Olist 每个订单一个 customer_id）
- note：items ⋈ products ⋈ translation ⋈ orders ⋈ customers，去重 customer_unique_id
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=14.95s  tokens=7923

**模型代码**
```python
# 1. 筛选目标商品类别
# 找到 'health_beauty' 对应的葡萄牙语类别名称
target_category_pt = dfs['category_translation'].loc[
    dfs['category_translation']['product_category_name_english'] == 'health_beauty', 
    'product_category_name'
].values

# 在 products 表中筛选出属于该类别的所有 product_id
health_beauty_products = dfs['products'].loc[
    dfs['products']['product_category_name'].isin(target_category_pt), 
    'product_id'
]

# 2. 关联订单明细
# 筛选出包含这些健康美容类商品的订单明细记录
health_beauty_order_items = dfs['order_items'].loc[
    dfs['order_items']['product_id'].isin(health_beauty_products)
]

# 3. 关联订单主表获取客户ID
# 将订单明细与 orders 表通过 order_id 合并，获取 customer_id
merged_orders = health_beauty_order_items.merge(
    dfs['orders'][['order_id', 'customer_id']], 
    on='order_id', 
    how='inner'
)

# 4. 关联客户表获取唯一客户ID
# 将结果与 customers 表通过 customer_id 合并，获取 customer_unique_id
merged_customers = merged_orders.merge(
    dfs['customers'][['customer_id', 'customer_unique_id']], 
    on='customer_id', 
    how='inner'
)

# 5. 统计去重客户数量
# 对 customer_unique_id 进行去重计数
result = merged_customers['customer_unique_id'].nunique()
```
**代码输出 result_text**：`8678`

**模型结论 answer**：

> 买过 health_beauty（健康美容）类商品的客户有 8678 个。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：8678 与 gold 一致）

## workflow · m06   [multi / join过滤]

**Q**：2018 年 8 月下单但最终被取消的订单，一共涉及多少支付金额？

- gold(scalar)：`23921.17`
- alt：无
- note：2018-08 下单、status=canceled 的 84 个订单，payments.payment_value 合计
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=strict   ← 参考，不是判据
- 成本：attempts=0  duration=10.44s  tokens=7493

**模型代码**
```python
import pandas as pd

# 1. 在 orders 表中筛选出 order_status 为 'canceled' 且 order_purchase_timestamp 落在 2018 年 8 月范围内的订单
orders_df = dfs['orders']
orders_df['order_purchase_timestamp'] = pd.to_datetime(orders_df['order_purchase_timestamp'])

# 筛选条件：状态为 canceled，且时间在 2018-08-01 到 2018-08-31 之间
mask = (
    (orders_df['order_status'] == 'canceled') &
    (orders_df['order_purchase_timestamp'] >= '2018-08-01') &
    (orders_df['order_purchase_timestamp'] < '2018-09-01')
)
canceled_orders_2018_08 = orders_df[mask]
canceled_order_ids = canceled_orders_2018_08['order_id'].unique()

# 2. 使用上一步得到的 order_id 列表，在 order_payments 表中筛选出对应的支付记录
payments_df = dfs['order_payments']
relevant_payments = payments_df[payments_df['order_id'].isin(canceled_order_ids)]

# 3. 对筛选出的支付记录中的 payment_value 列进行求和，得到总支付金额
total_payment_value = relevant_payments['payment_value'].sum()

# 4. 输出最终的求和结果作为答案
result = total_payment_value
```
**代码输出 result_text**：`23921.170000000002`

**模型结论 answer**：

> 2018 年 8 月下单但最终被取消的订单，涉及的支付金额共计 23921.17 元。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：23921.17 与 gold 一致）

## workflow · m07   [multi / 跨表排序]  ★ 比较器放宽口径判对

**Q**：销售额最高的 3 个商品类别是什么？用英文类别名。

- gold(list)：`list[3] health_beauty, watches_gifts, bed_bath_table`
- alt：无
- note：按 price 合计排前 3；加上运费时前 3 及顺序相同
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=relaxed   ← 参考，不是判据
- 成本：attempts=0  duration=18.33s  tokens=7972

**模型代码**
```python
# 步骤1: 从 order_items 表中计算每个商品的总销售额
product_sales = dfs['order_items'].groupby('product_id')['price'].sum().reset_index()
product_sales.columns = ['product_id', 'total_sales']

# 步骤2: 与 products 表左连接，获取 product_category_name
product_sales_with_category = product_sales.merge(
    dfs['products'][['product_id', 'product_category_name']],
    on='product_id',
    how='left'
)

# 步骤3: 与 category_translation 表左连接，获取英文类别名
product_sales_with_english_category = product_sales_with_category.merge(
    dfs['category_translation'],
    on='product_category_name',
    how='left'
)

# 步骤4: 按英文类别名分组，求和销售额
category_sales = product_sales_with_english_category.groupby('product_category_name_english')['total_sales'].sum().reset_index()
category_sales.columns = ['category_english', 'total_sales']

# 步骤5: 按总销售额降序排列，取前3行
top3_categories = category_sales.sort_values('total_sales', ascending=False).head(3)

# 提取英文类别名作为最终答案
result = top3_categories['category_english'].tolist()

# 绘图：展示销售额最高的3个商品类别
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(top3_categories['category_english'], top3_categories['total_sales'], color=['#1f77b4', '#ff7f0e', '#2ca02c'])
ax.set_title('销售额最高的3个商品类别', fontsize=14)
ax.set_xlabel('商品类别（英文）', fontsize=12)
ax.set_ylabel('总销售额', fontsize=12)

# 添加数值标注
for bar, value in zip(bars, top3_categories['total_sales']):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f'{value:,.0f}', 
            ha='center', va='bottom', fontsize=10)

plt.tight_layout()
plt.savefig('top3_categories_sales.png')
plt.show()
```
**代码输出 result_text**：`['health_beauty', 'watches_gifts', 'bed_bath_table']`

**模型结论 answer**：

> 销售额最高的 3 个商品类别是：health_beauty, watches_gifts, bed_bath_table。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：前 3 类别与 gold 一致）

## workflow · m08   [multi / 跨表排序]

**Q**：订单数最多的 5 个城市（按客户所在城市）是哪些？

- gold(list)：`list[5] sao paulo, rio de janeiro, belo horizonte, brasilia, curitiba`
- alt：无
- note：orders ⋈ customers，按 customer_city 数订单排前 5
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=False  match=None   ← 参考，不是判据
- 成本：attempts=0  duration=13.21s  tokens=7739

**模型代码**
```python
# 1. 从 orders 表中提取 customer_id
orders_with_customer = dfs['orders'][['order_id', 'customer_id']]

# 2. 与 customers 表通过 customer_id 合并，获取 customer_city
merged = orders_with_customer.merge(dfs['customers'][['customer_id', 'customer_city']], on='customer_id', how='left')

# 3. 按 customer_city 分组，统计订单数量
city_order_counts = merged.groupby('customer_city')['order_id'].count().reset_index()
city_order_counts.columns = ['customer_city', 'order_count']

# 4. 按订单数量降序排列，取前 5
top5_cities = city_order_counts.sort_values('order_count', ascending=False).head(5)

# 赋值给 result：问题问"哪些"，返回筛选出的行（DataFrame）
result = top5_cities

# 绘图：柱状图展示 Top 5 城市订单数
fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(top5_cities['customer_city'], top5_cities['order_count'], color='#4C72B0')
ax.set_title('订单数最多的 5 个城市', fontsize=14)
ax.set_xlabel('城市', fontsize=12)
ax.set_ylabel('订单数量', fontsize=12)

# 在柱子上方标注数值
for bar in bars:
    height = bar.get_height()
    ax.text(bar.get_x() + bar.get_width() / 2., height,
            f'{int(height)}',
            ha='center', va='bottom', fontsize=11)

plt.tight_layout()
plt.savefig(chart_path)
plt.show()
```
**代码输出 result_text**：`[表格，5 行 × 2 列]
       customer_city  order_count
3597       sao paulo        15540
3155  rio de janeiro         6882
453   belo horizonte         2773
558         brasilia         2131
1143        curitiba         1521`

**模型结论 answer**：

> 订单数最多的 5 个城市依次为：
> 
> 1. **Sao Paulo**（15,540 单）
> 2. **Rio de Janeiro**（6,882 单）
> 3. **Belo Horizonte**（2,773 单）
> 4. **Brasilia**（2,131 单）
> 5. **Curitiba**（1,521 单）

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：前 5 城市及顺序与 gold 一致；比较器漏判）

## workflow · m09   [multi / 拒答]  ★ 拒答题

**Q**：各个年龄段的客户分别贡献了多少销售额？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有年龄字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=refusal   ← 参考，不是判据
- 成本：attempts=0  duration=7.88s  tokens=7119

**模型代码**
```python
result = '无法回答：数据中没有客户年龄或出生日期字段'
```
**代码输出 result_text**：`无法回答：数据中没有客户年龄或出生日期字段`

**模型结论 answer**：

> 无法回答：数据中没有客户年龄或出生日期字段。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：正确拒答（无年龄字段））

## workflow · m10   [multi / 拒答]  ★ 拒答题

**Q**：各商品类别的利润分别是多少？

- gold(refusal)：`（应拒答）`
- alt：无
- note：没有成本字段
- 状态：executed=True  error_kind=None  error=None
- 比较器：auto_correct=True  match=refusal   ← 参考，不是判据
- 成本：attempts=0  duration=10.03s  tokens=7672

**模型代码**
```python
result = '无法回答：数据中没有成本字段，无法计算利润'
```
**代码输出 result_text**：`无法回答：数据中没有成本字段，无法计算利润`

**模型结论 answer**：

> 无法回答：数据中缺少成本字段，无法计算利润。

**待填**：human_correct [ x对 /  错 ]　failure_class [ ]　guessing [   ]
　　　reason：（AI 预标注：正确拒答（无成本字段））
