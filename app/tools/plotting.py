
"""统一的绘图样式：解决中文显示，并把图表美化到可直接用于汇报 PPT 的水平。

sandbox 在执行模型生成的绘图代码前会调用 apply_style()，
因此模型只要正常 plt.plot/bar/... 即可，无需自己设字体或风格。
"""
import os

from matplotlib import font_manager, rcParams
import matplotlib.pyplot as plt

# 优先使用的中文字体（Windows 自带微软雅黑；附带 Linux 兜底）
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑 Bold
    "C:/Windows/Fonts/simhei.ttf",   # 黑体
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

# 汇报友好的配色：主蓝 + 青 + 橙 + 红 + 紫 + 绿
PALETTE = ["#1F6FB2", "#159A8C", "#CD7D28", "#C0392B", "#7E57C2", "#3A7D44"]

_DARK = "#2B3A46"
_GRAY = "#66707A"

# 给模型的统一绘图要求：产出可直接放进汇报 PPT 的图。
# 字体与配色已由 apply_style() 全局设好，模型无需再设 rcParams/字体。
CHART_GUIDE = (
    "绘图要求（务必遵守）：\n"
    "- 出图优先用 chart(kind, df, x=列名, y=列名或列名列表, series=分组列, title='中文标题')，它生成可交互图表，不需要 plt.savefig：\n"
    "  kind 可选 'bar'（柱状，对比）/ 'line'（折线，趋势）/ 'area'（面积）/ 'pie'（饼图，占比）/ 'scatter'（散点，x、y 都是数值列）。\n"
    "  df 传算好的汇总表（DataFrame 或 Series；Series 不用给 x，横轴就是索引）。排序、Top-N、分箱都先用 pandas 做好，"
    "chart() 按现有顺序出图，图上的数字全部取自 df；直方图先 pd.cut 分箱计数，再用 'bar'。\n"
    "  多列对比：y=['列1', '列2']；长表分组：series='分组列'（同一个 x 在每组只能有一行，先 groupby 聚合）。\n"
    "  title 写清指标和单位，如 '各地区销售额（元）'。配色、横向、堆叠、数值标签由界面处理，不用设置。\n"
    "  chart() 没有返回值、出错也不会打断代码（原因会在执行结果里告诉你）；每次执行最多 4 张。\n"
    "- 只有上面五种图型表达不了时（如双坐标轴、箱线图、热力图、多子图）才用 plt：中文字体与配色已全局配置好，"
    "不要再设字体或 rcParams；必须有中文标题和坐标轴标签；关键数据点加数值标注（横轴是字符串标签时按位置 0..n-1 标注）；"
    "用 plt.savefig(chart_path) 保存。\n"
    "- 同一张图不要既用 chart() 又用 plt 画。"
)

_FONT_NAME = None


def _setup_font():
    global _FONT_NAME
    if _FONT_NAME:
        rcParams["font.sans-serif"] = [_FONT_NAME, "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False
        return
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)
                _FONT_NAME = font_manager.FontProperties(fname=path).get_name()
                break
            except Exception:
                continue
    if _FONT_NAME:
        rcParams["font.sans-serif"] = [_FONT_NAME, "DejaVu Sans"]
    rcParams["font.family"] = "sans-serif"
    rcParams["axes.unicode_minus"] = False   # 负号正常显示


def apply_style():
    """应用中文字体 + 汇报级视觉风格。可重复调用（幂等）。"""
    _setup_font()
    rcParams.update({
        "figure.figsize": (8, 5),
        "figure.dpi": 120,
        "savefig.dpi": 200,            # 高清，进 PPT 不糊
        "savefig.bbox": "tight",       # 自动裁掉多余白边
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#C9D1D9",
        "axes.linewidth": 1.0,
        "axes.grid": True,
        "axes.axisbelow": True,        # 网格在数据下方
        "grid.color": "#E6EAEE",
        "grid.linewidth": 1.0,
        "axes.spines.top": False,      # 去掉上、右边框，更清爽
        "axes.spines.right": False,
        "axes.titlesize": 15,
        "axes.titleweight": "bold",
        "axes.titlecolor": _DARK,
        "axes.titlepad": 12,
        "axes.labelsize": 12,
        "axes.labelcolor": _DARK,
        "xtick.color": _GRAY,
        "ytick.color": _GRAY,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 11,
        "legend.frameon": False,
        "lines.linewidth": 2.2,
        "lines.markersize": 6,
        "patch.edgecolor": "white",
        "axes.prop_cycle": plt.cycler(color=PALETTE),
    })
