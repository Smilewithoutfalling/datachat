"""跨层共用的文本清洗规则。只有一份：app/server/app.py 与 app/core/errors.py 都从这里 import（T11）。

core 不能反向依赖 server，所以这份字符集放在 core。

charts._CTRL（charts.py:56，`[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]`，不含 C1、不含 bidi）是另一份，**故意不并**：
用途不同。option 里的字符串（轴标签、类目名，_clean_str / _cat）要保真显示；界面文案要防视觉伪装。
并进含 bidi 的集合会改变 chart_fixtures.json 和注入判定表的结论，那是产品行为变更，不属于 T11。
"""
import re

# 方向控制符（LRM/RLM、嵌入 / 覆盖、隔离）：数据里没有合法用途，却能让后面的文本视觉重排（THREAT_MODEL §2.3）
BIDI = "\u200e\u200f\u202a-\u202e\u2066-\u2069"
BIDI_CONTROLS = re.compile(f"[{BIDI}]")
# 标题、note、错误文案：C0/C1 控制字符（保留 \t \n）+ 方向控制符。预览只用 BIDI_CONTROLS（数据里 \r \t \n 合法）
CONTROL_CHARS = re.compile(f"[\x00-\x08\x0b-\x1f\x7f-\x9f{BIDI}]")
