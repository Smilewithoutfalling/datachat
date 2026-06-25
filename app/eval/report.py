"""评测报告生成。"""

from datetime import datetime

from app.eval.cases import CATEGORY_MAP


class EvalReport:
    def __init__(self, results: list):
        """results: list[dict] from EvalRunner.run_all()"""
        self.results = results
        self.total = len(results)
        self.by_category = {}
        for r in results:
            cat = r["case"].category
            self.by_category.setdefault(cat, []).append(r)

    def _rate(self, items: list, key: str) -> float:
        """计算某项指标的比例。"""
        total = len(items)
        if total == 0:
            return 0.0
        return sum(1 for r in items if r.get(key)) / total * 100

    def execution_success_rate(self, items=None):
        items = items or self.results
        return self._rate(items, "executed")

    def correctness_rate(self, items=None):
        items = items or self.results
        executed = [r for r in items if r.get("executed")]
        if not executed:
            return 0.0
        return sum(1 for r in executed if r.get("correct")) / len(executed) * 100

    def reviewer_fix_rate(self, items=None):
        items = items or self.results
        errored = [r for r in items if r.get("initial_error")]
        if not errored:
            return 100.0  # 没有错误，修复率视为100
        return sum(1 for r in errored if r.get("executed")) / len(errored) * 100

    def print_summary(self):
        print("=" * 60)
        print("  DataChat 评测报告")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  总用例: {self.total}")
        print("=" * 60)

        all_items = self.results
        print(f"\n  📊 全局指标")
        print(f"  代码执行成功率: {self.execution_success_rate(all_items):.1f}%  "
              f"({sum(1 for r in all_items if r['executed'])}/{self.total})")
        print(f"  输出正确率:     {self.correctness_rate(all_items):.1f}%  "
              f"({sum(1 for r in all_items if r.get('correct'))}/{sum(1 for r in all_items if r['executed'])})")
        print(f"  Reviewer修复率: {self.reviewer_fix_rate(all_items):.1f}%  "
              f"(初始报错 {sum(1 for r in all_items if r['initial_error'])} 条, "
              f"最终成功 {sum(1 for r in all_items if r.get('initial_error') and r.get('executed'))} 条)")

        print(f"\n  📂 分类指标")
        print(f"  {'分类':<12} {'用例数':<8} {'执行成功率':<12} {'输出正确率':<12} {'修复率':<12}")
        print(f"  {'-' * 56}")
        for cat_key in ["aggregation", "filtering", "correlation", "timeseries"]:
            items = self.by_category.get(cat_key, [])
            cat_name = CATEGORY_MAP.get(cat_key, cat_key)
            n = len(items)
            esr = self.execution_success_rate(items)
            cr = self.correctness_rate(items)
            rfr = self.reviewer_fix_rate(items)
            print(f"  {cat_name:<12} {n:<8} {esr:<12.1f}% {cr:<12.1f}% {rfr:<12.1f}%")

        print()

    def print_details(self, verbose=False):
        """打印每条用例的结果。verbose=True 时打印 code 和 result。"""
        for i, r in enumerate(self.results, 1):
            case = r["case"]
            status = "✅" if r.get("correct") else ("⚠️" if r.get("executed") else "❌")
            icon = "📊" if case.has_chart else "  "
            print(f"  {i:2d}. {status} {icon} [{case.id}] {case.question[:50]}")
            if r.get("initial_error"):
                print(f"      🔧 初始报错，reviewer 修复后 {'成功' if r['executed'] else '仍失败'}"
                      f"（重试{r['attempts']}次）")
            if not r.get("executed") and r.get("error"):
                err_preview = r["error"].replace("\n", " ")[:120]
                print(f"      ❌ 错误: {err_preview}")
            if r.get("executed") and not r.get("correct") and verbose:
                print(f"      📝 期望: {str(r.get('expected'))[:80]}")
                print(f"      🔧 实际: {str(r.get('actual'))[:80]}")
            if verbose and r.get("code"):
                print(f"      💻 code: {r['code'][:150]}")
        print()
