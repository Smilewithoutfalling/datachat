"""EV-B6 真模型冒烟（规格：80 次全量太贵，先 5 条）。

基线 agg_001 + 4 种变体（total_row / merged_header / two_row_header / date_compact），
各跑一次真模型，产出一份 decay.py 能直接读的报告。
"""
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

from app.eval.cases import ALL_CASES  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402
from app.core.llm import LLMConfig  # noqa: E402

PERT = os.path.join(REPO, "outputs", "perturb")
base = [c for c in ALL_CASES if c.id == "agg_001"][0]


def variant(kind):
    from app.eval.case_model import EvalCase
    return EvalCase(id=f"smoke_{kind}", category=base.category,
                    question=base.question, ground_truth=base.ground_truth,
                    keywords=base.keywords,
                    dataset=os.path.join(PERT, f"agg_001.{kind}.dirty.csv"),
                    gold_dataset=os.path.join(PERT, f"agg_001.{kind}.clean.csv"),
                    variant_of="agg_001", variant_kind=kind)


cases = [base] + [variant(k) for k in ("total_row", "merged_header", "two_row_header", "date_compact")]
runner = EvalRunner(agent="react", llm_config=LLMConfig.from_env())
rows = []
for c in cases:
    t0 = time.time()
    r = runner.run_single(c)
    print(f"{c.id}: correct={r['correct']} executed={r['executed']} "
          f"answer={str(r.get('answer'))[:80]!r} ({time.time() - t0:.0f}s)", flush=True)
    rows.append({"id": c.id, "correct": r.get("correct"), "variant_of": c.variant_of,
                 "variant_kind": c.variant_kind})

out = os.path.join(REPO, "outputs", "perturb_smoke_react.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"cases": rows}, f, ensure_ascii=False, indent=2)
print("saved:", out)
