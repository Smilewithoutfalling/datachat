"""holdout（H1）runner —— 跑留出集、出待人工判定的报告。

用法（在仓库根目录）：
    python scripts/holdout/run_holdout.py --oracle              # 自检：标准答案代替模型输出，不调模型
    python scripts/holdout/run_holdout.py --agent react         # 正式跑（要 API Key，同 run_eval.py 的环境变量）
    python scripts/holdout/run_holdout.py --agent react --repeat 3
    python scripts/holdout/run_holdout.py --case h1_01,h1_07    # 只跑几题

题库目录：默认读仓库根的 `.holdout_path`（已 gitignore，内容是**目录路径**一行），或用 `--dir` 指定。
目录结构：

    <dir>/questions.json    题面（不含答案）
    <dir>/answers.json      标准答案（由独立脚本在**原始数据**上算出，含 questions_sha256）
    <dir>/data/...          数据：单表 = *.csv，多表 = 一个目录下每张 *.csv 一张表

`questions.json`：
    {
      "version": 1,
      "frozen_at": "2026-11-05",
      "datasets": {"h1_air": "data/air/空气质量.csv", "h1_shop": "data/shop"},
      "questions": [
        {"id": "h1_01", "group": "single", "category": "aggregation",
         "dataset": "h1_air", "question": "……", "ordered": false,
         "percent_equiv": false, "expect_refusal": false}
      ]
    }

`answers.json`：
    {
      "questions_sha256": "<题库冻结时算出的哈希>",
      "answers": {"h1_01": {"ground_truth": "result = ...", "alt": ["..."], "note": "口径说明"}}
    }

`category` 用**英文 key**（aggregation / filtering / correlation / timeseries / refusal /
ambiguity），报告的 by_category 按这个分组。

## 为什么不用 `run_eval.py --data`

`--data` 只覆盖 sales 一张表：help 写的就是「替换 sales 表的数据文件」（`run_eval.py:97`），
消费点是 `EvalRunner(args.data)`（`:178`），而 `runner.py:77-78` 只做
`self.datasets["sales"] = df_path`。`DATASETS`（`cases.py:357`）是模块级硬编码 dict，
`--data` 改不了它。**多表题因此没有 CLI 入口。**

闸门能跑 Olist 8 张表，是因为它绕开了 `run_eval.py`：`scripts/gate/run_gate.py:160` 把
`q["dataset"]`（相对路径，指向目录）直接传给 `analyze()`。本脚本走同一条路，但复用
`EvalRunner` 的 `datasets` 参数（`runner.py:72`）——它本来就支持整表替换，只是没人从 CLI 用过。

## 一处必须在调用侧规避的硬约束

`runner.py:79` 写着 `self.df_path = self.datasets["sales"]`。这个 `df_path` **全仓库没有任何
地方读**（赋值后即死），但它要求 `datasets` 必须含 `"sales"` 键，否则 KeyError。
`runner.py` 在 A 组指纹里，改它会让 6 个基线全部失配，所以只能在调用侧塞一个占位键。
留出集的逻辑名因此不能自由起名 —— 见 `_pad_sales()`。

## 与闸门的差别

不做 verdict / 门槛 / rerun / profile：H1 只回答「这版实现比基线好还是差」，判定单位是
**人工逐题判定**，不是预登记阈值。跑完只出报告，人工填 human_correct 后另行汇总。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval.case_model import EvalCase          # noqa: E402
from app.eval.report import EvalReport, datasets_metadata, run_metadata  # noqa: E402
from app.eval.runner import EvalRunner            # noqa: E402

DEFAULT_DIR_FILE = os.path.join(ROOT, ".holdout_path")
DEFAULT_OUT_DIR = os.path.join(ROOT, "docs", "eval")

# 人工判定要填的字段（§2 E0）。跑完一律留空/None，由人填；不预填猜测值。
MANUAL_DEFAULTS = {
    "human_correct": None,     # true / false
    "failure_class": None,     # 1–6，判错时填；见 docs/gate/JUDGE-GUIDE.md
    "reason": "",              # 一句话：这个答案我会不会拿去用
    "guessing": False,         # 读代码觉得它在乱猜（编数字凑答案）
    "first_error_step": None,  # 第一个出错的 step 序号（审计待办：B09 之后的过程归因）
}


def _sha256(obj) -> str:
    """稳定哈希：键排序、无空格、UTF-8。题目数组和整份题库都用它。"""
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load(path: str, what: str):
    if not os.path.exists(path):
        sys.exit(f"{what} 不存在：{path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"{what} 不是合法 JSON（{path}）：{e}")


def resolve_dir(cli_dir: str | None) -> str:
    """题库目录：--dir > .holdout_path > 报错。

    不猜、不默认到某个相对路径 —— 猜错目录会让 runner 在**别的**题库上跑出一份报告，
    比直接报错危险得多。
    """
    if cli_dir:
        return os.path.abspath(cli_dir)
    if not os.path.exists(DEFAULT_DIR_FILE):
        sys.exit(
            f"找不到题库目录：既没给 --dir，也没有 {os.path.relpath(DEFAULT_DIR_FILE, ROOT)}。\n"
            "先建一个只有一行（目录绝对路径）的 .holdout_path，或用 --dir 指定。\n"
            "题面与数据不进 git —— 规则见 scripts/holdout/README.md。"
        )
    with open(DEFAULT_DIR_FILE, encoding="utf-8") as f:
        line = f.read().strip().splitlines()
    if not line or not line[0].strip():
        sys.exit(f"{DEFAULT_DIR_FILE} 是空的，第一行要写题库目录的绝对路径")
    return os.path.abspath(line[0].strip())


def _pad_sales(datasets: dict) -> dict:
    """规避 `runner.py:79` 对 `datasets["sales"]` 的硬依赖。

    那个 `df_path` 赋值后无人读取（全仓库 grep 过），纯属遗留。`runner.py` 在 A 组，
    改一个字符就让 6 个基线失配，所以在这里补一个占位键，而不是去动它。
    占位值取第一个真实数据集 —— 只要它是个存在的路径，`EvalRunner` 就不会提前炸；
    真正的取数走 `path_for(case)`，按题目的逻辑名来，不经过这个键。
    """
    if "sales" in datasets:
        return datasets
    first = next(iter(datasets.values()))
    return {**datasets, "sales": first}


def build_datasets(spec: dict, base: str) -> dict:
    """逻辑名 → 绝对路径。相对路径按**题库目录**解析，不按仓库根。

    题面里只存逻辑名和相对路径，这样换一份数据不用改题；也让题目本身不含机器相关路径。
    """
    raw = spec.get("datasets") or {}
    if not raw:
        sys.exit("questions.json 缺 datasets 段：至少要给出逻辑名到路径的映射")

    out, missing = {}, []
    for name, rel in raw.items():
        p = rel if os.path.isabs(rel) else os.path.join(base, rel)
        p = os.path.abspath(p)
        if not os.path.exists(p):
            missing.append(f"  {name}: {p}")
        out[name] = p
    if missing:
        sys.exit("以下数据集路径不存在（相对路径按题库目录解析）：\n" + "\n".join(missing))
    return _pad_sales(out)


def build_cases(spec: dict, answers: dict) -> list[EvalCase]:
    """题面 + 答案 → EvalCase。缺答案、题号重复、引用未注册的数据集，一律硬失败。"""
    qs = spec.get("questions") or []
    if not qs:
        sys.exit("questions.json 里没有题目")

    registered = set((spec.get("datasets") or {}).keys())
    ans = answers.get("answers") or {}
    seen, cases, problems = set(), [], []

    for q in qs:
        cid = q.get("id")
        if not cid:
            problems.append("  有一条题没有 id")
            continue
        if cid in seen:
            problems.append(f"  {cid}: 题号重复")
            continue
        seen.add(cid)
        if q.get("dataset") not in registered:
            problems.append(f"  {cid}: dataset={q.get('dataset')!r} 不在 datasets 里")
        a = ans.get(cid)
        if not a:
            problems.append(f"  {cid}: answers.json 里没有这道题的答案")
            continue
        gt = (a.get("ground_truth") or "").strip()
        if not gt:
            problems.append(f"  {cid}: 答案是空的")
            continue
        cases.append(EvalCase(
            id=cid,
            category=q.get("category", "aggregation"),
            question=q["question"],
            ground_truth=gt,
            keywords=q.get("keywords", []),
            has_chart=q.get("has_chart", False),
            ordered=q.get("ordered", False),
            percent_equiv=q.get("percent_equiv", False),
            dataset=q["dataset"],
            expect_refusal=q.get("expect_refusal", False),
            alt_ground_truths=a.get("alt") or [],
            multi_table=q.get("multi_table", False),
            gold_kind=q.get("gold_kind", ""),
        ))

    extra = sorted(set(ans) - seen)
    if extra:
        problems.append(f"  answers.json 里有题库中没有的题号：{', '.join(extra)}")
    if problems:
        sys.exit("题库不一致：\n" + "\n".join(problems))
    return cases


def check_frozen(spec: dict, answers: dict) -> str:
    """冻结校验：答案是不是针对**现在这版题面**算的。

    算题的脚本会把这题面的 sha256 写进 answers.json；题面一改，这里就对不上。
    不比对就开跑，等于拿旧答案判新题 —— 判错的会被记成模型错。

    `questions_sha256` 缺失时**不拦**（首次建库还没有），但会打印警告 ——
    警告而非报错，是因为拦下来会逼人先算一遍哈希才能试跑；而"每次跑都看得见"足够防住忘记。
    """
    got = _sha256(spec.get("questions"))
    want = answers.get("questions_sha256")
    if not want:
        print("⚠️  answers.json 没有 questions_sha256，无法确认答案是不是针对这版题面算的。")
        return got
    if want != got:
        sys.exit(
            "题面与答案不匹配 —— 题库在答案算完之后被改过。\n"
            f"  questions 当前哈希：{got}\n"
            f"  answers 记录的：    {want}\n"
            "先重算答案，或把题面改回去。不要带着不匹配跑 —— 判错的会被记成模型错。"
        )
    return got


def main() -> None:
    ap = argparse.ArgumentParser(description="holdout（H1）runner")
    ap.add_argument("--dir", default=None, help="题库目录（默认读 .holdout_path）")
    ap.add_argument("--agent", choices=["workflow", "react"], default="react",
                    help="被测 Agent。默认 react —— 全部归档基线用的就是它")
    ap.add_argument("--oracle", action="store_true",
                    help="离线自检：用标准答案代替模型输出，只校验流水线与数据可解，不代表准确率")
    ap.add_argument("--case", default=None, help="只跑指定题号，逗号分隔")
    ap.add_argument("--repeat", type=int, default=1, help="连跑几次（默认 1；报 pass^k 用 3）")
    ap.add_argument("--out", default=None, help="报告路径（默认 docs/eval/holdout_<时间>_<agent>.json）")
    ap.add_argument("--no-dict", action="store_true", help="关闭数据字典检索")
    args = ap.parse_args()

    base = resolve_dir(args.dir)
    spec = _load(os.path.join(base, "questions.json"), "questions.json")
    answers = _load(os.path.join(base, "answers.json"), "answers.json")
    qsha = check_frozen(spec, answers)

    datasets = build_datasets(spec, base)
    cases = build_cases(spec, answers)
    if args.case:
        want = {c.strip() for c in args.case.split(",") if c.strip()}
        unknown = want - {c.id for c in cases}
        if unknown:
            sys.exit(f"--case 里有题库中不存在的题号：{', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in want]

    tables = sorted({c.dataset for c in cases})
    print(f"📋 留出集 {len(cases)} 题，数据集: {', '.join(tables)}")
    print(f"   题库 {base}")
    print(f"   questions_sha256 = {qsha[:12]}  frozen_at = {spec.get('frozen_at') or '未标注'}")

    llm_config = None
    model_factory = None
    if args.oracle:
        from app.core.testing import oracle_model
        model_factory = lambda case: oracle_model(case.ground_truth, args.agent)  # noqa: E731
        print("⚙️  oracle 模式：模型输出 = 标准答案，只校验流水线与数据可解，不代表准确率\n")
    else:
        from app.config import LLMConfig
        llm_config = LLMConfig.from_env()

    runner = EvalRunner(None, datasets=datasets, agent=args.agent, model_factory=model_factory,
                        llm_config=llm_config, use_dictionary=not args.no_dict)

    meta = run_metadata(llm_config, None)
    meta.update({
        "holdout": {
            "dir": base,
            "version": spec.get("version"),
            "frozen_at": spec.get("frozen_at"),
            "questions_sha256": qsha,
            "n": len(cases),
            "selected": args.case,
        },
        "agent": args.agent,
        "oracle": args.oracle,
        "use_dictionary": not args.no_dict,
        "repeat": args.repeat,
        "datasets": datasets_metadata({k: v for k, v in runner.datasets.items() if k in tables}),
    })

    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    out_base = args.out or os.path.join(DEFAULT_OUT_DIR, f"holdout_{stamp}_{args.agent}"
                                       f"{'_oracle' if args.oracle else ''}.json")

    runs, per_case = [], {}
    for k in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n======== 第 {k}/{args.repeat} 次 ========")
        results = runner.run_all(cases, verbose=True)
        # rendered_cases：不传的话 report 会按 ALL_CASES 的 130 题渲染指纹，
        # 那 130 题的 dataset 名（orders/employees/…）在留出集的数据集里不存在 → KeyError。
        report = EvalReport(results, meta={**meta, "run": k}, datasets=runner.datasets,
                            rendered_cases=cases)
        report.print_summary()
        if args.repeat > 1:
            path = out_base[:-5] + f"_run{k}.json" if out_base.endswith(".json") else out_base + f"_run{k}.json"
        else:
            path = out_base
        report.to_json(path)
        _stamp_manual_fields(path, meta["holdout"])
        print(f"JSON 报告已保存：{path}")

        s = report.summary()
        runs.append({"run": k, "file": path, "overall": s["overall"]})
        for r in results:
            per_case.setdefault(r["case"].id, {"passes": []})["passes"].append(bool(r["correct"]))

    if args.repeat > 1:
        _print_passk(per_case, args.repeat)


def _stamp_manual_fields(path: str, holdout: dict) -> None:
    """在报告里补人工判定字段（全空）与 holdout 段。

    为什么跑完再改文件、而不是改 `app/eval/report.py`：report.py 是 B 组（改它不动指纹），
    但它的 `cases` 字段是逐键白名单拼的 —— 要带新键就得改那个白名单，等于让**所有**评测
    报告都多出五个恒为 null 的字段。留出集是独立产物，不该污染主线报告的形状。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["holdout"] = holdout
    for c in data.get("cases") or []:
        for k, v in MANUAL_DEFAULTS.items():
            c.setdefault(k, v)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _print_passk(per_case: dict, k: int) -> None:
    """pass@1 与 pass^k。k 次里全对才算 pass^k —— 这是稳定性，不是平均分。"""
    n = len(per_case)
    p1 = sum(sum(r["passes"]) for r in per_case.values()) / (n * k) if n else 0.0
    pk = sum(1 for r in per_case.values() if all(r["passes"])) / n if n else 0.0
    flipped = [cid for cid, r in per_case.items() if len(set(r["passes"])) > 1]
    print("\n" + "=" * 56)
    print(f"  pass@1  {p1:.1%}   （{sum(sum(r['passes']) for r in per_case.values())}/{n * k} 题次）")
    print(f"  pass^{k}  {pk:.1%}   （{sum(1 for r in per_case.values() if all(r['passes']))}/{n} 题 k 次全对）")
    print(f"  翻转     {len(flipped)} 题 {('：' + ', '.join(sorted(flipped))) if flipped else ''}")
    print("=" * 56)


if __name__ == "__main__":
    main()
