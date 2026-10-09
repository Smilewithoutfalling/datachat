"""评测报告生成。

B11 口径修正：
- 正确率 = 判对题数 / 全部题数（旧版分母只算执行成功的题，数字虚高）。
  "执行成功中的正确率"仍保留，但明确标为条件正确率，不作为主指标。
- 修复率：没有任何题初始报错时为 None（报告显示 N/A），不再记作 100%。
- 分类统计：某类没有题时按空集计算（旧版 `items or self.results` 会退回到全部题）。
- 新增：基础设施失败数（LLM 超时/限流/缺 Key）、平均耗时、平均 token。
"""
import json
import subprocess
from datetime import datetime

from app.eval.cases import CATEGORY_MAP


def git_sha(short: bool = True) -> str:
    try:
        args = ["git", "rev-parse"] + (["--short"] if short else []) + ["HEAD"]
        sha = subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return (sha + ("-dirty" if dirty else "")) if sha else "unknown"
    except Exception:
        return "unknown"


class EvalReport:
    def __init__(self, results: list):
        """results: list[dict] from EvalRunner.run_all()"""
        self.results = results
        self.total = len(results)
        self.by_category = {}
        for r in results:
            cat = r["case"].category
            self.by_category.setdefault(cat, []).append(r)

    def _items(self, items):
        return self.results if items is None else items

    def _rate(self, items: list, key: str):
        total = len(items)
        if total == 0:
            return None
        return sum(1 for r in items if r.get(key)) / total * 100

    def execution_success_rate(self, items=None):
        return self._rate(self._items(items), "executed")

    def correctness_rate(self, items=None):
        """主指标：分母是全部题。"""
        return self._rate(self._items(items), "correct")

    def conditional_correctness_rate(self, items=None):
        """条件正确率：只在执行成功的题里算（仅供诊断）。"""
        executed = [r for r in self._items(items) if r.get("executed")]
        return self._rate(executed, "correct")

    def reviewer_fix_rate(self, items=None):
        """初始报错的题中，最终执行成功的比例；没有初始报错时无定义（None）。"""
        errored = [r for r in self._items(items) if r.get("initial_error")]
        return self._rate(errored, "executed")

    def infra_error_count(self, items=None):
        return sum(1 for r in self._items(items) if r.get("infra_error"))

    def avg(self, key, items=None):
        vals = [r[key] for r in self._items(items) if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def summary(self) -> dict:
        def block(items):
            return {
                "n": len(items),
                "correct": sum(1 for r in items if r.get("correct")),
                "executed": sum(1 for r in items if r.get("executed")),
                "correctness_rate": self.correctness_rate(items),
                "execution_success_rate": self.execution_success_rate(items),
                "conditional_correctness_rate": self.conditional_correctness_rate(items),
                "reviewer_fix_rate": self.reviewer_fix_rate(items),
                "initial_errors": sum(1 for r in items if r.get("initial_error")),
                "infra_errors": self.infra_error_count(items),
                "avg_duration_s": self.avg("duration_s", items),
                "avg_tokens": self.avg("tokens", items),
            }
        agents = sorted({r.get("agent", "workflow") for r in self.results})
        return {
            "time": datetime.now().isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "agent": agents[0] if len(agents) == 1 else agents,
            "overall": block(self.results),
            "by_category": {k: block(v) for k, v in self.by_category.items()},
        }

    def to_json(self, path: str, extra: dict | None = None) -> None:
        """写出带 SHA 的报告：汇总 + 每题明细（结果对象只存文本预览）。"""
        rows = []
        for r in self.results:
            c = r["case"]
            rows.append({
                "id": c.id, "category": c.category, "question": c.question,
                "correct": r.get("correct"), "executed": r.get("executed"),
                "initial_error": r.get("initial_error"), "infra_error": r.get("infra_error"),
                "error_kind": r.get("error_kind"), "error": r.get("error"),
                "attempts": r.get("attempts"), "duration_s": r.get("duration_s"),
                "tokens": r.get("tokens"), "code": r.get("code"),
                "expected": str(r.get("expected"))[:500], "actual": str(r.get("actual"))[:500],
            })
        data = {**self.summary(), **(extra or {}), "cases": rows}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _pct(v):
        return "N/A" if v is None else f"{v:.1f}%"

    def print_summary(self):
        s = self.summary()
        o = s["overall"]
        print("=" * 60)
        print("  DataChat 评测报告")
        print(f"  时间: {s['time']}    commit: {s['git_sha']}    agent: {s['agent']}")
        print(f"  总用例: {self.total}")
        print("=" * 60)

        print("\n  📊 全局指标")
        print(f"  输出正确率（分母=全部题）: {self._pct(o['correctness_rate'])}  ({o['correct']}/{o['n']})")
        print(f"  代码执行成功率:           {self._pct(o['execution_success_rate'])}  ({o['executed']}/{o['n']})")
        print(f"  条件正确率（仅执行成功）: {self._pct(o['conditional_correctness_rate'])}  "
              f"({o['correct']}/{o['executed']})")
        print(f"  Reviewer 修复率:          {self._pct(o['reviewer_fix_rate'])}  "
              f"(初始报错 {o['initial_errors']} 条)")
        print(f"  基础设施失败（LLM 超时/限流/缺 Key 等）: {o['infra_errors']} 条")
        if o["avg_duration_s"] is not None:
            print(f"  平均耗时: {o['avg_duration_s']:.2f} 秒/题")
        tok = o["avg_tokens"]
        print(f"  平均 token: {'N/A' if tok is None else format(tok, '.0f')}")

        print("\n  📂 分类指标")
        print(f"  {'分类':<10} {'用例数':<6} {'正确率':<9} {'执行成功率':<11} {'修复率':<8}")
        print(f"  {'-' * 52}")
        for cat_key in ["aggregation", "filtering", "correlation", "timeseries"]:
            b = s["by_category"].get(cat_key)
            if not b:
                continue
            cat_name = CATEGORY_MAP.get(cat_key, cat_key)
            print(f"  {cat_name:<10} {b['n']:<6} {self._pct(b['correctness_rate']):<9} "
                  f"{self._pct(b['execution_success_rate']):<11} {self._pct(b['reviewer_fix_rate']):<8}")
        print()

    def print_details(self, verbose=False):
        """打印每条用例的结果。verbose=True 时打印 code 和 result。"""
        for i, r in enumerate(self.results, 1):
            case = r["case"]
            status = "✅" if r.get("correct") else ("⚠️" if r.get("executed") else "❌")
            icon = "📊" if case.has_chart else "  "
            print(f"  {i:2d}. {status} {icon} [{case.id}] {case.question[:50]}")
            if r.get("initial_error"):
                print(f"      🔧 初始报错，修复后 {'成功' if r['executed'] else '仍失败'}"
                      f"（重试{r['attempts']}次）")
            if not r.get("executed") and r.get("error"):
                err_preview = r["error"].replace("\n", " ")[:120]
                print(f"      ❌ 错误[{r.get('error_kind')}]: {err_preview}")
            if r.get("executed") and not r.get("correct") and verbose:
                print(f"      📝 期望: {str(r.get('expected'))[:80]}")
                print(f"      🔧 实际: {str(r.get('actual'))[:80]}")
            if verbose and r.get("code"):
                print(f"      💻 code: {r['code'][:150]}")
        print()
