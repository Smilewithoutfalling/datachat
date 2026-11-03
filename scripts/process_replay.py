"""回放评测报告里的过程结构标记（E2），和人工判定对照。

用法：
    python scripts/process_replay.py docs/eval/gate_*.json
    python scripts/process_replay.py docs/eval/gate_*.json --detail
    python scripts/process_replay.py docs/eval/eval_*.json --rule unnamed_column

**它不是正确率的补充指标。** 两条规则各自只抓一个很窄的写法，命中不等于判错（见
`app/eval/process_check.py` 的 docstring 与 DEVLOG [112] 的实测）。这个脚本只有一个用途：
拿"有人工标注的报告"验一遍规则靠不靠谱 —— 召回多少、误报多少。没标注的报告只能看命中清单。

老报告没有 `process_risks` 字段（该字段 2026-11-02 才加），这里从 `code` 现场重算。
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.eval.process_check import RULES, details  # noqa: E402


def _paths(patterns):
    out = []
    for p in patterns:
        hit = glob.glob(p) or ([p] if os.path.exists(p) else [])
        out.extend(sorted(hit))
    return out


def _cases(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for c in data.get("cases") or []:
        yield c


def main():
    ap = argparse.ArgumentParser(description="回放 E2 过程结构标记")
    ap.add_argument("reports", nargs="+", help="报告 JSON 路径或 glob")
    ap.add_argument("--detail", action="store_true", help="打印每个命中的源码行")
    ap.add_argument("--rule", help="只看某条规则")
    args = ap.parse_args()

    paths = _paths(args.reports)
    if not paths:
        sys.exit("没有匹配的报告")

    rows = []
    for p in paths:
        for c in _cases(p):
            c["_file"] = os.path.basename(p)
            c["_hits"] = details(c.get("code"))
            rows.append(c)

    hits = []
    for c in rows:
        for d in c["_hits"]:
            if args.rule and d["rule"] != args.rule:
                continue
            d = dict(d)
            d.update(id=c.get("id"), file=c["_file"], human_correct=c.get("human_correct"))
            hits.append(d)

    n_code = sum(1 for c in rows if c.get("code"))
    graded = [c for c in rows if c.get("human_correct") is not None]
    wrong = [c for c in graded if c["human_correct"] is False]
    right = [c for c in graded if c["human_correct"] is True]

    print(f"报告 {len(paths)} 份 / case {len(rows)} / 有代码 {n_code} / 标记 {len(hits)} 次")
    print(f"有人工标注 {len(graded)}（判错 {len(wrong)} / 判对 {len(right)}）")
    print()

    by_rule = collections.Counter(h["rule"] for h in hits)
    print(f"{'规则':22} {'标记':>4} {'判错':>4} {'判对':>4} {'未标注':>6}  精度")
    for rule in RULES:
        if args.rule and rule != args.rule:
            continue
        hs = [h for h in hits if h["rule"] == rule]
        nw = sum(1 for h in hs if h["human_correct"] is False)
        nr = sum(1 for h in hs if h["human_correct"] is True)
        nu = sum(1 for h in hs if h["human_correct"] is None)
        prec = f"{nw / (nw + nr):.0%}" if (nw + nr) else "—"
        print(f"{rule:22} {by_rule[rule]:>4} {nw:>4} {nr:>4} {nu:>6}  {prec}")
    print()

    # 召回/误报给两个口径：
    # - 题次：22 次判错里有几次被标出。反映"标记能省多少人工翻查"。
    # - 题  ：8 道判错的题里有几道被标出。反映"覆盖了多少种错法"。
    # 两个不一样是因为同一道题会被多次重跑（s04 判错 4 次、s02 判错 6 次）。
    marked_w = {h["id"] for h in hits if h["human_correct"] is False}
    marked_r = {h["id"] for h in hits if h["human_correct"] is True}
    n_w_times = sum(1 for h in hits if h["human_correct"] is False)
    n_r_times = sum(1 for h in hits if h["human_correct"] is True)
    ids_w = {c["id"] for c in wrong}
    ids_r = {c["id"] for c in right}
    if wrong:
        print(f"召回（题次）  {n_w_times}/{len(wrong)} = {n_w_times / len(wrong):.0%}"
              f"    误报（题次）  {n_r_times}/{len(right) if right else 0}"
              + (f" = {n_r_times / len(right):.0%}" if right else ""))
    if ids_w:
        print(f"召回（题）    {len(marked_w)}/{len(ids_w)} = {len(marked_w) / len(ids_w):.0%}"
              f"    误报（题）    {len(marked_r)}/{len(ids_r) if ids_r else 0}"
              + (f" = {len(marked_r) / len(ids_r):.0%}" if ids_r else ""))
    print("注：召回低不代表规则坏 —— 它只覆盖两种写法，其余错因（口径、缺失哨兵）在 AST 层看不见。")
    print("    同一道题反复判错会重复计数，所以「题次」比「题」高不代表覆盖更广。")
    print()

    if args.detail:
        print("== 命中详情 ==")
        for h in hits:
            hc = {True: "对", False: "错", None: "未标注"}[h["human_correct"]]
            extra = h.get("columns") or h.get("value") or ""
            print(f"{h['file'][:30]:32} {str(h['id']):6} {hc:4} {h['rule']:20} {extra}")
            print(f"    L{h['line']}: {h['text'][:110]}")
    else:
        print("命中清单（加 --detail 看源码行）：")
        for h in hits:
            hc = {True: "对", False: "错", None: "未标注"}[h["human_correct"]]
            print(f"  {h['file'][:30]:32} {str(h['id']):6} {hc:4} {h['rule']}")


if __name__ == "__main__":
    main()
