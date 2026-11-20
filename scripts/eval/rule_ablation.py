"""comparator 放宽规则留一消融（7.5b B3，phase75b-eval-assess.md §B3）。

用法：
    python scripts/eval/rule_ablation.py <报告.json> [<报告2.json> ...] [--md OUT.md] [--json OUT.json]

对每条可消融的放宽规则：monkeypatch 关掉它的实现函数，用 rescore()（零 API，
报告里存了 actual_obj）在报告上重打分，记录哪些题翻转。产出「规则 → 翻转数、
方向、涉及题号」表。**只产报告**：不写回报告、不改 comparator、不改 gold、
不改题库 —— 结论写进报告末尾的「CHANGES 候选清单」段，攒给下一次断代。

设计要点：

- **monkeypatch，comparator 零改动**。放宽规则一半是独立函数（_extras_eq、
  _rank_eq、_drop_margins…），可以直接替换；另一半是 _vs_scalar / _vs_sequence /
  _series_eq 里的内嵌分支，替换它们等于把比较逻辑抄一份进脚本，迟早漂 ——
  这些规则**不做消融**，在报告里列为「内嵌不可消融」，人工复核靠 match_kind=relaxed
  的 needs_audit 清单（rescore 已给出）。
- **共用 helper 如实标注**。_pct 同时服务规则 19 与规则 10/20b 的值解析；
  _month_numbers 同时服务规则 14 与 18 —— 关掉它们消融的是整个接受面，
  报告的「覆盖」列写「共用」，翻转数解释时按面读，不按规则号读。
- **方向**。放宽规则关掉只会让判对变判错（对→错）；规则 24（拒答越界）相反，
  关掉是少判错（错→对）。出现其余方向的翻转属于异常，逐条列出。

验收口径（方案 §B3）：3b→3c 的 +4.6 点应落在 3c 新增的规则 18/19/20 各自的
翻转数上。历史读数是在旧报告上测的，这里是在新报告上测，数量级对得上即可。

退出码恒 0：这是体检报告，不是闸门（§0 规则：评估只列不判）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Windows GBK 控制台兜底；CI 是 UTF-8 不受影响
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import app.eval.comparator as C            # noqa: E402
import app.eval.rescore as RS               # noqa: E402
from app.eval.rescore import rescore       # noqa: E402

_NEVER = re.compile(r"(?!x)x")   # 永不匹配，用来关掉正则型规则


def _drop_margins_off(a, e):
    return a                    # 规则 17：不去汇总行列，原样比


def _false(*_a, **_k):
    return False


def _none(*_a, **_k):
    return None


def _empty(*_a, **_k):
    return []


def _pct_off(_v):
    return None                 # 规则 19：百分数字符串不再按数值读


def _leak_off(answer):
    return None, ""             # 规则 24：不再判拒答越界


# (unit id, 说明, 覆盖, patches {模块: {attr: stub}}, 方向)
RULES = [
    ("r17", "规则17 去总计/汇总行列", "完整",
     {C: {"_drop_margins": _drop_margins_off}}, "对→错"),
    ("r20", "规则20 附加信息形态（a/a2/b/c）", "完整",
     {C: {"_extras_eq": _false}}, "对→错"),
    ("r19_rank", "规则19 名次 Series（问排名给 1..n）", "完整",
     {C: {"_rank_eq": _false}}, "对→错"),
    ("r19_dict", "规则19 dict 键内嵌季度/月份", "完整",
     {C: {"_dict_embedded_periods": _false}}, "对→错"),
    ("r19_pct", "规则19 百分数字符串（'7.00%'）", "共用（规则10/20b 的值解析同用 _pct）",
     {C: {"_pct": _pct_off}}, "对→错"),
    ("r18_q", "规则18 季度序号索引", "完整",
     {C: {"_quarter_numbers": _none}}, "对→错"),
    ("r14_18_m", "规则14+18 月份序号索引", "共用（14 与 18 同用 _month_numbers）",
     {C: {"_month_numbers": _none}}, "对→错"),
    ("r6_22", "规则6+22 月份键对齐（含中文月份）", "共用（时间索引对齐与 _is_time_index 同用）",
     {C: {"_month_key": _none}}, "对→错"),
    ("r12", "规则12 百分刻度 ×100/÷100（percent_equiv）", "完整",
     {C: {"_scale": _none}}, "对→错"),
    ("r8", "规则8 按值找（标签列,数值列）/ 表列值匹配", "完整",
     {C: {"_label_value_series": _empty, "_match_columns": _none}}, "对→错"),
    ("r21a", "规则21a 标签集合（set 期望）", "完整",
     {C: {"_vs_label_set": _false}}, "对→错"),
    ("r15", "规则15 ISO 周标签", "完整",
     {C: {"_WEEK_RE": _NEVER}}, "对→错"),
    ("r23", "规则23 裸日期写法", "完整",
     {C: {"_MONTH_DAY_RE": _NEVER, "_FULL_DATE_RE": _NEVER}}, "对→错"),
    ("r25", "规则25 时间字段级归一", "完整",
     {C: {"_time_key": _none}}, "对→错"),
    ("r11", "规则11 标量对序号（月份/季度部分）", "共用（_period_part 同时喂 14/18 的 helper）",
     {C: {"_period_part": _none}}, "对→错"),
    ("r24", "规则24 拒答越界（≥2 百分比判错）", "完整",
     {C: {"refusal_leak": _leak_off}, RS: {"refusal_leak": _leak_off}}, "错→对"),
]

# 内嵌分支，monkeypatch 关不掉（关掉 = 抄一份比较逻辑进脚本，迟早漂）。
INLINE_RULES = ("1 单元素容器拆包", "2 标签vs二元组", "3 表→Series 还原", "4 MultiIndex↔透视宽表",
                "5 期望列子集", "9 N行表任一列=期望", "10 单行汇总含期望", "13 一行表↔行Series",
                "16 dict 值里按序找标签", "21b Top-N标签在索引", "21c ExtensionArray按list",
                "18内嵌两处（ISO周序号/连续序号按位置比）")


def _apply(patches):
    """返回可还原的 {(module, attr): 原 值} 快照。"""
    saved = {}
    for mod, attrs in patches.items():
        for name, stub in attrs.items():
            saved[(mod, name)] = getattr(mod, name)
            setattr(mod, name, stub)
    return saved


def _restore(saved):
    for (mod, name), orig in saved.items():
        setattr(mod, name, orig)


def _run(report_path: str) -> list:
    """一份报告的消融结果：[{unit, 说明, 覆盖, 方向, flips, anomalies}, ...] + baseline 信息。"""
    base = rescore(report_path)
    # 报告自带的读数（重算前的），仅供对照：基线翻转只跟重算值比
    try:
        recorded = (json.load(open(report_path, encoding="utf-8")).get("overall") or {})
    except Exception:  # noqa: BLE001
        recorded = {}
    base["recorded_correct"] = recorded.get("correct")
    base["recorded_rate"] = recorded.get("correctness_rate")
    base_ok = {r["id"]: bool(r["correct"]) for r in base["rows"]}
    out = []
    for unit, desc, cover, patches, direction in RULES:
        saved = _apply(patches)
        try:
            after = rescore(report_path)
        finally:
            _restore(saved)
        after_ok = {r["id"]: bool(r["correct"]) for r in after["rows"]}
        flips, anomalies = [], []
        for cid, ok in base_ok.items():
            if cid in after_ok and after_ok[cid] != ok:
                entry = {"id": cid, "before": ok, "after": after_ok[cid]}
                if (ok, after_ok[cid]) == (True, False):
                    flips.append(entry)
                else:
                    anomalies.append(entry)   # 放宽规则不应出现错→对（r24 除外，它整个就是错→对）
        out.append({"unit": unit, "desc": desc, "cover": cover, "direction": direction,
                    "n_flips": len(flips), "flips": [f["id"] for f in flips],
                    "anomalies": anomalies})
        print(f"  [{unit}] 翻转 {len(flips)} 处"
              + (f"；异常方向 {len(anomalies)} 处" if anomalies else ""), flush=True)
    return out, base


def _md(reports: list) -> str:
    lines = ["# comparator 放宽规则留一消融（7.5b B3，只产报告）", ""]
    for path, result, base in reports:
        n, correct = base["n"], base["correct"]
        rate = f"{base['correctness_rate']:.1f}" if base.get("correctness_rate") is not None else "?"
        lines += [f"## {os.path.basename(path)}", "",
                  f"- 重算基线：{correct}/{n}（{rate}%）；报告自带读数：{base.get('recorded_correct')} 题"
                  f"（{('%.1f' % base['recorded_rate']) if base.get('recorded_rate') is not None else '?'}%）。"
                  f"翻转只和重算基线比。",
                  f"- 题库指纹：报告 {base.get('evalset_report')} → 现在 {base.get('evalset_now')}"
                  + ("（同一版）" if base.get("evalset_report") == base.get("evalset_now") else "（**已换版**，翻转数仍相对本基线有效）"),
                  f"- 无结构化结果/还原失败沿用原判定的题：{len(base.get('skipped_no_obj') or [])}；"
                  f"基础设施失败：{len(base.get('infra_errors') or [])}。", "",
                  "| 规则 | 覆盖 | 方向 | 翻转数 | 翻转题号 |", "|---|---|---|---|---|"]
        for r in result:
            ids = ", ".join(r["flips"][:10]) + ("…" if len(r["flips"]) > 10 else "")
            lines.append(f"| {r['unit']} {r['desc']} | {r['cover']} | {r['direction']} "
                         f"| {r['n_flips']} | {ids} |")
        anomalies = [a for r in result for a in r["anomalies"]]
        lines += ["", f"异常方向翻转（放宽规则不应出现，逐条核对）：{len(anomalies)}"]
        for a in anomalies[:10]:
            lines.append(f"- {a['id']}: {a['before']} → {a['after']}")
        lines += ["", "内嵌分支不可消融（monkeypatch 关不掉，人工复核走 needs_audit 清单）：",
                  ", ".join(INLINE_RULES), "",
                  "### 承重判定（方案 §B3 口径）", "",
                  "- 翻转 ≥5 判承重，规则本体进 CHANGES 候选；1–4 的逐题人工复核（题号已列出）。", ""]
    lines += ["### CHANGES 候选清单（本批不改 comparator，攒给下一次断代）", ""]
    for path, result, base in reports:
        bearing = [f"{r['unit']} {r['desc']}（{r['n_flips']} 翻转，{'、'.join(r['flips'][:10] + (['…'] if len(r['flips']) > 10 else []))}）"
                   for r in result if r["n_flips"] >= 5]
        review = [f"{r['unit']} {r['desc']}（{r['n_flips']}）：{'、'.join(r['flips'])}"
                  for r in result if 0 < r["n_flips"] < 5]
        zero = [r["unit"] for r in result if r["n_flips"] == 0 and r["direction"] == "对→错"]
        lines += [f"**{os.path.basename(path)}**（基线 {base['correct']}/{base['n']}）：",
                  f"- 承重规则（翻转 ≥5，本体候选）：{bearing[0] if bearing else '无'}"
                  + ("".join(f"；{b}" for b in bearing[1:]) if len(bearing) > 1 else ""),
                  f"- 逐题人工复核（1–4 翻转）：{'；'.join(review) or '无'}",
                  f"- 零翻转：{', '.join(zero) or '无'}", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="comparator 规则留一消融（只产报告）")
    ap.add_argument("reports", nargs="+", help="评测报告 JSON（需带 actual_obj）")
    ap.add_argument("--md", help="Markdown 报告输出路径（不给则打 stdout）")
    ap.add_argument("--json", help="机器可读 JSON 输出路径")
    args = ap.parse_args(argv)

    done = []
    for path in args.reports:
        print(f"[rule_ablation] {path}", flush=True)
        result, base = _run(path)
        done.append((path, result, base))

    md = _md(done)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[rule_ablation] markdown → {args.md}")
    else:
        print(md)
    if args.json:
        payload = [{"report": p, "baseline": {"n": b["n"], "correct": b["correct"],
                                              "evalset_report": b.get("evalset_report"),
                                              "evalset_now": b.get("evalset_now")},
                    "rules": r} for p, r, b in done]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[rule_ablation] json → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
