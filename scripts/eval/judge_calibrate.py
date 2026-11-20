"""EV-B8 校准：judge vs 人工/比较器标注的一致率、Cohen's κ、混淆矩阵、弃权数。

用法（spec EV-B8 验收命令）：
    python scripts/eval/judge_calibrate.py --gold docs/eval/judge_gold.jsonl
    python scripts/eval/judge_calibrate.py --gold docs/eval/judge_gold.jsonl --limit 5   # 冒烟
    python scripts/eval/judge_calibrate.py --gold ... --out outputs/judge_cal.json       # 存档

上线判据（预登记，spec EV-B8 / phase7 E4）：
    κ ≥ 0.7 且 一致率 ≥ 90% 才允许启用；否则只记录不判定。
    退出码：0 = 达标可启用；1 = 未达标；2 = 有效样本不足（弃权+失败吃掉了太多分母）。

统计口径：
- 有效样本 = 非 abstain 且 confidence=high —— spec 原文"confidence=low 或 abstain 的样本
  不计入一致率分母，单列"。
- 一致率 = judge(pass) == label 的比例（有效样本内）。
- Cohen's κ 在有效样本上算：κ = (p_o - p_e) / (1 - p_e)，p_e 由混淆矩阵边缘推出。
  手写实现，不引 sklearn（仓库不背这个依赖）。
- 每条样本的明细写进 --out JSON，方便逐条复核 judge 说错了谁。
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, ".")  # 仓库根跑，保证 app.eval.judge 可导入

# .env 在 run_eval.py 是入口时自动加载；这个脚本直接跑，得自己加载——
# 不然 DATACHAT_JUDGE_* / DEEPSEEK_* 全空，模型名掉回 deepseek-chat、
# base_url 掉回 llm.py 的默认常量，连接错误。
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

JUDGE_THRESHOLD_KAPPA = 0.7
JUDGE_THRESHOLD_AGREE = 0.90


def rubric_of(row):
    """rubric 只从题面与 gold 现算（spec：不许把被评答案喂回去让它"解释"）。

    拒答类题（gold 是"无法回答：…"）契约特殊：正确回答 = 只拒答并给原因，
    parts = [f"题目：{row['question']}"]
    if row.get("note"):
        parts.append(f"口径说明：{row['note']}")
    拒答类题（gold 是"无法回答：…"）契约特殊：正确回答 = 只拒答并给原因，
    拒答之后继续输出替代性分析算错（第一轮校准 emp_022 就是这么判错的）——
    这层契约必须写进 rubric，否则 judge 只看"结论是拒答"就放行。
    """
    gold_text = row.get("gold_summary") or ""
    parts = [f"题目：{row['question']}"]
    if row.get("note"):
        parts.append(f"口径说明：{row['note']}")
    if gold_text.startswith("无法回答") or "无法回答" in gold_text[:20]:
        parts.append(
            "判定要求：这道题数据里缺必要字段，标准答案就是一句拒答说明。"
            "被评回答若明确拒答且原因与标准答案一致（缺同一字段），判 pass=true；"
            "但拒答之后还继续输出替代性分析或估算（如用别的字段凑答案），判 pass=false；"
            "若给出了编造的结论数值，判 pass=false。")
    else:
        parts.append(f"判定要求：被评回答的最终结论必须与标准答案一致（标准答案见下）。")
    return "\n".join(parts)


def kappa_2x2(cm):
    """cm = {(judge_pass, label): n}。二元 Cohen's κ。"""
    total = sum(cm.values())
    if total == 0:
        return None
    p_o = sum(n for (j, l), n in cm.items() if j == l) / total
    p_j = sum(n for (j, _), n in cm.items() if j) / total      # judge 判 pass 的比例
    p_l = sum(n for (_, l), n in cm.items() if l) / total      # 真实 pass 的比例
    p_e = p_j * p_l + (1 - p_j) * (1 - p_l)
    if p_e == 1:
        return 1.0 if p_o == 1 else 0.0
    return (p_o - p_e) / (1 - p_e)


def wilson_ci(k, n, z=1.96):
    """一致率的 Wilson score 置信区间。k=一致数，n=有效样本数。

    为什么用 Wilson 不用正态近似：n 小（校准集就几十条）时正态近似会跑出
    [0,1] 外或宽度失真，Wilson 在 p 靠近 0/1 时也表现正常。
    """
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, center - half), min(1.0, center + half))


def bootstrap_kappa_ci(pairs, n_boot=2000, seed=0):
    """κ 的 bootstrap 95% percentile 区间。pairs = [(judge_pass, label), ...]。

    为什么 bootstrap：κ 没有可闭式表达的方差（边缘比例的比），重抽样是仓库
    手写代码里最省事也最不引依赖的路。seed 固定 → 同输入必同输出（可复现，
    回放断言用）。手写 random.Random，不引 numpy（仓库不背这个依赖）。
    """
    if not pairs:
        return (None, None)
    import random
    rng = random.Random(seed)
    n = len(pairs)
    kappas = []
    for _ in range(n_boot):
        cm = Counter(pairs[rng.randrange(n)] for _ in range(n))
        k = kappa_2x2(cm)
        if k is not None:
            kappas.append(k)
    if not kappas:
        return (None, None)
    kappas.sort()
    lo = kappas[int(0.025 * len(kappas))]
    hi = kappas[min(len(kappas) - 1, int(0.975 * len(kappas)))]
    return (lo, hi)


def split_segments(details):
    """把有效样本拆成校准段 / 泛化段，各报 κ。

    拆法：先按 (label, idx) 稳定排序再交替分配——不是随机对半。排序保证两段的
    标签比例接近（一段全对、一段全错的分割会让段结论没意义）；idx 打散保证
    两段的采集时间 / 来源也混匀。方案 §1 B4：两段各过 κ ≥ 0.7 才算 judge 可用
    （防止 25 题小样本上 κ 的运气成分——单段 κ 可能被几条边样本顶上去）。
    """
    ordered = sorted(details, key=lambda d: (d["label"], d["idx"]))
    calib, gen = [], []
    for i, d in enumerate(ordered):
        (calib if i % 2 == 0 else gen).append(d)
    return calib, gen


def summarize(details):
    """从明细算全套统计：一致率+Wilson CI、κ+bootstrap CI、混淆矩阵。"""
    valid = [d for d in details if not d["abstain"] and d["confidence"] == "high"]
    cm = Counter((d["judge_pass"], d["label"]) for d in valid)
    n = len(valid)
    n_agree = sum(1 for d in valid if d["judge_pass"] == d["label"])
    agree = n_agree / n if n else None
    kap = kappa_2x2(cm)
    pairs = [(d["judge_pass"], d["label"]) for d in valid]
    w_lo, w_hi = wilson_ci(n_agree, n)
    b_lo, b_hi = bootstrap_kappa_ci(pairs)
    return {"n": n, "n_agree": n_agree, "agree": agree, "kappa": kap,
            "confusion": {f"{j}|{l}": c for (j, l), c in cm.items()},
            "agree_ci": [w_lo, w_hi], "kappa_ci": [b_lo, b_hi]}


def fmt_ci(ci):
    if ci is None or ci[0] is None:
        return "—"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="docs/eval/judge_gold.jsonl")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条（冒烟用）")
    ap.add_argument("--out", default=None, help="明细 JSON 输出路径")
    ap.add_argument("--segments", action="store_true",
                    help="拆校准/泛化两段各报 κ+CI，两段各过 κ≥0.7 才算达标（B4 口径）")
    ap.add_argument("--replay", default=None,
                    help="从上次 --out 的明细 JSON 重算统计（不调 judge、无需 Key）——"
                         "用来验证统计层本身与存档可复算")
    args = ap.parse_args()

    if args.replay:
        d = json.load(open(args.replay, encoding="utf-8"))
        details = d["details"]
        print(f"重算模式：{args.replay}（{d.get('gold', '?')}，{len(details)} 条明细，不调模型）")
        sys.exit(report(details, args.segments,
                        {"gold": d.get("gold"), "n": d.get("n", len(details)),
                         "failed": d.get("failed", 0), "fails": d.get("fails", []),
                         "elapsed_s": d.get("elapsed_s")}))

    rows = [json.loads(l) for l in open(args.gold, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[:args.limit]

    from app.eval.judge import JudgeError, judge, judge_model
    model = judge_model()
    print(f"judge 模型：{getattr(model, 'model_name', '?')}  样本 {len(rows)} 条  temp=0.0")

    details, fails = [], []
    t0 = time.time()
    for i, row in enumerate(rows):
        try:
            r = judge(row["question"], row["answer"], row["gold_summary"],
                      rubric_of(row), model=model, order=row["order"])
        except JudgeError as e:
            fails.append({"idx": i, "id": row["id"], "error": str(e)[:200]})
            print(f"  [{i+1}/{len(rows)}] {row['id']}  JudgeError: {str(e)[:80]}")
            continue
        details.append({"idx": i, "id": row["id"], "category": row.get("category"),
                        "label": row["label"], "judge_pass": r["pass"],
                        "confidence": r["confidence"], "abstain": r["abstain"],
                        "order": r["order"], "reason": r["reason"][:200],
                        "source": row.get("source")})
        mark = "✓" if (not r["abstain"] and r["confidence"] == "high" and r["pass"] == row["label"]) else "✗"
        print(f"  [{i+1}/{len(rows)}] {row['id']:10s} label={row['label']} judge={r['pass']} "
              f"conf={r['confidence']} abstain={r['abstain']} {mark}")

    sys.exit(report(details, args.segments,
                    {"gold": args.gold, "n": len(rows), "failed": len(fails),
                     "fails": fails, "elapsed_s": round(time.time() - t0, 1)},
                    out=args.out))


def report(details, segments, ctx, out=None):
    """算统计、打印、（可选）落盘、返回退出码。live 跑批与 --replay 共用一套口径。"""
    s = summarize(details)
    n_valid, agree, k = s["n"], s["agree"], s["kappa"]
    low_or_abstain = sum(1 for d in details if d["abstain"] or d["confidence"] != "high")

    print("\n===== 校准结果 =====")
    print(f"样本 {ctx['n']}：有效 {n_valid}  弃权/低置信 {low_or_abstain}  调用失败 {ctx['failed']}")
    if n_valid:
        cm = s["confusion"]
        print(f"混淆矩阵（judge, label）：TP={cm.get('True|True', 0)} FP={cm.get('True|False', 0)} "
              f"FN={cm.get('False|True', 0)} TN={cm.get('False|False', 0)}")
        print(f"一致率 {agree:.1%} {fmt_ci(s['agree_ci'])}   "
              f"Cohen's κ {k:.3f} {fmt_ci(s['kappa_ci'])}（bootstrap 95%）")
        gate_ok = k >= JUDGE_THRESHOLD_KAPPA and agree >= JUDGE_THRESHOLD_AGREE
        print(f"判据：κ ≥ {JUDGE_THRESHOLD_KAPPA} 且 一致率 ≥ {JUDGE_THRESHOLD_AGREE:.0%} → "
              + ("达标，可启用" if gate_ok else "未达标，只记录不判定"))
    else:
        gate_ok = False
        print("无有效样本，判不了。")

    seg_summary = None
    if segments:
        seg_summary = {}
        print("\n----- 校准段 / 泛化段（B4：两段各过 κ ≥ 0.7 才算可用） -----")
        segs_ok = True
        for name, seg in zip(("calibration", "generalization"), split_segments(details)):
            ss = summarize(seg)
            seg_summary[name] = ss
            if ss["n"] == 0:
                print(f"  {name:14s} 无有效样本")
                segs_ok = False
                continue
            seg_ok = ss["kappa"] >= JUDGE_THRESHOLD_KAPPA
            segs_ok = segs_ok and seg_ok
            print(f"  {name:14s} n={ss['n']:3d}  一致率 {ss['agree']:.1%} {fmt_ci(ss['agree_ci'])}  "
                  f"κ {ss['kappa']:.3f} {fmt_ci(ss['kappa_ci'])}  "
                  + ("过" if seg_ok else "不过"))
        if n_valid:
            gate_ok = gate_ok and segs_ok
            print("两段判据 → " + ("两段均过，judge 可用" if segs_ok else "至少一段未过，judge 不可用"))

    if out:
        payload = {"gold": ctx.get("gold"), "n": ctx["n"], "valid": n_valid,
                   "abstain_or_low": low_or_abstain, "failed": ctx["failed"],
                   "agree": agree, "agree_ci": s["agree_ci"], "kappa": k,
                   "kappa_ci": s["kappa_ci"],
                   "thresholds": {"kappa": JUDGE_THRESHOLD_KAPPA, "agree": JUDGE_THRESHOLD_AGREE},
                   "confusion": s["confusion"],
                   "details": details, "fails": ctx.get("fails", []),
                   "elapsed_s": ctx.get("elapsed_s")}
        if seg_summary is not None:
            payload["segments"] = seg_summary
        json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"明细已存 {out}")

    if not n_valid:
        return 2
    return 0 if gate_ok else 1


if __name__ == "__main__":
    main()
