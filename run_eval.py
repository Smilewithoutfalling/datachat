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
"""
import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app.config import ensure_dirs
from app.eval.cases import ALL_CASES, CATEGORY_MAP
from app.eval.runner import EvalRunner
from app.eval.report import EvalReport


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
    args = parser.parse_args()

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

    runner = EvalRunner(args.data)
    results = runner.run_all(cases, verbose=True)
    report = EvalReport(results)
    report.print_summary()
    report.print_details(verbose=args.verbose)

    # 返回码：全部正确为0，否则为1
    all_correct = all(r["correct"] for r in results)
    sys.exit(0 if all_correct else 1)


if __name__ == "__main__":
    main()
