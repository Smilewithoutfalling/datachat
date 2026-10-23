"""把后端的事件类型、图表白名单与禁用键、图表夹具导出成前端用的 JSON（阶段 5 F2 / F3），前端不手抄、改了后端 CI 就报。

    python scripts/gen_ui_types.py            # 写 ui/web/src/generated/{events,banned_keys,chart_schema,chart_fixtures,kind_fixtures,inject}.json
    python scripts/gen_ui_types.py --check    # 只校验现有文件与重新生成的是否一致（CI 用）

来源：app/core/events.py 的 EVENT_TYPES、ERROR_KINDS 和常量文案；app/server/db.py 的 MESSAGE_STATUSES；app/tools/charts.py 的 BANNED_KEYS（前端渲染 ECharts 前再过一遍）、
KINDS / _KIND_SERIES_TYPE / _ENUMS / _ALLOWED 顶层键（chart_schema.json，前端组件注册表双向比对），
以及 build_option 在固定合成数据上的真实产出（chart_fixtures.json，前端渲染测试只用它，不手写 option）；
F3 第二步的注入载荷与 CSV（inject.json，来自 tests/fake_llm.py，前端 e2e 直接上传这份 CSV，不在 TS 里手拼）。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "ui", "web", "src", "generated")


def chart_schema() -> dict:
    from app.tools.charts import (_ALLOWED, _CART_BOTTOM, _CART_GRID, _ENUMS, _KIND_SERIES_TYPE, _PIE_CENTER, _PIE_LEGEND,
                                  _PIE_RADIUS, AXIS_NAME_MAX_PX, DISPLAY_UNSAFE, GEOMETRY, KINDS, MAX_PIE_SLICES, PALETTE,
                                  SHOW_SYMBOL_MAX, TITLE_MAX, X_KINDS)
    return {"_generated_by": "scripts/gen_ui_types.py", "kinds": list(KINDS),
            "palette": list(PALETTE),               # 前端默认主题（经典）的 color 从这里读（F3 第四步）
            "axis_name_max_px": AXIS_NAME_MAX_PX,
            # F3 第五步：prepare 的 normalize 用 geometry 归一历史 spec；changeKind 用 frame / 阈值造出和 builder 一样的 option
            "geometry": GEOMETRY,
            "x_kinds": list(X_KINDS),
            "pie_max_slices": MAX_PIE_SLICES,
            "show_symbol_max": SHOW_SYMBOL_MAX,
            "frame": {"cartesian_grid": _CART_GRID, "cartesian_bottom": _CART_BOTTOM,
                      "pie_legend": _PIE_LEGEND, "pie_radius": _PIE_RADIUS, "pie_center": _PIE_CENTER},
            # V2b B3：标记卡的标题输入在前端 sanitizeTitle 清洗，渲染面替换表和限长与后端同一份（Bidi 表是前端独有的，不导出）
            "display": {"unsafe": dict(DISPLAY_UNSAFE), "title_max": TITLE_MAX},
            "kind_series_type": dict(_KIND_SERIES_TYPE),
            "top_level_keys": list(_ALLOWED),
            "enums": {".".join(k): sorted(v) for k, v in _ENUMS.items()}}


def chart_fixtures() -> dict:
    """固定合成数据 → build_option 的真实产出。只放成功例（validate_spec 的拒绝例在 tests/test_charts.py）。"""
    import numpy as np
    import pandas as pd
    from app.tools.charts import MAX_PIE_SLICES, MAX_POINTS, MAX_SERIES, NAME_MAX, build_option

    def _ascii_name(tag):
        return (f"{tag}_total_revenue_by_region_" * 10)[:NAME_MAX]
    rng = np.random.RandomState(20261016)
    small = pd.DataFrame({"城市": ["北京", "上海", "广州", "深圳", "杭州"], "销量": [3, 5, 2, 8, 6],
                          "利润": [1.5, 2.25, 0.5, 3.75, 2.0]})
    days = pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=30, freq="D"),
                         "访问": rng.randint(50, 200, 30)})
    missing = pd.DataFrame({"类别": ["甲", None, "丙", "丁"], "值": [1.0, 2.0, np.nan, 4.0]})
    long = pd.DataFrame([(f"m{i}", f"s{j:02d}", int(rng.randint(0, 100))) for i in range(5) for j in range(MAX_SERIES)],
                        columns=["月", "系列", "量"])
    pie = pd.DataFrame({"项": [f"项{i:02d}" for i in range(MAX_PIE_SLICES)], "值": rng.randint(1, 100, MAX_PIE_SLICES)})
    def cats(n):
        return pd.DataFrame({"k": [f"k{i}" for i in range(n)], "v": rng.randint(0, 1000, n)})
    def pts(n):
        return pd.DataFrame({"x": rng.normal(0, 1, n).round(3), "y": rng.normal(0, 1, n).round(3)})
    wide = pd.DataFrame({"季度": ["Q1", "Q2", "Q3", "Q4"], "收入": [10, 12, 9, 15], "成本": [7, 8, 8, 9], "利润": [3, 4, 1, 6]})
    from tests.fake_llm import INJECT_PAYLOADS as P, INJECT_COLUMNS, INJECT_ROWS
    inj = pd.DataFrame(INJECT_ROWS, columns=INJECT_COLUMNS)
    c_cat, c_ser, c_n1, c_n2 = INJECT_COLUMNS
    cases = [
        ("bar", build_option("bar", small, x="城市", y="销量", title="各城市销量")),
        ("bar-untitled", build_option("bar", small, x="城市", y="销量")),
        ("line", build_option("line", small, x="城市", y="销量", title="销量走势")),
        ("area", build_option("area", small, x="城市", y="销量", title="销量面积")),
        ("pie", build_option("pie", small, x="城市", y="销量", title="销量占比")),
        ("scatter", build_option("scatter", small, x="销量", y="利润", title="销量与利润")),
        ("line-time", build_option("line", days, x="日期", y="访问", title="每日访问")),
        ("area-time", build_option("area", days, x="日期", y="访问")),
        ("bar-missing", build_option("bar", missing, x="类别", y="值", title="含缺失")),
        (f"bar-series-{MAX_SERIES}", build_option("bar", long, x="月", y="量", series="系列")),
        (f"pie-{MAX_PIE_SLICES}", build_option("pie", pie, x="项", y="值")),
        ("line-wide", build_option("line", wide, x="季度", y=["收入", "成本", "利润"], title="多指标")),
        (f"bar-{MAX_POINTS}", build_option("bar", cats(MAX_POINTS), x="k", y="v")),
        (f"bar-{MAX_POINTS + 1}", build_option("bar", cats(MAX_POINTS + 1), x="k", y="v", title="截断柱图")),
        (f"scatter-{MAX_POINTS}", build_option("scatter", pts(MAX_POINTS), x="x", y="y")),
        (f"scatter-{MAX_POINTS + 1}", build_option("scatter", pts(MAX_POINTS + 1), x="x", y="y", title="截断散点")),
        # 注入例（F3 第二步）：与 fake inject-<kind> 同一份数据、同样的调用
        ("inject-bar", build_option("bar", inj, x=c_cat, y=[c_n1, c_n2], title=P["P1"])),
        ("inject-bar-series", build_option("bar", inj, x=c_cat, y=c_n1, series=c_ser, title=f"{P['P4']} {P['P5']}")),
        ("inject-pie", build_option("pie", inj, x=c_cat, y=c_n1, title=P["P1"])),
        # F3 第三步：outerBounds 的 clamp 下限（默认 25%）在"类目少 + 标签超长"时最容易显形：3 个类目不会被 hideOverlap 隔开
        ("long-labels-bar", build_option("bar", pd.DataFrame({"名": [f"{c}" * 120 for c in "甲乙丙"], "值": [3, 1, 2]}),
                                         x="名", y="值")),
        # F3 第四步：轴名纳入外边界 + nameTruncate。长度取 NAME_MAX；ASCII 是 CSV 列名的主流场景；y 单独一例（截断逐轴生效）
        ("long-axis-name-bar", build_option("bar", pd.DataFrame({"横" * NAME_MAX: ["甲", "乙", "丙"], "纵" * NAME_MAX: [3, 1, 2]}),
                                            x="横" * NAME_MAX, y="纵" * NAME_MAX)),
        ("long-ascii-axis-name-bar", build_option("bar", pd.DataFrame({_ascii_name("x"): ["a", "b", "c"], _ascii_name("y"): [3, 1, 2]}),
                                                  x=_ascii_name("x"), y=_ascii_name("y"))),
        ("long-y-axis-name-bar", build_option("bar", pd.DataFrame({"k": ["a", "b", "c"], _ascii_name("y"): [3, 1, 2]}),
                                              x="k", y=_ascii_name("y"))),
        # F3 第五步：COMPAT 的"多系列 scatter"格（图例位置开关）要一个真实夹具
        ("scatter-multi", build_option("scatter", small.assign(组=["a", "b", "a", "b", "a"]), x="销量", y="利润",
                                       series="组", title="分组散点")),
    ]
    return {"_generated_by": "scripts/gen_ui_types.py", "fixtures": [{"id": i, "spec": s} for i, s in cases]}


def kind_fixtures() -> dict:
    """F3 第五步换图型契约：同一份数据分别以 bar / line / area / pie 调 build_option。前端断言 changeKind(A, B) 等于这里的 B，
    只允许 switches.ts 的 KIND_DIFF 列出的差异。组：单系列类目、单系列时间、多系列宽表、类目数超过 SHOW_SYMBOL_MAX、含空值。"""
    import numpy as np
    import pandas as pd
    from app.tools.charts import MAX_PIE_SLICES, SHOW_SYMBOL_MAX, build_option
    small = pd.DataFrame({"城市": ["北京", "上海", "广州", "深圳", "杭州"], "销量": [3, 5, 2, 8, 6]})
    days = pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=30, freq="D"), "访问": list(range(30, 60))})
    wide = pd.DataFrame({"季度": ["Q1", "Q2", "Q3", "Q4"], "收入": [10, 12, 9, 15], "成本": [7, 8, 8, 9]})
    many = pd.DataFrame({"k": [f"k{i:02d}" for i in range(SHOW_SYMBOL_MAX + 1)], "v": list(range(SHOW_SYMBOL_MAX + 1))})
    pie_max = pd.DataFrame({"项": [f"项{i:02d}" for i in range(MAX_PIE_SLICES)], "值": list(range(1, MAX_PIE_SLICES + 1))})
    over = pd.DataFrame({"项": [f"项{i:02d}" for i in range(MAX_PIE_SLICES + 1)], "值": list(range(1, MAX_PIE_SLICES + 2))})
    holes = pd.DataFrame({"类": ["甲", "乙", "丙"], "值": [1.0, np.nan, 3.0]})
    neg = pd.DataFrame({"类": ["甲", "乙", "丙"], "值": [1, -2, 3]})

    def group(df, kinds, **kw):
        return {k: build_option(k, df, **kw) for k in kinds}
    four, three = ("bar", "line", "area", "pie"), ("bar", "line", "area")
    return {"_generated_by": "scripts/gen_ui_types.py", "groups": {
        "single": group(small, four, x="城市", y="销量", title="销量"),
        "time": group(days, four, x="日期", y="访问"),
        "wide": group(wide, three, x="季度", y=["收入", "成本"], title="收支"),
        "many": group(many, three, x="k", y="v"),
        "pie-max": group(pie_max, four, x="项", y="值"),
        # 下面三组只有直角坐标：换饼图的条件不满足（类目超上限 / 有空值 / 有负值），前端断言饼图选项置灰
        "pie-over": group(over, three, x="项", y="值"),
        "holes": group(holes, three, x="类", y="值"),
        "negative": group(neg, three, x="类", y="值"),
    }}


def inject() -> dict:
    from app.tools.charts import _display_safe
    from tests.fake_llm import INJECT_ORDER, INJECT_PAYLOADS, inject_csv
    # display：后端 _display_safe 算出的期望画布显示串（F3 第三步），前端判据只用它，不在 TS 里另写一份规范化
    return {"_generated_by": "scripts/gen_ui_types.py", "payloads": dict(INJECT_PAYLOADS),
            "display": _display_safe(dict(INJECT_PAYLOADS)), "order": list(INJECT_ORDER), "csv": inject_csv()}


def build() -> dict[str, str]:
    from app.core.events import (CANCELLED_MESSAGE, DISCONNECTED_MESSAGE, ERROR_KINDS, EVENT_TYPES,
                                 INTERRUPTED_MESSAGE, LLM_KINDS, STREAM_ABORTED_MESSAGE)
    from app.server.db import MESSAGE_STATUSES
    from app.tools.charts import BANNED_KEYS
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=2) + "\n"   # noqa: E731
    return {
        "events.json": dump({"_generated_by": "scripts/gen_ui_types.py", "event_types": list(EVENT_TYPES),
                             "error_kinds": list(ERROR_KINDS), "llm_kinds": list(LLM_KINDS),
                             "message_statuses": list(MESSAGE_STATUSES),
                             "messages": {"cancelled": CANCELLED_MESSAGE, "interrupted": INTERRUPTED_MESSAGE,
                                          "disconnected": DISCONNECTED_MESSAGE,
                                          "stream_aborted": STREAM_ABORTED_MESSAGE}}),
        "banned_keys.json": dump({"_generated_by": "scripts/gen_ui_types.py", "banned_keys": sorted(BANNED_KEYS)}),
        "chart_schema.json": dump(chart_schema()),
        # indent=1：build_option 一改，diff 能看出改了哪个值（紧凑 JSON 一行，每次整份重写）。按字节比对。
        "chart_fixtures.json": json.dumps(chart_fixtures(), ensure_ascii=False, indent=1) + "\n",
        "kind_fixtures.json": json.dumps(kind_fixtures(), ensure_ascii=False, indent=1) + "\n",
        "inject.json": dump(inject()),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    bad = []
    for name, text in build().items():
        path = os.path.join(OUT_DIR, name)
        if args.check:
            try:
                with open(path, encoding="utf-8", newline="") as f:
                    cur = f.read().replace("\r\n", "\n")
            except FileNotFoundError:
                cur = None
            if cur != text:
                bad.append(name)
        else:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    if bad:
        print("与后端不一致，运行 python scripts/gen_ui_types.py 重新生成：" + "、".join(bad))
        return 1
    print("ok" if args.check else f"已写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
