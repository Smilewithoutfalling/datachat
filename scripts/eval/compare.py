"""比较两份评测报告的逐题判定：Δ / 翻转 / McNemar p / 判对层级迁移。

用法：
    python scripts/eval/compare.py A.json B.json [--alpha 0.05] [--json OUT]

只读 JSON，不调模型、不 import 被测系统。同一种子同一份文件传两次必须得出
Δ=0、翻转 0:0、p=1.0 —— 这是这个脚本唯一能自证没算错的方式（规格 §8 批 0）。

## 为什么不用报告里记的 `correct` 当基准

报告里的 `correct` 是**生成它的那一刻**那把尺子的产物。判分器改过之后，
两份报告记录值之间的差可能全部来自尺子，而不是模型。这不是假设：2026-11-03
修规则 16 时，13 份老报告在 `git stash` 前后逐题判定**一模一样**，说明当时
"有 6 道题翻正"的印象完全来自基准取错。要回答"改动有没有影响"，
只能同一份代码状态把双方都重算一遍再比（`run_eval.py --rescore`）。

## 判定取哪一个字段

闸门报告人判优先于比较器：`human_correct` → `correct` → `auto_correct`。
比较器的结论只做参考，规格 §1.2 明说"不要动这套语义"。每份报告的判定来源
都会打印出来，混着用时读者能看见。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval.outcome import STRICT_TIER, build as build_outcome, tier_of  # noqa: E402
from app.eval.report_adapter import ReportError, load as load_json, verdict_of  # noqa: E402
from app.eval.stats import mcnemar_exact, mde_flips  # noqa: E402

# 可比性逐项。顺序即输出顺序。
# 规格 §EV-B1 只写 prompt/evalset/model 三项，这里多一项 `agent`：
# 实测传错过一次 —— react 报告比 workflow 报告，三项全 yes（两边 model 相同、
# 都没有 prompt/evalset 指纹），脚本兴高采烈地报了个"Δ -10.0pp"。
# 两个执行器根本不是同一个被测对象，这比 model 换掉还严重。
COMPARABLE_KEYS = ("prompt_sha12", "evalset_sha12", "model", "agent")


def load_report(path: str) -> dict:
    """读一份报告并归一成 `{rows, outcome, meta}`。"""
    data = load_json(path)
    if "runs" in data and "cases" not in data:
        raise ReportError(
            f"{path}: 这是 *_summary.json（只有 runs[]），请传它引用的那份 run 报告"
        )
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ReportError(f"{path}: 没有 cases 逐题行")

    rows: dict[str, dict] = {}
    sources = Counter()
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise ReportError(f"{path}: cases[{i}] 不是对象")
        cid = c.get("id")
        if not cid:
            raise ReportError(f"{path}: cases[{i}] 没有 id，无法配对")
        if cid in rows:
            raise ReportError(f"{path}: id={cid} 重复出现，无法配对")

        ok, source = verdict_of(c)
        sources[source] += 1
        rows[cid] = {
            "correct": ok,
            "source": source,
            "match": c.get("match") if ok else None,
            "category": c.get("category"),
            "dataset": c.get("dataset"),
        }

    # 有 outcome 块就用它（报告 v2）；没有就现算 —— 旧报告与闸门报告都走这条。
    outcome = data.get("outcome")
    if not isinstance(outcome, dict):
        outcome = build_outcome(
            [{**r, "id": cid} for cid, r in rows.items()]
        )

    return {
        "path": path,
        "meta": {
            "model": data.get("model"),
            "agent": data.get("agent"),
            "temperature": data.get("temperature"),
            "git_sha": data.get("git_sha"),
            "schema_version": data.get("schema_version", 1),
            "prompt_sha12": _dig(data, "prompt_sha12"),
            "evalset_sha12": _dig(data, "evalset_sha12") or _evalset_from_block(data),
            # 跑模型时那把尺子 vs 现在这把。不同 = 这份报告的判定被 --rescore 重算过。
            "run_code_sha12": data.get("run_code_sha12"),
            "code_sha12": _dig(data, "code_sha12"),
        },
        "rows": rows,
        "sources": dict(sources),
        "outcome": outcome,
    }


def _dig(data: dict, key: str):
    fp = data.get("fingerprints")
    return fp.get(key) if isinstance(fp, dict) else None


def _evalset_from_block(data: dict):
    """老报告没有 `fingerprints`，但顶层 `evalset` 里有 sha256（若存在）。"""
    ev = data.get("evalset")
    if isinstance(ev, dict) and isinstance(ev.get("sha256"), str):
        return ev["sha256"][:12]
    return None


def comparable(a: dict, b: dict) -> dict:
    """三项逐项 yes/no；缺失记 None（不是 no，也不是 yes）。"""
    fields = {}
    diffs, unknown = [], []
    for key in COMPARABLE_KEYS:
        x, y = a["meta"].get(key), b["meta"].get(key)
        if x is None or y is None:
            fields[key] = None
            unknown.append(key)
        elif x == y:
            fields[key] = True
        else:
            fields[key] = False
            diffs.append(key)
    return {
        "fields": fields,
        "ok": not diffs and not unknown,
        "diffs": diffs,
        "unknown": unknown,
        # 顺序要紧：**确定的差异**压过"没数据"。model 明确不同时就是不可比，
        # 不能因为 prompt 指纹缺失退回"不知道"——那是拿一个缺失项掩盖一个已知差异。
        "verdict": "different" if diffs else ("legacy" if unknown else "ok"),
    }


def _source_mix(a: dict, b: dict, common: list[str]) -> dict:
    """两边判定来源不同的题 —— 混源时准确率差不是模型差。

    2026-11-03 实测踩到：`gate_20261013_151425_react.json` 的人工字段全空，
    判定落到 `auto_correct`；`gate_20261014_162428_react.json` 人工填满了。
    两份一比，96.0% → 92.0% 看着像"退步 4pp"，实际比的是
    "比较器结论 vs 人工结论"，跟模型没有关系。不拦这个，脚本就是在
    把错的基准包装成结论。
    """
    mismatch = [cid for cid in common if a["rows"][cid]["source"] != b["rows"][cid]["source"]]
    return {
        "a": dict(a["sources"]),
        "b": dict(b["sources"]),
        "mismatch_n": len(mismatch),
        "mismatch_ids": mismatch[:20],
        "mixed": bool(mismatch),
    }


def compare(a: dict, b: dict, *, alpha: float = 0.05) -> dict:
    ids_a, ids_b = set(a["rows"]), set(b["rows"])
    common = sorted(ids_a & ids_b)
    if not common:
        raise ReportError("两份报告没有共同题号，无法配对比较")

    na = sum(1 for i in common if a["rows"][i]["correct"])
    nb = sum(1 for i in common if b["rows"][i]["correct"])

    # 只有两边都判完了才算配对；待判的题单独记，不混进 b/c。
    b_only = c_only = pending = 0
    flips: list[dict] = []
    tier_moves = Counter()
    for cid in common:
        ra, rb = a["rows"][cid], b["rows"][cid]
        va, vb = ra["correct"], rb["correct"]
        if va is None or vb is None:
            pending += 1
            continue
        if not va and vb:
            b_only += 1
        elif va and vb:
            # 层级迁移只在"两边都判对"时有意义：判错的题没有层级。
            ta, tb = tier_of(ra), tier_of(rb)
            if ta != tb:
                tier_moves[(ta or "unknown", tb or "unknown")] += 1
        elif va and not vb:
            c_only += 1
        if va != vb:
            flips.append({"id": cid, "a": va, "b": vb,
                          "category": ra.get("category"), "dataset": ra.get("dataset")})

    p = mcnemar_exact(b_only, c_only)
    k_mde = mde_flips(alpha)
    n = len(common)
    delta_pp = round(100.0 * (nb - na) / n, 1)

    return {
        "comparable": comparable(a, b),
        "source_mix": _source_mix(a, b, common),
        "n_common": n,
        "only_a": sorted(ids_a - ids_b),
        "only_b": sorted(ids_b - ids_a),
        "a": {"correct": na, "accuracy": round(100.0 * na / n, 1)},
        "b": {"correct": nb, "accuracy": round(100.0 * nb / n, 1)},
        "delta_pp": delta_pp,
        "flips": {"b_only": b_only, "c_only": c_only, "pending": pending, "cases": flips},
        "mcnemar_p": round(p, 4),
        "alpha": alpha,
        "mde_flips": k_mde,
        "mde_equiv_pp": round(100.0 * k_mde / n, 1),
        "significant": p < alpha,
        "tier": _tier_block(a["outcome"], b["outcome"], tier_moves),
        "conclusion": _conclusion(n, delta_pp, p, alpha, k_mde, b_only, c_only, pending),
    }


def _tier_block(oa: dict, ob: dict, moves: Counter) -> dict:
    sa, sb = oa.get("strict_rate"), ob.get("strict_rate")
    return {
        "strict_a": oa.get("strict"),
        "strict_b": ob.get("strict"),
        "strict_rate_a": sa,
        "strict_rate_b": sb,
        "delta_pp": None if sa is None or sb is None else round(sb - sa, 1),
        "moves": {f"{x}->{y}": k for (x, y), k in sorted(moves.items())},
        # 严格率算不出来时，原因必须写出来，否则读者会以为"这批没有放宽"。
        "note": _tier_note(oa, ob),
    }


def _tier_note(oa: dict, ob: dict) -> str | None:
    missing = []
    for name, o in (("A", oa), ("B", ob)):
        if o.get("strict_rate") is None:
            why = ("全部答错，分母为 0" if not o.get("correct")
                   else f"{o.get('unknown_tier', 0)} 题判对但报告没记层级")
            missing.append(f"{name}: {why}")
    return "；".join(missing) if missing else None


def _conclusion(n, delta_pp, p, alpha, k_mde, b_only, c_only, pending) -> str:
    if b_only == 0 and c_only == 0:
        head = f"在 {n} 题上逐题判定完全一致" + ("（含待判题，未计入配对）" if pending else "")
        return head + "，没有任何翻转。"

    sign = "+" if delta_pp > 0 else ""
    move = f"{b_only} 题错→对、{c_only} 题对→错，净 {sign}{delta_pp}pp"
    if n < k_mde:
        # 3 道题上要 6 个翻转才显著 —— 不是"差异小"，是这套设计永远测不出来。
        return (
            f"{move}；n={n} 小于 MDE 所需的 {k_mde} 个单向翻转，"
            f"**无论怎么翻都不可能显著**（p={p:.4f}）。这批题只能看逐题，不能看统计量。"
        )
    if p < alpha:
        return f"{move}；McNemar p={p:.4f} < α={alpha}，差异显著。仍需人工抽审翻转题确认不是判分器放宽。"
    return (
        f"{move}；McNemar p={p:.4f} ≥ α={alpha}，**不显著**。"
        f"在 n={n} 上要达到 p<{alpha} 需要 {k_mde} 个单向翻转（≈{round(100.0 * k_mde / n, 1)}pp），"
        f"本次差异小于可检出量，不能宣称改进或退化。"
    )


_SOURCE_LABEL = {
    "human_correct": "人判",
    "auto_correct": "比较器",
    "correct": "报告记录",
    "pending": "待判",
}


def _fmt_sources(src: dict) -> str:
    return "　".join(f"{_SOURCE_LABEL.get(k, k)} {v} 题" for k, v in sorted(src.items()))


def format_report(res: dict, a_path: str, b_path: str) -> str:
    comp = res["comparable"]
    lines = [f"A: {a_path}", f"B: {b_path}", ""]

    mark = {True: "yes", False: "NO", None: "缺"}
    lines.append("可比性：" + "　".join(f"{k}={mark[v]}" for k, v in comp["fields"].items())
                 + f"　→ {comp['verdict']}")
    if comp["diffs"]:
        lines.append(f"  不同：{', '.join(comp['diffs'])} —— 分数差异不能归因于单次改动")
    if comp["unknown"]:
        lines.append(f"  缺失：{', '.join(comp['unknown'])} —— 只能说'不能声称可比'，不能说'不可比'")

    sm = res["source_mix"]
    if sm["mixed"]:
        lines.append(
            f"判定来源：**{sm['mismatch_n']} 题两边来源不同**"
            f"（A {_fmt_sources(sm['a'])} / B {_fmt_sources(sm['b'])}）"
            f" —— 下面的准确率差混合了判定方式，不能读成模型差异"
        )
    else:
        lines.append(f"判定来源：{_fmt_sources(sm['a'])}（两边一致）")

    lines.append(f"准确率：A {res['a']['accuracy']}% ({res['a']['correct']}/{res['n_common']})"
                 f" → B {res['b']['accuracy']}% ({res['b']['correct']}/{res['n_common']})"
                 f"，Δ {res['delta_pp']:+.1f}pp")

    f = res["flips"]
    pend = f"，{f['pending']} 题待判未计入" if f["pending"] else ""
    unreachable = "" if res["n_common"] >= res["mde_flips"] else f"，多于题目数 {res['n_common']}，不可达"
    lines.append(f"配对：B 对 A 错 {f['b_only']} 题，A 对 B 错 {f['c_only']} 题，"
                 f"McNemar p={res['mcnemar_p']}"
                 f"（{'显著' if res['significant'] else '不显著'}；"
                 f"MDE={res['mde_flips']} 个单向翻转 ≈{res['mde_equiv_pp']}pp{unreachable}）{pend}")

    t = res["tier"]
    if t["strict_rate_a"] is None or t["strict_rate_b"] is None:
        lines.append("判对层级：不可比 —— " + (t["note"] or ""))
    else:
        lines.append(f"判对层级：strict {t['strict_a']}/{res['a']['correct']} ({t['strict_rate_a']}%)"
                     f" → {t['strict_b']}/{res['b']['correct']} ({t['strict_rate_b']}%)"
                     f"，Δ {t['delta_pp']:+.1f}pp")
        if t["moves"]:
            lines.append("  层级迁移：" + "　".join(f"{k} {v} 题" for k, v in t["moves"].items()))

    if res["only_a"] or res["only_b"]:
        seg = []
        for name, ids in (("仅 A 有", res["only_a"]), ("仅 B 有", res["only_b"])):
            if not ids:
                continue
            shown = ", ".join(ids[:6]) + ("…" if len(ids) > 6 else "")
            seg.append(f"{name} {len(ids)} 题（{shown}）")
        lines.append("题集不同：" + "，".join(seg) + "。配对只在交集上做。")

    lines.append("")
    lines.append("结论：" + res["conclusion"])

    # 三种情况下上面的 Δ / p 都不成立。分开写会让读者只记住最后一个，
    # 所以合成一条，把所有失效条件一起摆出来。
    warnings = []
    if comp["verdict"] == "different":
        warnings.append(f"{'、'.join(comp['diffs'])} 不同 —— 这不是同一配置下的两次运行")
    if res["source_mix"]["mixed"]:
        warnings.append(
            f"{res['source_mix']['mismatch_n']} 题的判定一边来自比较器、一边来自人判"
            "（先把人工字段填齐，或都用同一把尺子重判）"
        )
    if warnings:
        lines.append("⚠️ 上面这行不作数：" + "；".join(warnings) + "。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="比较两份评测报告的逐题判定")
    ap.add_argument("a", help="基准报告 JSON")
    ap.add_argument("b", help="对比报告 JSON")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平，默认 0.05")
    ap.add_argument("--json", dest="json_out", help="把结果写进这个文件")
    args = ap.parse_args(argv)

    try:
        a = load_report(args.a)
        b = load_report(args.b)
        res = compare(a, b, alpha=args.alpha)
    except ReportError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    res["_paths"] = {"a": args.a, "b": args.b}
    print(format_report(res, args.a, args.b))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
