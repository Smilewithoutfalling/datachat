"""C-013 配对探针：先找到「不带信号时模型真的会反问」的口径作答，再用同一句挂在信号下复跑。

第一版（probe_c013.py）里 T2' 没反问 —— 因为「实付金额合计」本身够明确，模型的自由裁量
就不想问，反事实看不见。要证明 prev_clarify 是**因果**而不是伴随，必须配对：
同一句 question，prev_clarify=False 反问 / True 不反问。

候选句都用「上一轮在问销售额口径」的语境，是用户真会说的话，不是构造的病句。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

from app.core import LLMConfig, analyze
from app.eval.cases import DATASETS

ORDERS = DATASETS["orders"]
CFG = LLMConfig.from_env()

Q1 = "这些订单的销售额怎么样？"
CANDIDATES = ["都行，你定", "两个都看", "你觉得该怎么算"]


def run(tag, question, prev_clarify):
    res = analyze(ORDERS, question, agent="workflow", llm_config=CFG,
                  memory_mode="off", history=None, prev_clarify=prev_clarify, log=False)
    rec = {
        "question": question,
        "prev_clarify": prev_clarify,
        "clarify": bool(getattr(res, "clarify", False)),
        "executed": bool(getattr(res, "executed", False)),
        "error_kind": getattr(res, "error_kind", None),
        "answer": (res.answer or "")[:300],
    }
    print(f"[{tag}] clarify={rec['clarify']} executed={rec['executed']} err={rec['error_kind']}  Q={question} (prev={prev_clarify})")
    print(f"      A: {rec['answer'][:150].replace(chr(10), ' ')}")
    return rec


out = {}
r1 = run("T1", Q1, False)
out["T1"] = r1

# 第一遍：不带信号，找会反问的那句
hits = []
for i, q in enumerate(CANDIDATES):
    rec = run(f"cand{i}", q, False)
    out[f"cand{i}"] = rec
    if rec["clarify"]:
        hits.append(q)

print("\n不带信号时会反问的候选：", hits)

# 第二遍：对命中的那句，挂上信号（T1 真的反问了才挂，否则等于伪造）
paired = []
for i, q in enumerate(hits):
    rec = run(f"paired{i}", q, r1["clarify"])
    out[f"paired{i}"] = rec
    paired.append({"question": q, "clarify_without": True, "clarify_with": rec["clarify"],
                   "executed_with": rec["executed"]})

out["_summary"] = {
    "T1_clarify": r1["clarify"],
    "candidates_that_clarify": hits,
    "paired": paired,
    "causality_ok": bool(paired) and all(not p["clarify_with"] for p in paired),
}

os.makedirs("outputs", exist_ok=True)
path = "outputs/probe_c013_pair_1116.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("saved", path)
print("causality_ok =", out["_summary"]["causality_ok"])
