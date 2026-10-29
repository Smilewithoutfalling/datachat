"""评测入口：跑标注用例（阶段 3 起 130 题、4 张表），输出指标报告。

用法:
    python run_eval.py                       # 跑全部 130 题
    python run_eval.py --dataset sales       # 只跑原 50 题（data/sample_eval.csv），可与阶段 1.5 的基线对比
    python run_eval.py --dataset orders      # 只跑某张表：sales / orders / employees / inventory
    python run_eval.py --category refusal    # 只跑某类：agg / filt / corr / ts / refusal / ambiguity
    python run_eval.py --case ord_001        # 单条调试
    python run_eval.py --verbose             # 详细输出（含code和result）
    python run_eval.py --data data/other.csv # 替换 sales 表的数据文件
    python run_eval.py --agent react         # 测 ReAct 版（默认工作流版）
    python run_eval.py --agent both          # 两个 Agent 同一批题各跑一遍，并排比较正确率、耗时、token
    python run_eval.py --no-dict             # 关闭数据字典检索（单独衡量 RAG 增益）
    python run_eval.py --oracle              # 离线自检：假模型直接"生成"标准答案，验证评测流水线与打分口径（不需要 API Key）
    python run_eval.py --out outputs/eval.json  # 另存带 commit SHA 的 JSON 报告
    python run_eval.py --repeat 3            # 同一配置连跑 3 次，报每次结果与均值/区间（衡量运行间波动）
    python run_eval.py --rescore outputs/eval_x.json  # 不调模型，用报告里存的结果按当前比较器/标准答案重新打分

全部经 app.core.analyze() 调用 Agent（与 run.py / run_react.py / UI 同一条路径）。
"""
import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Windows 控制台默认 GBK，强制 UTF-8 以正常打印中文与 emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app.config import OUTPUT_DIR, ensure_dirs
from app.eval.cases import ALL_CASES, CATEGORY_MAP, DATASETS
from app.eval.runner import EvalRunner
from app.core import LLMConfig
from app.eval.report import EvalReport, datasets_metadata, git_sha, run_metadata

_CAT_ALIAS = {
    "agg": "aggregation", "filt": "filtering", "corr": "correlation", "ts": "timeseries",
    "ref": "refusal", "amb": "ambiguity", "mul": "multi_turn",
}


def _select_cases(category: str = None, case_id: str = None, dataset: str = None):
    cases = ALL_CASES
    if case_id:
        cases = [c for c in cases if c.id == case_id]
        if not cases:
            print(f"未找到用例: {case_id}")
            sys.exit(1)
        return cases
    if dataset and dataset != "all":
        if dataset not in DATASETS:
            print(f"未知数据表: {dataset}，可选: {' / '.join(DATASETS)} / all")
            sys.exit(1)
        cases = [c for c in cases if c.dataset == dataset]
    if category:
        key = _CAT_ALIAS.get(category, category)
        if key not in CATEGORY_MAP:
            print(f"未知分类: {category}，可选: {' / '.join(_CAT_ALIAS)}")
            sys.exit(1)
        cases = [c for c in cases if c.category == key]
    return cases


def main():
    parser = argparse.ArgumentParser(description="DataChat 评测")
    parser.add_argument("--category", "-c", default=None, help="分类: agg/filt/corr/ts/refusal/ambiguity")
    parser.add_argument("--dataset", "-d", default="all", help="数据表: sales/orders/employees/inventory/all（默认 all）")
    parser.add_argument("--case", default=None, help="单条用例ID，如 agg_001")
    parser.add_argument("--data", default=None, help="替换 sales 表的数据文件（默认 data/sample_eval.csv）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出（含code和result）")
    parser.add_argument("--agent", choices=["workflow", "react", "both"], default="workflow", help="被测 Agent")
    parser.add_argument("--no-dict", action="store_true", help="关闭数据字典检索")
    parser.add_argument("--oracle", action="store_true", help="离线自检：用标准答案代替模型输出")
    parser.add_argument("--out", default=None, help="JSON 报告路径（默认 outputs/eval_<agent>_<时间>.json）")
    parser.add_argument("--repeat", type=int, default=1, help="同一配置连跑几次（默认 1）")
    parser.add_argument("--rescore", default=None, metavar="REPORT", help="离线重新打分一份已有报告，不调用模型")
    parser.add_argument("--baseline", default=None, metavar="REPORT",
                        help="基准报告的 JSON 路径：填 comparable，判定两批分数能不能直接比（EV-A3）")
    args = parser.parse_args()

    if args.rescore:
        _rescore(args.rescore, args.data)
        return

    baseline_fp = None
    if args.baseline:
        import json
        try:
            with open(args.baseline, encoding="utf-8") as f:
                baseline_fp = (json.load(f) or {}).get("fingerprints") or {}
        except (OSError, ValueError) as e:
            print(f"读不了基准报告 {args.baseline}: {e}")
            sys.exit(1)
        if not baseline_fp:
            print(f"⚠ 基准报告没有 fingerprints（{args.baseline}），只能判为不可比")
    args.baseline_fp = baseline_fp

    if args.data and not os.path.exists(args.data):
        print(f"数据文件不存在: {args.data}")
        sys.exit(1)

    ensure_dirs()
    cases = _select_cases(args.category, args.case, args.dataset)
    tables = sorted({c.dataset for c in cases})
    print(f"📋 加载 {len(cases)} 条测试用例，数据表: {', '.join(tables)}\n")

    llm_config = None if args.oracle else LLMConfig.from_env()
    if args.oracle:
        print("⚙️  oracle 模式：模型输出 = 标准答案，结果只用于校验评测流水线，不代表 Agent 准确率\n")
    agents = ["workflow", "react"] if args.agent == "both" else [args.agent]
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    all_correct, compare = True, {}
    for agent in agents:
        ok, runs = _run_agent(agent, cases, args, llm_config, stamp)
        all_correct = all_correct and ok
        compare[agent] = runs
    if len(agents) > 1:
        # 给了 --out 时 compare 写在同一目录，测试不会往真实 outputs/ 里落文件（B42）
        out_dir = os.path.dirname(os.path.abspath(args.out)) if args.out else OUTPUT_DIR
        _print_compare(compare, os.path.join(out_dir, f"eval_compare{'_oracle' if args.oracle else ''}_{stamp}.json"))
    # 返回码：全部正确为0，否则为1
    sys.exit(0 if all_correct else 1)


def _run_agent(agent, cases, args, llm_config, stamp):
    model_factory = None
    if args.oracle:
        from app.core.testing import oracle_model
        model_factory = lambda case: oracle_model(case.ground_truth, agent)  # noqa: E731
    runner = EvalRunner(args.data, agent=agent, model_factory=model_factory, llm_config=llm_config,
                        use_dictionary=not args.no_dict)
    used = {c.dataset for c in cases}
    meta = run_metadata(llm_config, runner.datasets["sales"] if "sales" in used else None)
    meta.update({"data": args.data or "data/sample_eval.csv", "oracle": args.oracle,
                 "use_dictionary": not args.no_dict,
                 "datasets": datasets_metadata({k: v for k, v in runner.datasets.items() if k in used}),
                 "filter": {"dataset": args.dataset, "category": args.category, "case": args.case}})
    tag = f"eval_{agent}{'_oracle' if args.oracle else ''}{'' if not args.no_dict else '_nodict'}_{stamp}"
    runs, all_correct = [], True
    # EV-C3：逐题跨轮的判定与签名。`runs` 里只有汇总数字，算不了 pass^k / flip_rate——
    # 那需要"同一题在第 1..k 次分别对没对"，必须在这层把逐题结果留下。
    per_case = {}
    for k in range(1, args.repeat + 1):
        if args.repeat > 1 or args.agent == "both":
            print(f"\n======== {agent} 第 {k}/{args.repeat} 次 ========")
        results = runner.run_all(cases, verbose=True)
        report = EvalReport(results, meta={**meta, "run": k, "repeat": args.repeat},
                            datasets=runner.datasets, baseline=getattr(args, "baseline_fp", None))
        report.print_summary()
        report.print_details(verbose=args.verbose)
        if args.out and args.repeat == 1 and args.agent != "both":
            out = args.out
        else:
            base = args.out[:-5] if args.out and args.out.endswith(".json") else (args.out or os.path.join(OUTPUT_DIR, tag))
            if args.agent == "both" and args.out:
                base = f"{base}_{agent}"
            out = f"{base}{'' if args.repeat == 1 else f'_run{k}'}.json"
        report.to_json(out)
        print(f"JSON 报告已保存：{out}")
        s = report.summary()
        runs.append({"run": k, "file": out, "overall": s["overall"],
                     "by_category": {c: b["correctness_rate"] for c, b in s["by_category"].items()},
                     "by_dataset": {c: b["correctness_rate"] for c, b in s["by_dataset"].items()}})
        for r in results:
            rec = per_case.setdefault(r["case"].id, {"passes": [], "sig": []})
            rec["passes"].append(bool(r["correct"]))
            rec["sig"].append((r.get("tokens"), r.get("code")))
        all_correct = all_correct and all(r["correct"] for r in results)
    if args.repeat > 1:
        _print_repeat(runs, meta, os.path.join(os.path.dirname(runs[0]["file"]) or ".", f"{tag}_summary.json"),
                      per_case)
    return all_correct, runs


def _print_compare(compare, path):
    """--agent both：两个 Agent 并排（多次运行时取均值）。"""
    import json
    import statistics as st

    def avg(runs, f):
        vals = [f(r) for r in runs if f(r) is not None]
        return st.mean(vals) if vals else None

    rows = {}
    for agent, runs in compare.items():
        rows[agent] = {
            "correctness_rate": avg(runs, lambda r: r["overall"]["correctness_rate"]),
            "execution_success_rate": avg(runs, lambda r: r["overall"]["execution_success_rate"]),
            "avg_duration_s": avg(runs, lambda r: r["overall"]["avg_duration_s"]),
            "avg_tokens": avg(runs, lambda r: r["overall"]["avg_tokens"]),
            "by_category": {c: avg(runs, lambda r, c=c: r["by_category"].get(c))
                            for c in CATEGORY_MAP if any(c in r["by_category"] for r in runs)},
            "by_dataset": {d: avg(runs, lambda r, d=d: r["by_dataset"].get(d))
                           for d in DATASETS if any(d in r["by_dataset"] for r in runs)},
            "files": [r["file"] for r in runs],
        }
    fmt = lambda v, p="%": "N/A" if v is None else (f"{v:.1f}%" if p == "%" else f"{v:.{p}f}")  # noqa: E731
    print("=" * 60)
    print(f"  {'指标':<14}" + "".join(f"{a:>14}" for a in rows))
    print(f"  {'正确率':<14}" + "".join(f"{fmt(r['correctness_rate']):>14}" for r in rows.values()))
    print(f"  {'执行成功率':<12}" + "".join(f"{fmt(r['execution_success_rate']):>14}" for r in rows.values()))
    print(f"  {'平均耗时(秒)':<11}" + "".join(f"{fmt(r['avg_duration_s'], 2):>14}" for r in rows.values()))
    print(f"  {'平均 token':<13}" + "".join(f"{fmt(r['avg_tokens'], 0):>14}" for r in rows.values()))
    for c in CATEGORY_MAP:
        if any(c in r["by_category"] for r in rows.values()):
            print(f"  {CATEGORY_MAP[c]:<14}" + "".join(f"{fmt(r['by_category'].get(c)):>14}" for r in rows.values()))
    for d in DATASETS:
        if any(d in r["by_dataset"] for r in rows.values()):
            print(f"  {d:<14}" + "".join(f"{fmt(r['by_dataset'].get(d)):>14}" for r in rows.values()))
    print("=" * 60)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"git_sha": git_sha(), "agents": rows}, f, ensure_ascii=False, indent=2, default=str)
    print(f"对比已保存：{path}")


def _stability(per_case: dict, k: int) -> dict:
    """EV-C3：k 次运行的稳定性。这是读数的前提，不是装饰。

    三个数字分工不同，不能互相替代：
      - `pass_pow_k`：k 次全对的题占比。稳定正确的下界，必然 ≤ 任何单跑的正确率。
      - `any_correct`：至少对过一次的题占比。用来确认没有"永远做不对"的题。
      - `flip_rate`：任取一题、再任取两次运行，判定不一致的概率。两个单跑相减时的噪声
        量级就是它——eval-v0 那次 129 对 125，4 题差里 3 题是噪声、1 题是真变化。

    `flip_rate` 的全库口径是 sum(单题 flip_rate)/题数，即"随机抽一道题、随机抽两跑"。
    不要拿"翻转题数/题数"顶替：那个数回答的是"有多少题不稳"，分母是题，不是(题, 跑对)。
    本仓库 130 题 3 跑时两个数分别是 2.05% 与 3.08%，量级接近但含义不同。

    复用 `stats.pass_pow_k` / `stats.flip_rate`，不复用 `stats.pass_at_1`：后者虽然名字
    带 at_1，实现却是"至少对一次"（忽略 k），语义与名字不符，直接用会让读数的人误解。
    """
    from app.eval import stats
    ids = list(per_case)
    n = len(ids)
    if n == 0 or k < 2:
        return None
    passes = [sum(per_case[i]["passes"]) for i in ids]
    flipped = [i for i in ids if 0 < sum(per_case[i]["passes"]) < k]
    always_wrong = [i for i in ids if sum(per_case[i]["passes"]) == 0]
    flip = sum(stats.flip_rate(p, k) for p in passes) / n
    # 缓存嫌疑：k 次跑出来的 (tokens, code) 逐字相同。temp=0 时部分题本来就确定，所以
    # 只有"全部题都相同"才当异常——那说明多半是同一份响应被复用，pass^k 没有信息量。
    identical = sum(1 for i in ids
                    if len(set(per_case[i]["sig"])) == 1 and per_case[i]["sig"][0][0] is not None)
    valid = identical < n
    return {
        "k": k,
        "n_cases": n,
        "pass_pow_k": stats.pass_pow_k(passes, k),
        "any_correct": sum(1 for p in passes if p >= 1) / n,
        "flip_rate": flip,
        "flipped": {"count": len(flipped), "ids": flipped},
        "always_wrong": always_wrong,
        "identical_cases": identical,
        "valid": valid,
        "invalid_reason": None if valid else (
            f"{n} 题在 {k} 次运行里的 (tokens, code) 全部逐字相同：可能是同一份响应被复用，"
            "也可能是 --oracle 自检（那模式下 tokens 是桩值，恒为同一个数）。"
            "两种情况下 pass^k 都没有信息量"),
    }


def _print_repeat(runs, meta, path, per_case=None):
    import json
    import statistics as st
    rates = [r["overall"]["correctness_rate"] for r in runs]
    agg = {"runs": len(runs), "mean": st.mean(rates), "min": min(rates), "max": max(rates),
           "stdev": st.stdev(rates) if len(rates) > 1 else 0.0,
           "avg_duration_s": st.mean([r["overall"]["avg_duration_s"] or 0 for r in runs]),
           "avg_tokens": st.mean([r["overall"]["avg_tokens"] or 0 for r in runs])}
    print("=" * 60)
    print(f"  {len(runs)} 次运行：正确率 均值 {agg['mean']:.1f}%  区间 {agg['min']:.1f}%–{agg['max']:.1f}%"
          f"  标准差 {agg['stdev']:.1f}pp")
    for r in runs:
        print(f"    run{r['run']}: {r['overall']['correctness_rate']:.1f}%  {r['file']}")
    stab = _stability(per_case, len(runs)) if per_case else None
    if stab:
        k, n = stab["k"], stab["n_cases"]
        print("-" * 60)
        print(f"  稳定性（k={k}，{n} 题）")
        print(f"    pass^{k} {stab['pass_pow_k'] * 100:.1f}%"
              f"（{round(stab['pass_pow_k'] * n)}/{n} 全对）"
              f"   至少对一次 {stab['any_correct'] * 100:.1f}%")
        print(f"    翻转 {stab['flipped']['count']} 题，flip_rate {stab['flip_rate'] * 100:.2f}%"
              f"（任取两跑判定不一致的概率）")
        if stab["flipped"]["ids"]:
            print(f"      {' '.join(stab['flipped']['ids'])}")
        print(f"    {k} 跑全错 {len(stab['always_wrong'])} 题"
              + (f"：{' '.join(stab['always_wrong'])}" if stab["always_wrong"] else ""))
        if not stab["valid"]:
            print(f"    ⚠ pass^{k} 不可用：{stab['invalid_reason']}")
    print("=" * 60)
    payload = {**meta, "git_sha": git_sha(), "aggregate": agg, "runs": runs}
    if stab:
        payload["stability"] = stab
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"汇总已保存：{path}")


def _rescore(path, data):
    from app.eval.rescore import rescore
    r = rescore(path, data)
    print(f"重新打分：{r['correct']}/{r['n']} = {r['correctness_rate']:.1f}%   （{path}）")
    for cat, b in r["by_category"].items():
        print(f"  {CATEGORY_MAP.get(cat, cat)}: {b['correct']}/{b['n']}")
    for c in r["changed"]:
        print(f"  变化 {c['id']}: {c['before']} → {c['after']}")
    if r["skipped_no_obj"]:
        print(f"  {len(r['skipped_no_obj'])} 题没有结构化结果（旧报告），沿用原判定")
    print(f"  判对层级：{r['match_kinds']}")
    if r["needs_audit"]:
        print(f"  需人工抽审（判对但不是 strict）{len(r['needs_audit'])} 题：{' '.join(r['needs_audit'])}")
    if r["evalset_report"] and r["evalset_report"] != r["evalset_now"]:
        print(f"  ⚠ 评测集指纹变了（报告 {r['evalset_report']} → 现在 {r['evalset_now']}），与原报告不完全可比")


if __name__ == "__main__":
    main()
