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
    "ref": "refusal", "amb": "ambiguity",
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
    args = parser.parse_args()

    if args.rescore:
        _rescore(args.rescore, args.data)
        return

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
        _print_compare(compare, os.path.join(OUTPUT_DIR, f"eval_compare{'_oracle' if args.oracle else ''}_{stamp}.json"))
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
    for k in range(1, args.repeat + 1):
        if args.repeat > 1 or args.agent == "both":
            print(f"\n======== {agent} 第 {k}/{args.repeat} 次 ========")
        results = runner.run_all(cases, verbose=True)
        report = EvalReport(results, meta={**meta, "run": k, "repeat": args.repeat})
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
        all_correct = all_correct and all(r["correct"] for r in results)
    if args.repeat > 1:
        _print_repeat(runs, meta, os.path.join(os.path.dirname(runs[0]["file"]) or ".", f"{tag}_summary.json"))
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


def _print_repeat(runs, meta, path):
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
    print("=" * 60)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**meta, "git_sha": git_sha(), "aggregate": agg, "runs": runs}, f,
                  ensure_ascii=False, indent=2, default=str)
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


if __name__ == "__main__":
    main()
