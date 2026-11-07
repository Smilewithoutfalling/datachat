"""EV-B6 扰动全量（规格实验：20 条基线题 × 4 种变体 = 80 次真模型运行）。

基线选择（确定性，不随机）：单表、非多轮、非负向、无 variant 的题，按 (dataset, id)
排序每组取前 5 —— sales / orders / employees / inventory 各 5。变体用规格点名的四种：
total_row / thousand_sep / date_compact / two_row_header。

报告里同时带上 20 条基线（decay.py 的基线口径是"同报告里被指向的 variant_of 原题"），
共 100 跑。产物：outputs/perturb_full_react.json，直接喂 scripts/eval/decay.py。
fixture 生成复用 scripts/perturb.py 的变换器（同一份代码，不写第二份）。
"""
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

from app.eval.cases import ALL_CASES, DATASETS  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402
from app.core.llm import LLMConfig  # noqa: E402
import perturb as P  # noqa: E402

PERT = os.path.join(REPO, "outputs", "perturb")
KINDS = ("total_row", "thousand_sep", "date_compact", "two_row_header")
PER_DATASET = 5


def pick_bases():
    pools = {}
    for c in ALL_CASES:
        if (c.dataset in DATASETS and not c.turns and not c.expect_refusal
                and not c.expect_kind and not c.variant_kind
                and not getattr(c, "multi_table", False) and c.dataset != "biz"):
            pools.setdefault(c.dataset, []).append(c)
    bases = []
    for ds in sorted(pools):
        bases.extend(sorted(pools[ds], key=lambda c: c.id)[:PER_DATASET])
    return bases


def make_fixture(base, kind):
    """与 perturb.py main() 同一条生成路径，只是不经过 CLI。"""
    from app.tools.dataset import load_data
    path = EvalRunner().datasets.get(base.dataset, base.dataset)
    data, _ = load_data(path)
    header = [str(c) for c in data.columns]
    rows = [[("" if v is None or (isinstance(v, float) and v != v) else (
        f"{v:g}" if isinstance(v, float) else str(v))) for v in rec]
        for rec in data.itertuples(index=False, name=None)]
    os.makedirs(PERT, exist_ok=True)
    stem = f"{base.id}.{kind}"
    clean_path = os.path.join(PERT, f"{stem}.clean.csv")
    dirty_path = os.path.join(PERT, f"{stem}.dirty.csv")
    P._write_csv(clean_path, [header, *rows])
    P._write_csv(dirty_path, P.TRANSFORM[kind](header, rows),
                 quote_all=kind in P.QUOTE_ALWAYS)
    return dirty_path, clean_path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="扰动全量或子集")
    ap.add_argument("--kind", default=",".join(KINDS), help="逗号分隔，默认全部 4 种")
    ap.add_argument("--case", default="", help="只跑这些基线题 id（逗号分隔），默认全部 20 条")
    ap.add_argument("--out", default=os.path.join(REPO, "outputs", "perturb_full_react.json"))
    ap.add_argument("--no-base", action="store_true", help="不跑基线原题（只看变体）")
    args = ap.parse_args(argv)

    kinds = [k.strip() for k in args.kind.split(",") if k.strip()]
    bad = [k for k in kinds if k not in KINDS]
    assert not bad, f"未知变体：{bad}，可选 {KINDS}"
    want = {c.strip() for c in args.case.split(",") if c.strip()}

    bases = [b for b in pick_bases() if not want or b.id in want]
    assert bases, f"没有匹配的基线题（--case {args.case}）"
    if not want:
        assert len(bases) == 20, f"基线凑不齐 20 条（实际 {len(bases)}）"
    print(f"基线 {len(bases)} 条:", " ".join(c.id for c in bases), flush=True)
    print("变体:", kinds, flush=True)

    from app.eval.case_model import EvalCase
    cases = []
    for b in bases:
        if not args.no_base:
            cases.append(b)                   # 基线原题进报告（decay 的 base_rate 用）
        for k in kinds:
            dirty, clean = make_fixture(b, k)
            cases.append(EvalCase(
                id=f"pf_{b.id}.{k}", category=b.category,
                question=b.question, ground_truth=b.ground_truth,
                keywords=b.keywords, dataset=dirty, gold_dataset=clean,
                variant_of=b.id, variant_kind=k))

    runner = EvalRunner(agent="react", llm_config=LLMConfig.from_env())
    rows = []
    t_all = time.time()
    for i, c in enumerate(cases, 1):
        t0 = time.time()
        try:
            r = runner.run_single(c)
        except Exception as e:                # noqa: BLE001 —— 单题基础设施炸不拖垮整批
            r = {"correct": False, "executed": False, "error": f"harness: {e}"}
        print(f"[{i:>3}/{len(cases)}] {c.id}: correct={r.get('correct')} "
              f"({time.time() - t0:.0f}s)", flush=True)
        rows.append({"id": c.id, "correct": r.get("correct"), "executed": r.get("executed"),
                     "variant_of": c.variant_of, "variant_kind": c.variant_kind,
                     "answer": str(r.get("answer") or "")[:200],
                     "error": str(r.get("error") or "") or None,
                     "duration_s": round(time.time() - t0, 1)})
    out = args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"agent": "react", "kinds": kinds,
                   "bases": [b.id for b in bases],
                   "total_s": round(time.time() - t_all, 1), "cases": rows},
                  f, ensure_ascii=False, indent=2)
    print("saved:", out, f"({time.time() - t_all:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
