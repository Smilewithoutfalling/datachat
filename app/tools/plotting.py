
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
PALETTE = ["#1F6FB2", "#159A8C", "#E2843B", "#C0392B", "#7E57C2", "#3A7D44"]

_DARK = "#2B3A46"
_GRAY = "#66707A"

# 给模型的统一绘图要求：产出可直接放进汇报 PPT 的图。
# 字体与配色已由 apply_style() 全局设好，模型无需再设 rcParams/字体。
CHART_GUIDE = (
    "绘图要求（务必遵守，目标是可直接用于汇报 PPT 的图）：\n"
    "- 中文字体与配色已全局配置好，正常调用 plt/pandas 绘图即可，不要再设字体或 rcParams。\n"
    "- 必须有中文标题（ax.set_title）和中文坐标轴标签（set_xlabel/set_ylabel）。\n"
    "- 选择合适的图型：对比用柱状图、趋势用折线图、占比用饼图/堆叠图。\n"
    "- 关键数据点加数值标注（ax.text / bar_label），让人不看坐标也能读数。\n"
    "- 横轴是字符串标签（如 '2024-01'）时，pandas 折线/柱状图的横坐标实际是位置 0..n-1："
    "用 for i, (lab, y) in enumerate(s.items()): ax.text(i, y, ...) 标注，不要把字符串当 x 传给 ax.text/annotate。\n"
    "- 不要堆砌过多元素，保持简洁；如有多类别再加图例。\n"
    "- 用 plt.savefig(chart_path) 保存（清晰度与白边已全局处理，无需传 dpi）。"
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
