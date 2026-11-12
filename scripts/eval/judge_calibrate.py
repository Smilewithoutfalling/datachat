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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="docs/eval/judge_gold.jsonl")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条（冒烟用）")
    ap.add_argument("--out", default=None, help="明细 JSON 输出路径")
    args = ap.parse_args()

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

    valid = [d for d in details if not d["abstain"] and d["confidence"] == "high"]
    low_or_abstain = [d for d in details if d["abstain"] or d["confidence"] != "high"]
    cm = Counter((d["judge_pass"], d["label"]) for d in valid)
    agree = (sum(1 for d in valid if d["judge_pass"] == d["label"]) / len(valid)) if valid else None
    k = kappa_2x2(cm)

    print("\n===== 校准结果 =====")
    print(f"样本 {len(rows)}：有效 {len(valid)}  弃权/低置信 {len(low_or_abstain)}  调用失败 {len(fails)}")
    if valid:
        print(f"混淆矩阵（judge, label）：TP={cm[(True, True)]} FP={cm[(True, False)]} "
              f"FN={cm[(False, True)]} TN={cm[(False, False)]}")
        print(f"一致率 {agree:.1%}   Cohen's κ {k:.3f}")
        print(f"判据：κ ≥ {JUDGE_THRESHOLD_KAPPA} 且 一致率 ≥ {JUDGE_THRESHOLD_AGREE:.0%} → "
              + ("达标，可启用" if (k >= JUDGE_THRESHOLD_KAPPA and agree >= JUDGE_THRESHOLD_AGREE) else "未达标，只记录不判定"))
    else:
        print("无有效样本，判不了。")

    if args.out:
        json.dump({"gold": args.gold, "n": len(rows), "valid": len(valid),
                   "abstain_or_low": len(low_or_abstain), "failed": len(fails),
                   "agree": agree, "kappa": k,
                   "thresholds": {"kappa": JUDGE_THRESHOLD_KAPPA, "agree": JUDGE_THRESHOLD_AGREE},
                   "confusion": {f"{j}|{l}": n for (j, l), n in cm.items()},
                   "details": details, "fails": fails,
                   "elapsed_s": round(time.time() - t0, 1)},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"明细已存 {args.out}")

    if not valid:
        sys.exit(2)
    sys.exit(0 if (k >= JUDGE_THRESHOLD_KAPPA and agree >= JUDGE_THRESHOLD_AGREE) else 1)


if __name__ == "__main__":
    main()
