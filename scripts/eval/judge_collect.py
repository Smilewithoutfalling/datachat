"""EV-B8 B4：judge 校准集扩容——待人标候选采集 + 人工入库（两步，人不缺席）。

方案红线（phase75b §1 B4 / §2 第 4 条）：不一致样本**不自动入库**——
本脚本只负责①把候选从报告里筛出来、按信息量排序、写成人标清单；
②人标完（label 字段填 true/false）后 --ingest --confirm 合并进 judge_gold.jsonl。

为什么候选口径比 build_judge_gold 宽：
    build_judge_gold 只收"判分语义清晰"的样本进**校准集**（strict/rounded 的 True、
    有人背书的 False），为的是标签零噪声。本脚本的目的是把**标签语义模糊**的样本
    （宽容阶梯放水过的 True、alt 变体命中、闸门上人工与比较器逆反的）端到人面前——
    这些恰恰是 judge 与 comparator 最可能不一致、人标价值最大的地方（B4 采样源）。
    人标后它们才成为库里的可信样本：人给了 label，样本就不再模糊。

优先级（信息量从大到小）：
    P0 闸门题 human_correct 与 auto_correct 逆反——两把尺子当面打架，必须人裁；
    P1 match 层级 scaled/extras/relaxed（被宽容放水过的 True）或 alt: 前缀（歧义变体）；
    P2 strict/rounded/refusal/impossible 的 True（清晰对）；
    P3 比较器 False 且 match 非 None（清晰错）。

用法：
    python scripts/eval/judge_collect.py                      # 采集 → outputs/judge_candidates.jsonl
    python scripts/eval/judge_collect.py --target 120 --out x.jsonl
    # …人标：在清单每行填 "label": true / false…
    python scripts/eval/judge_collect.py --ingest x.jsonl            # 干跑：只报将入库几条
    python scripts/eval/judge_collect.py --ingest x.jsonl --confirm  # 真写进 docs/eval/judge_gold.jsonl

无 Key 即可跑（采集只读报告文件）；judge 本身的校准跑批在 judge_calibrate.py，那步要 Key。
"""
import argparse
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

GOLD_PATH = os.path.join("docs", "eval", "judge_gold.jsonl")
GATE_GLOB = os.path.join("docs", "eval", "gate_*.json")
OUT_GLOB = os.path.join("outputs", "eval_*.json")

# strict 一侧的 match 尾段（与 build_judge_gold 同词表）
_STRICT_KINDS = ("strict", "rounded", "refusal", "impossible")
_SOFT_KINDS = ("scaled", "extras", "relaxed")


def _sha12(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def load_pool_wide(gate_glob=GATE_GLOB, out_glob=OUT_GLOB, exclude=None):
    """扫闸门 + 能力面报告收候选（answer 去重）。exclude={(id, answer_sha12)} 已入库跳过。

    与 build_judge_gold.load_pool 的差别：**收模糊样本**（soft match 的 True、alt 命中、
    闸门人工逆反），每条带 priority；infra 失败 / 缺 expected 的排除口径不变。
    """
    exclude = exclude or set()
    pool = {}
    for f in sorted(glob.glob(gate_glob)):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for c in d.get("cases", []):
            ans = (c.get("answer") or "").strip()
            if not ans or len(ans) < 8:
                continue
            h, a = c.get("human_correct"), c.get("auto_correct")
            if h is None and a is None:
                continue
            gold = c.get("gold") or {}
            if not (gold.get("kind") and (gold.get("value") is not None or gold.get("index"))):
                continue
            key = (c["id"], _sha12(ans))
            if key in exclude or key in pool:
                continue
            # P0：两把尺子打架（人工 vs 比较器逆反）。没打架的按 auto 给建议标签。
            clash = h is not None and a is not None and bool(h) != bool(a)
            pool[key] = {
                "id": c["id"], "source": os.path.basename(f),
                "question": c["question"], "note": c.get("note") or "",
                "gold": gold, "answer": ans,
                "category": c.get("category"),
                "comparator_correct": bool(a),
                "match": None, "alt_hit": False,
                "priority": 0 if clash else 3,
                "clash": clash,
                "suggested_label": bool(h) if h is not None else bool(a),
            }
    for f in sorted(glob.glob(out_glob)):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for c in d.get("cases", []):
            ans = (c.get("answer") or "").strip()
            if not ans or len(ans) < 8:
                continue
            eobj, exp = c.get("expected_obj"), c.get("expected")
            if eobj is None and exp is None:
                continue
            if c.get("correct") is None:
                continue
            if c.get("infra_error") or c.get("error_kind") in ("llm", "dataset"):
                continue
            m = c.get("match") or ""
            tail = m.split(":")[-1] if m else None
            kind = m.split(":")[0] if m else None
            if bool(c["correct"]):
                if not tail:
                    continue  # 旧报告 match=None 的 True 无人背书，不收（build_judge_gold 同口径）
                if tail in _SOFT_KINDS:
                    pr = 1          # 宽容放水过的 True：语义模糊，judge 最可能翻
                elif tail in _STRICT_KINDS:
                    pr = 2
                else:
                    continue
            else:
                if m is None or m == "":
                    continue  # 旧报告无人背书的 False，同口径排除
                pr = 3 if not kind or kind != "alt" else 1
            key = (c["id"], _sha12(ans))
            if key in exclude or key in pool:
                continue
            if isinstance(eobj, dict) and (eobj.get("kind") == "series" or eobj.get("value") is not None):
                gold = eobj
            else:
                gold = {"kind": "scalar", "value": exp}
            pool[key] = {
                "id": c["id"], "source": os.path.basename(f),
                "question": c.get("question") or "", "note": "",
                "gold": gold, "answer": ans,
                "category": c.get("category"),
                "comparator_correct": bool(c["correct"]),
                "match": m, "alt_hit": bool(kind == "alt"),
                "priority": pr, "clash": False,
                "suggested_label": bool(c["correct"]),
            }
    return pool


def _alt_values(case_id):
    """与 build_judge_gold._alt_values 同源：现算一道题全部 alt 值。缺表/跑不动返回空。"""
    from app.eval.cases import ALL_CASES
    from app.eval.runner import EvalRunner
    case = next((c for c in ALL_CASES if c.id == case_id), None)
    if case is None or not case.alt_ground_truths:
        return []
    runner = EvalRunner()
    outs, _err = runner.expected_all(case)
    main, _e2 = runner._run_code(case.ground_truth, runner._gold_source(case))
    vals = []
    for r in outs:
        s = json.dumps(r, ensure_ascii=False, default=str)
        if json.dumps(main, ensure_ascii=False, default=str) != s:
            vals.append(s[:200])
    return vals


def collect(target, gate_glob=GATE_GLOB, out_glob=OUT_GLOB, gold_path=GOLD_PATH):
    """返回 (候选行列表, 池统计)。行含 gold_summary，可直接人标。"""
    from scripts.eval.build_judge_gold import gold_summary

    done = set()
    if os.path.exists(gold_path):
        for line in open(gold_path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                done.add((r["id"], _sha12(r["answer"])))
    pool = load_pool_wide(gate_glob, out_glob, exclude=done)
    # 轮转取：P0 全收后，P1/P2/P3 轮流补齐——校准集需要对/错两侧、清晰/模糊两侧
    # 都有代表，100 条全落在"模糊 True"上会让 judge 只学会放行。
    by_pr = {}
    for v in sorted(pool.values(), key=lambda x: (x["priority"], x["id"])):
        by_pr.setdefault(v["priority"], []).append(v)
    if not target:
        picked = [v for pr in sorted(by_pr) for v in by_pr[pr]]
    else:
        picked = by_pr.get(0, [])[:target]
        others = [pr for pr in sorted(by_pr) if pr != 0]
        rest = target - len(picked)
        share = max(1, rest // len(others)) if others else 0
        for pr in others:
            if len(picked) >= target:
                break
            picked.extend(by_pr[pr][:share])
        while len(picked) < target:
            progressed = False
            for pr in others:
                if len(picked) >= target:
                    break
                bucket = by_pr[pr]
                if bucket:
                    picked.append(bucket.pop(0))
                    progressed = True
            if not progressed:
                break
    rows = picked
    out = []
    for v in rows:
        gs = gold_summary(v["gold"])
        if v["alt_hit"]:
            alts = _alt_values(v["id"])
            if alts:
                gs += "\n其他同样正确的合理答案（口径歧义的登记变体）：\n" + \
                     "\n".join(f"  {a}" for a in alts)
        out.append({
            "id": v["id"], "source": v["source"], "question": v["question"],
            "note": v["note"], "gold": v["gold"], "answer": v["answer"],
            "gold_summary": gs, "category": v["category"],
            "comparator_correct": v["comparator_correct"], "match": v["match"],
            "priority": v["priority"], "clash": v["clash"],
            "suggested_label": v["suggested_label"],
            "label": None,  # 人标填 true / false
        })
    stats = {"pool": len(pool), "already_in_gold": len(done), "picked": len(out),
             "by_priority": {}}
    for v in pool.values():
        stats["by_priority"][v["priority"]] = stats["by_priority"].get(v["priority"], 0) + 1
    return out, stats


def ingest(cand_path, gold_path=GOLD_PATH, confirm=False):
    """把人标过的候选合并进 judge_gold.jsonl。返回 (拟入库, 跳过, 库内现有)。

    人标闸：label 非 true/false 的行**拒绝**——宁缺勿错（方案红线 4）。
    order 接续库里现有行数交替分配，防位置偏。
    """
    existing = []
    if os.path.exists(gold_path):
        existing = [json.loads(l) for l in open(gold_path, encoding="utf-8") if l.strip()]
    done = {(r["id"], _sha12(r["answer"])) for r in existing}

    cands = [json.loads(l) for l in open(cand_path, encoding="utf-8") if l.strip()]
    accepted, skipped = [], []
    for c in cands:
        if c.get("label") not in (True, False):
            skipped.append((c["id"], "label 未人标"))
            continue
        key = (c["id"], _sha12(c["answer"]))
        if key in done:
            skipped.append((c["id"], "已在库（answer 相同）"))
            continue
        done.add(key)
        i = len(existing) + len(accepted)
        accepted.append({
            "id": c["id"], "source": c["source"], "label": bool(c["label"]),
            "category": c.get("category"), "question": c["question"],
            "note": c.get("note") or "", "gold": c.get("gold") or {},
            "answer": c["answer"], "gold_summary": c["gold_summary"],
            "order": "gold_first" if i % 2 == 0 else "answer_first",
            "human_labeled": True,   # 人标样本与比较器推论标签可区分（来源追溯）
        })
    if confirm and accepted:
        with open(gold_path, "a", encoding="utf-8", newline="\n") as f:
            for r in accepted:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return accepted, skipped, existing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100, help="候选目标条数（0=全收）")
    ap.add_argument("--out", default=os.path.join("outputs", "judge_candidates.jsonl"))
    ap.add_argument("--ingest", default=None, help="人标后的候选文件（干跑）")
    ap.add_argument("--confirm", action="store_true", help="与 --ingest 连用：真写库")
    args = ap.parse_args()

    if args.ingest:
        accepted, skipped, existing = ingest(args.ingest, confirm=args.confirm)
        print(f"库里现有 {len(existing)} 条；本次拟入库 {len(accepted)} 条；跳过 {len(skipped)} 条")
        for sid, why in skipped[:20]:
            print(f"  跳过 {sid}：{why}")
        n_pos = sum(1 for a in accepted if a["label"])
        print(f"拟入库分布：对 {n_pos} / 错 {len(accepted) - n_pos}")
        if not args.confirm:
            print("干跑——加 --confirm 才真写。")
        else:
            print(f"已追加进 {GOLD_PATH}。校准集现共 {len(existing) + len(accepted)} 条。")
        sys.exit(0)

    rows, stats = collect(args.target)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"池 {stats['pool']} 条（已入库 {stats['already_in_gold']} 排除后）；选出 {len(rows)} 条 → {args.out}")
    print("按优先级分布（P0 逆反 / P1 模糊 / P2 清晰对 / P3 清晰错）：")
    from collections import Counter
    picked = Counter(r["priority"] for r in rows)
    for p in sorted(stats["by_priority"]):
        print(f"  P{p}: 池内 {stats['by_priority'][p]} 条，选出 {picked.get(p, 0)} 条")
    unlabeled = sum(1 for r in rows if r["label"] is None)
    print(f"待人标 {unlabeled} 条——每行填 \"label\": true/false 后用 --ingest 入库。")


if __name__ == "__main__":
    main()
