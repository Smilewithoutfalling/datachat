"""构建 EV-B8 judge 的校准集 docs/eval/judge_gold.jsonl（40 条：20 对 / 20 错）。

样本来源：docs/eval/gate_*.json 历史闸门报告，人工判定（human_correct）优先，
为 null 时回退 auto_correct——auto 只是比较器参考，但拿到过人工判定的题不回退。

字段契约（与 judge.py / judge_calibrate.py 对齐）：
    id          题号
    source      报告文件名（可追溯到原始现场）
    label       人工判定（true=回答正确）
    question    题面
    note        题面口径说明（进 rubric）
    gold        判分用真值（kind + value / index+values）
    answer      被评回答（模型原文）
    order       gold_first / answer_first，交替分配 —— 消位置偏见
    salt        同题多实例的去重盐（answer 相同的实例只留一条）

rubric 由 judge_calibrate.py 从 question + note + gold 现算，不在样本里存
——存了就成了第二个真值来源，改题面时两处要同步，必漂。
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))  # 仓库根，_alt_values 要 import app

OUT = "docs/eval/judge_gold.jsonl"
N_POS, N_NEG = 20, 15
# N_NEG=15 偏离规格的"20 对 / 20 错"（spec EV-B8），原因写在 judge.md §样本量：
# 仓库内"判分语义清晰"的错样本只有 15 条——outputs 的旧报告 match 全 None
# 且实测有 label 与 answer/gold 矛盾的（ord_027 数值差 0.9% 标 True），
# gate 人工判 False 去重后恰 15 条。凑够 20 只能放宽过滤，等于给校准集灌标签噪声。
# 后续跑批累积新错样本（human 判 False 或 match 阶梯明确的 False）到 20 时改回。


def load_pool():
    """扫两个来源收 (题id, answer_sha) 维度的样本，人工判定优先，比较器兜底。

    来源 1：docs/eval/gate_*.json —— 闸门 25 题，human_correct 优先，null 回退 auto_correct。
    来源 2：outputs/eval_*.json —— 202 题能力面，correct 字段（比较器判定）。
            来源 2 没有"人工"层，但校准集的 label 语义是"这条回答事实上对/错"，
            比较器对这些题（数值/标签类）的判定与 gold 逐值比对，可信；
            infra 失败（error_kind=llm/dataset 或 infra_error 非空）不算模型错，排除。
    两来源都要求有结构化 gold/expected，否则写不出 rubric。
    """
    import hashlib
    pool = {}
    for f in sorted(glob.glob("docs/eval/gate_*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for c in d.get("cases", []):
            ans = (c.get("answer") or "").strip()
            if not ans or len(ans) < 8:
                continue
            h, a = c.get("human_correct"), c.get("auto_correct")
            label = True if h is True else (False if h is False else (None if a is None else bool(a)))
            if label is None:
                continue
            gold = c.get("gold") or {}
            if not (gold.get("kind") and (gold.get("value") is not None or gold.get("index"))):
                continue
            key = (c["id"], hashlib.sha256(ans.encode()).hexdigest()[:12])
            if key in pool:
                continue
            pool[key] = {"id": c["id"], "source": os.path.basename(f), "label": label,
                         "category": c.get("category"), "question": c["question"],
                         "note": c.get("note") or "", "gold": gold, "answer": ans}
    for f in sorted(glob.glob("outputs/eval_*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for c in d.get("cases", []):
            ans = (c.get("answer") or "").strip()
            if not ans or len(ans) < 8:
                continue
            # expected 字符串会被报告截断（~520 字符），series 必须用 expected_obj；
            # 两者都没有的题跳过——不完整的标准答案会让 judge 误判（实测 agg_005）。
            eobj = c.get("expected_obj")
            exp = c.get("expected")
            if eobj is None and exp is None:
                continue
            if c.get("correct") is None:
                continue
            if c.get("infra_error") or c.get("error_kind") in ("llm", "dataset"):
                continue  # 基础设施故障不是模型错，不进校准集
            # match 过滤（第一轮校准 82% 的教训，错分 7 条全是标签问题）：
            # - True 侧：宽容阶梯（scaled/extras/relaxed）放水过的 True 语义模糊
            #   （"数值不对但形态接近"也算对），只收 strict/rounded/refusal/impossible；
            # - False 侧：宽容阶梯救不回来的 False 就是真错。两种可信来源：
            #   ① 人工判定 human_correct=False（gate 报告，match=None 无所谓，人背书）；
            #   ② 比较器 False 且 match 非 None（新报告）。
            #   其余（旧报告 auto False，match=None 无人背书）排除——
            #   实测有 label 与 answer/gold 明显矛盾的（ord_027 数值差 0.9% 却标 True）。
            m = c.get("match")
            if bool(c["correct"]):
                if not m or m.split(":")[-1] not in ("strict", "rounded", "refusal", "impossible"):
                    continue
            else:
                if c.get("human_correct") is not False and m is None:
                    continue
            label = bool(c["correct"])
            key = (c["id"], hashlib.sha256(ans.encode()).hexdigest()[:12])
            if key in pool:
                continue
            if isinstance(eobj, dict) and eobj.get("kind") == "series":
                gold = eobj
            elif isinstance(eobj, dict) and eobj.get("value") is not None:
                gold = eobj
            else:
                gold = {"kind": "scalar", "value": exp}
            pool[key] = {"id": c["id"], "source": os.path.basename(f), "label": label,
                         "category": c.get("category"),
                         "question": c.get("question") or "", "note": "",
                         "gold": gold, "answer": ans,
                         "_alt_hit": bool(m and m.startswith("alt:"))}
    return pool


def gold_summary(gold):
    """gold → 给 judge 看的标准答案文本。

    series 给 index→value 逐行表；scalar 给值。
    注意必须用**完整**的真值：报告的 expected 字符串在 ~520 字符被截断（series 长表
    装不下，judge 会把截掉的部分判成"标准答案缺失"而误判），所以 series 一律从
    expected_obj（结构化、完整）构造，expected 字符串只兜 scalar。
    """
    if gold.get("kind") == "series":
        idx, vals = gold.get("index") or [], gold.get("values") or []

        def _lbl(x):
            if isinstance(x, dict):
                for k in ("t", "s", "v"):        # t=tuple 键、s=字符串键（report.py 的序列化约定）
                    if k in x:
                        return " / ".join(str(p) for p in x[k]) if isinstance(x[k], list) else str(x[k])
                return json.dumps(x, ensure_ascii=False)
            return str(x)

        rows = "\n".join(f"  {_lbl(i)}: {v}" for i, v in zip(idx, vals))
        name = gold.get("name") or "value"
        return f"一个 {len(idx)} 行的表（{name}），index → value：\n{rows}"
    return json.dumps(gold.get("value"), ensure_ascii=False)


def build(pool):
    pos = [v for v in pool.values() if v["label"]]
    neg = [v for v in pool.values() if not v["label"]]
    print(f"对样本 {len(pos)} 条 / 错样本 {len(neg)} 条（answer 去重后）")

    # 跨类别均匀：按 category 轮转取（同一类别里按 source 新到旧），避免校准集
    # 全是某一道题的形态——judge 在校准集上 90%，要在"整批题"上 90% 才算数。
    def pick(samples, n):
        by_cat = {}
        for v in sorted(samples, key=lambda x: x["source"], reverse=True):
            by_cat.setdefault(v.get("category") or "?", []).append(v)
        out = []
        while len(out) < n:
            progressed = False
            for cat in sorted(by_cat):
                if len(out) >= n:
                    break
                if by_cat[cat]:
                    out.append(by_cat[cat].pop(0))
                    progressed = True
            if not progressed:
                break
        return out[:n]

    sel_pos, sel_neg = pick(pos, N_POS), pick(neg, N_NEG)
    from collections import Counter
    print(f"选出：对 {len(sel_pos)}（类别 {dict(Counter(v['category'] for v in sel_pos))}）")
    print(f"       错 {len(sel_neg)}（类别 {dict(Counter(v['category'] for v in sel_neg))}）")
    if len(sel_pos) < N_POS or len(sel_neg) < N_NEG:
        print("样本不足 20/20 —— 把缺口报出来，不凑数", file=sys.stderr)
        sys.exit(1)

    rows = sel_pos + sel_neg
    out = []
    for i, v in enumerate(rows):
        gs = gold_summary(v["gold"])
        # alt 命中的样本（match=alt:strict 等）：模型答的是登记的替代合理答案
        # （实测 emp_025：全员均值 18580 也是合法答案，judge 只看主 gold 18631.53 必误判）。
        # 从用例定义现算全部 alt 值，列进标准答案文本——rubric 才完整。
        if v.get("_alt_hit"):
            alts = _alt_values(v["id"])
            if alts:
                gs += "\n其他同样正确的合理答案（口径歧义的登记变体）：\n" + \
                    "\n".join(f"  {a}" for a in alts)
        out.append({"id": v["id"], "source": v["source"], "label": v["label"],
                    "category": v.get("category"),
                    "question": v["question"], "note": v["note"], "gold": v["gold"],
                    "answer": v["answer"], "gold_summary": gs,
                    "order": "gold_first" if i % 2 == 0 else "answer_first"})
    return out


def _alt_values(case_id):
    """现算一道题全部 alt_ground_truths 的输出值（缺表或跑不动就返回空，不硬凑）。"""
    from app.eval.cases import ALL_CASES
    from app.eval.runner import EvalRunner
    case = next((c for c in ALL_CASES if c.id == case_id), None)
    if case is None or not case.alt_ground_truths:
        return []
    runner = EvalRunner()
    outs, _err = runner.expected_all(case)
    main, _e2 = runner._run_code(case.ground_truth, runner._gold_source(case))
    vals = []
    import json as _json
    for r in outs:
        s = _json.dumps(r, ensure_ascii=False, default=str)
        if _json.dumps(main, ensure_ascii=False, default=str) != s:
            vals.append(s[:200])
    return vals


def main():
    pool = load_pool()
    rows = build(pool)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_pos = sum(1 for r in rows if r["label"])
    print(f"写入 {OUT}: {len(rows)} 条（对 {n_pos} / 错 {len(rows) - n_pos}）")


if __name__ == "__main__":
    main()
