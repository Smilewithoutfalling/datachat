"""M13 第 1 步：静态统计历史画图代码里的图型，估计 v1 builder 五类（bar/line/area/pie/scatter）的覆盖率。

只看代码文本（正则），不重放；样本是 docs/eval 下所有报告里的 code 字段。结论只作方向性判断。
用法：python scripts/chart_coverage.py [--json out.json] [--show]
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
    "stacked":  [r"stacked\s*=\s*True", r"bottom\s*=", r"\.stackplot\("],
}
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


def classify(code):
    kinds = {k for k, pats in PATTERNS.items() if any(re.search(p, code) for p in pats)}
    if _bare_plot(code):
        kinds.add("line")
    struct = {k for k, pats in STRUCT.items() if any(re.search(p, code) for p in pats)}
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
                         "struct": sorted(struct)})
    return rows


def verdict(r):
    k, s = set(r["kinds"]), set(r["struct"])
    if not k:
        return "unknown"
    if not k <= V1:
        return "uncovered_kind"
    if "twinx" in s or "subplots" in s:
        return "uncovered_layout"
    if len(k - {"barh"} | ({"bar"} if "barh" in k else set())) > 1:
        return "mixed"                # 一张图里混了两种图型（如柱 + 折线）：v1 builder 一次只出一种
    return "covered"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--show", action="store_true")
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
    print("判定：" + "，".join(f"{k} {c}" for k, c in v.most_common()))
    if n:
        print(f"v1 五类完整覆盖：{v['covered']}/{n} = {v['covered'] / n:.0%}")
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
