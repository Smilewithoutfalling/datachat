"""M13 第 1 步：静态统计历史画图代码里的图型，估计 v1 builder 五类（bar/line/area/pie/scatter）的覆盖率。

只看代码文本（正则），不重放；样本是 docs/eval 下所有报告里的 code 字段。结论只作方向性判断。
用法：python scripts/chart_coverage.py [--by-case] [--show] [--json out.json]

判定（每份代码一个）：
  covered            五类之一，单图
  multi_figure       多张独立的图（plt.figure / subplots / close 分段），每张都是五类之一 → v1 每次最多 4 张，算覆盖
  degraded           折线 + 少量 scatter 高亮点（列表字面量或 zorder）→ 主图可出，高亮点丢失，算覆盖但降级
  overlay            同一张图叠两种图型（如散点 + 趋势线）→ 未覆盖
  uncovered_kind     有五类以外的图型（hist / heatmap / box）
  multi_panel        多子图（subplots，≤4 格）且每格都是五类之一 → 可拆成 N 次 chart()，算覆盖（与 multi_figure 同口径）
  uncovered_layout   双轴（twinx / secondary_y），或子图超过 4 格 / 格数认不出
  unknown            认不出图型
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 三种写法都要认：plt.bar / ax.bar / df.plot(kind='bar') / df.plot.bar()
_K = r"""kind\s*=\s*['"]{k}['"]"""
PATTERNS = {
    "barh":    [r"\.barh\(", r"\.plot\.barh\(", _K.format(k="barh")],
    "bar":     [r"\.bar\(", r"\.plot\.bar\(", _K.format(k="bar"), r"\.bar_label\("],
    "pie":     [r"\.pie\(", r"\.plot\.pie\(", _K.format(k="pie")],
    "scatter": [r"\.scatter\(", r"\.plot\.scatter\(", _K.format(k="scatter")],
    "hist":    [r"\.hist\(", r"\.plot\.hist\(", _K.format(k="hist")],
    "area":    [r"\.fill_between\(", r"\.stackplot\(", r"\.plot\.area\(", _K.format(k="area")],
    "box":     [r"\.boxplot\(", r"\.plot\.box\(", _K.format(k="box")],
    "heatmap": [r"\.imshow\(", r"\.pcolormesh\(", r"\.matshow\("],
    # line：plt.plot / ax.plot / s.plot(...) 没有 kind，或 kind='line'，或 .plot.line()
    "line":    [r"(?:plt|ax\w*)\.plot\(", r"\.plot\.line\(", _K.format(k="line")],
}
STRUCT = {
    "twinx":    [r"\.twinx\(", r"\.twiny\(", r"secondary_y\s*="],
    "subplots": [r"subplots\(\s*(?:nrows\s*=\s*)?[2-9]", r"subplots\(\s*1\s*,\s*[2-9]", r"\.subplot\(\s*\d",
                 r"ncols\s*=\s*[2-9]", r"nrows\s*=\s*[2-9]", r"subplots\s*=\s*True"],
    # 只统计，不参与判定：堆叠是前端开关，builder 出多系列即可
    "stacked":  [r"stacked\s*=\s*True", r"bottom\s*=", r"\.stackplot\("],
}
COVERED = {"covered", "multi_figure", "multi_panel", "degraded"}
MAX_CHARTS = 4                                   # v1 每次分析最多 4 张
_FIG_SPLIT = re.compile(r"plt\.figure\(|plt\.subplots\(|plt\.close\(")
_MARKER_SCATTER = re.compile(r"\.scatter\(\s*\[|\.scatter\([^\n]*zorder")
V1 = {"bar", "barh", "line", "area", "pie", "scatter"}   # barh = bar + 前端横向开关
DRAW_HINT = re.compile(r"\bplt\.|\.plot\b|savefig|\bax\w*\.")


def _bare_plot(code):
    """df.plot(...) / s.plot() 不带 kind：pandas 默认折线。"""
    for m in re.finditer(r"(?<![\w.])\w[\w\]\[\'\"]*\.plot\(([^()]*(?:\([^()]*\)[^()]*)*)\)", code):
        if m.group(0).startswith(("plt.", "ax")):
            continue
        if "kind" not in m.group(1):
            return True
    return False


def _kinds(code):
    kinds = {k for k, pats in PATTERNS.items() if any(re.search(p, code) for p in pats)}
    if _bare_plot(code):
        kinds.add("line")
    return kinds


def _norm(kinds):
    return {"bar" if k == "barh" else k for k in kinds}


def classify(code):
    kinds = _kinds(code)
    struct = {k for k, pats in STRUCT.items() if any(re.search(p, code) for p in pats)}
    segs = [_norm(_kinds(seg)) for seg in _FIG_SPLIT.split(code)]
    segs = [k for k in segs if k]
    if len(segs) > 1 and all(len(k) == 1 for k in segs):
        struct.add("multi_figure")
    if {"line", "scatter"} <= kinds and _MARKER_SCATTER.search(code):
        struct.add("marker_scatter")
    return kinds, struct


def _iter_codes(node, ctx):
    if isinstance(node, dict):
        cid = node.get("id") or node.get("case_id") or ctx
        if isinstance(node.get("code"), str) and node["code"].strip():
            yield cid, node["code"]
        for k, v in node.items():
            if k != "code":
                yield from _iter_codes(v, cid)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_codes(v, ctx)


def collect(paths):
    rows = []
    for path in paths:
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        seen = set()
        for cid, code in _iter_codes(data, None):
            if (cid, code) in seen or not DRAW_HINT.search(code):
                continue
            seen.add((cid, code))
            kinds, struct = classify(code)
            if not kinds and not re.search(r"savefig|plt\.|\.plot\b", code):
                continue
            rows.append({"file": os.path.relpath(path, ROOT), "case": cid, "kinds": sorted(kinds),
                         "struct": sorted(struct), "panels": _panels(code)})
    return rows


_GRID = re.compile(r"subplots\(\s*(?:nrows\s*=\s*)?(\d)\s*,\s*(?:ncols\s*=\s*)?(\d)")


def _panels(code):
    """subplots(r, c) 的格数；认不出返回 None（按未覆盖处理）。"""
    m = _GRID.search(code or "")
    return int(m.group(1)) * int(m.group(2)) if m else None


def verdict(r):
    k, s = set(r["kinds"]), set(r["struct"])
    if not k:
        return "unknown"
    if not k <= V1:
        return "uncovered_kind"
    if "twinx" in s:
        return "uncovered_layout"
    if "subplots" in s:
        n = r.get("panels")
        return "multi_panel" if n is not None and n <= MAX_CHARTS else "uncovered_layout"
    if len(_norm(k)) > 1:
        if "multi_figure" in s:
            return "multi_figure"
        if _norm(k) == {"line", "scatter"} and "marker_scatter" in s:
            return "degraded"
        return "overlay"
    return "covered"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--show", action="store_true", help="列出未覆盖的样本")
    ap.add_argument("--by-case", action="store_true", help="按题（多数票）统计并列出未覆盖的题")
    a = ap.parse_args(argv)
    paths = sorted(glob.glob(os.path.join(ROOT, "docs", "eval", "**", "*.json"), recursive=True))
    rows = collect(paths)
    for r in rows:
        r["verdict"] = verdict(r)
    uniq = {(r["case"], tuple(r["kinds"]), tuple(r["struct"])) for r in rows}
    v = Counter(r["verdict"] for r in rows)
    kinds = Counter(k for r in rows for k in r["kinds"])
    struct = Counter(s for r in rows for s in r["struct"])
    n = len(rows)
    print(f"报告文件 {len(paths)} 个；画图代码样本 {n} 份（按 题×图型 去重后 {len(uniq)} 种）")
    print("按样本判定：" + "，".join(f"{k} {c}" for k, c in v.most_common()))
    if n:
        cov = sum(v[k] for k in COVERED)
        print(f"按样本覆盖：严格 {v['covered']}/{n} = {v['covered'] / n:.0%}；"
              f"含多图与降级 {cov}/{n} = {cov / n:.0%}")
    if a.by_case:
        by = {}
        for r in rows:
            by.setdefault(r["case"], Counter())[r["verdict"]] += 1
        maj = {}
        for case, cnt in by.items():
            top = cnt.most_common()
            maj[case] = "tie" if len(top) > 1 and top[0][1] == top[1][1] else top[0][0]
        m = Counter(maj.values())
        nc = len(by)
        strict = m["covered"]
        cov = sum(m[k] for k in COVERED)
        print(f"按题（多数票，{nc} 题）：" + "，".join(f"{k} {c}" for k, c in m.most_common()))
        print(f"按题覆盖：严格 {strict}/{nc} = {strict / nc:.0%}；含多图与降级 {cov}/{nc} = {cov / nc:.0%}")
        for case in sorted(maj, key=lambda c: (maj[c], str(c))):
            if maj[case] not in ("covered",):
                print(f"  {maj[case]:<17} {case!s:<10} " + "，".join(f"{k} {c}" for k, c in by[case].most_common()))
    print("图型出现次数：" + "，".join(f"{k} {c}" for k, c in kinds.most_common()))
    print("结构：" + ("，".join(f"{k} {c}" for k, c in struct.most_common()) or "无"))
    if a.show:
        for r in rows:
            if r["verdict"] != "covered":
                print(f"  {r['verdict']:<17} {r['case']!s:<8} {','.join(r['kinds']) or '-':<20} "
                      f"{','.join(r['struct']) or '-':<16} {r['file']}")
    if a.json:
        json.dump({"n": n, "verdict": dict(v), "kinds": dict(kinds), "struct": dict(struct), "rows": rows},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
