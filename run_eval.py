"""评测入口：跑50条标注用例，输出三维指标报告。

用法:
    python run_eval.py                       # 跑全部50条
    python run_eval.py --category agg        # 只跑聚合类
    python run_eval.py --category filt       # 只跑过滤类
    python run_eval.py --category corr       # 只跑关联类
    python run_eval.py --category ts         # 只跑时序类
    python run_eval.py --case agg_001        # 单条调试
    python run_eval.py --verbose             # 详细输出（含code和result）
    python run_eval.py --data data/other.csv # 指定数据文件
    python run_eval.py --agent react         # 测 ReAct 版（默认工作流版）
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
from app.eval.cases import ALL_CASES, CATEGORY_MAP
from app.eval.runner import EvalRunner
from app.core import LLMConfig
from app.eval.report import EvalReport, git_sha, run_metadata


def _select_cases(category: str = None, case_id: str = None):
    cases = ALL_CASES
    if case_id:
        cases = [c for c in cases if c.id == case_id]
        if not cases:
            print(f"未找到用例: {case_id}")
            sys.exit(1)
    elif category:
        cat_map = {
            "agg": "aggregation", "aggregation": "aggregation",
            "filt": "filtering", "filtering": "filtering",
            "corr": "correlation", "correlation": "correlation",
            "ts": "timeseries", "timeseries": "timeseries",
        }
        key = cat_map.get(category)
        if not key:
            print(f"未知分类: {category}，可选: agg / filt / corr / ts")
            sys.exit(1)
        cases = [c for c in cases if c.category == key]
    return cases


def main():
    parser = argparse.ArgumentParser(description="DataChat 评测")
    parser.add_argument("--category", "-c", default=None, help="分类: agg/filt/corr/ts")
    parser.add_argument("--case", default=None, help="单条用例ID，如 agg_001")
    parser.add_argument("--data", default="data/sample_eval.csv", help="数据文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出（含code和result）")
    parser.add_argument("--agent", choices=["workflow", "react"], default="workflow", help="被测 Agent")
    parser.add_argument("--no-dict", action="store_true", help="关闭数据字典检索")
    parser.add_argument("--oracle", action="store_true", help="离线自检：用标准答案代替模型输出")
    parser.add_argument("--out", default=None, help="JSON 报告路径（默认 outputs/eval_<agent>_<时间>.json）")
    parser.add_argument("--repeat", type=int, default=1, help="同一配置连跑几次（默认 1）")
    parser.add_argument("--rescore", default=None, metavar="REPORT", help="离线重新打分一份已有报告，不调用模型")
    args = parser.parse_args()

    if args.rescore:
        _rescore(args.rescore, args.data if args.data != "data/sample_eval.csv" else None)
        return

    if not os.path.exists(args.data):
        print(f"数据文件不存在: {args.data}")
        sys.exit(1)

    ensure_dirs()

    cases = _select_cases(args.category, args.case)
    cat_hint = ""
    if args.case:
        cat_hint = f" 用例: {args.case}"
    elif args.category:
        key = {"agg": "aggregation", "filt": "filtering", "corr": "correlation", "ts": "timeseries"}.get(args.category, args.category)
        cat_hint = f" 分类: {CATEGORY_MAP.get(key, key)}"
    print(f"📋 加载 {len(cases)} 条测试用例{cat_hint}，数据: {args.data}\n")

    model_factory = None
    if args.oracle:
        from app.core.testing import oracle_model
        model_factory = lambda case: oracle_model(case.ground_truth, args.agent)  # noqa: E731
        print("⚙️  oracle 模式：模型输出 = 标准答案，结果只用于校验评测流水线，不代表 Agent 准确率\n")

    llm_config = None if args.oracle else LLMConfig.from_env()
    meta = run_metadata(None if args.oracle else llm_config, args.data)
    meta.update({"data": args.data, "oracle": args.oracle, "use_dictionary": not args.no_dict})
    runner = EvalRunner(args.data, agent=args.agent, model_factory=model_factory, llm_config=llm_config,
                        use_dictionary=not args.no_dict)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    tag = f"eval_{args.agent}{'_oracle' if args.oracle else ''}{'' if not args.no_dict else '_nodict'}_{stamp}"
    runs, all_correct = [], True
    for k in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n======== 第 {k}/{args.repeat} 次 ========")
        results = runner.run_all(cases, verbose=True)
        report = EvalReport(results, meta={**meta, "run": k, "repeat": args.repeat})
        report.print_summary()
        report.print_details(verbose=args.verbose)
        if args.out and args.repeat == 1:
            out = args.out
        else:
            base = args.out[:-5] if args.out and args.out.endswith(".json") else (args.out or os.path.join(OUTPUT_DIR, tag))
            out = f"{base}{'' if args.repeat == 1 else f'_run{k}'}.json"
        report.to_json(out)
        print(f"JSON 报告已保存：{out}")
        s = report.summary()
        runs.append({"run": k, "file": out, "overall": s["overall"],
                     "by_category": {c: b["correctness_rate"] for c, b in s["by_category"].items()}})
        all_correct = all_correct and all(r["correct"] for r in results)

    if args.repeat > 1:
        _print_repeat(runs, meta, os.path.join(os.path.dirname(runs[0]["file"]) or ".", f"{tag}_summary.json"))

    # 返回码：全部正确为0，否则为1
    sys.exit(0 if all_correct else 1)


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
