"""评测执行器：对每条用例调用 analyze()，执行 ground truth，比较结果。

阶段 1 变化：
- 走统一的 analyze()，两种 Agent 都能测（agent="workflow" | "react"）。
- 直接用 analyze() 返回的结构化 result 打分，不再把最终代码重跑一遍（B07：消除双重执行）。
- 每题记录耗时与 token；LLM/基础设施失败（error_kind="llm"）单独计数，不与"代码写错"混在一起。
"""
from app.core import analyze
from app.eval.cases import DATASETS, EvalCase
from app.eval.comparator import is_refusal, results_equal
from app.tools.csv_io import read_csv
from app.tools.sandbox import run_trusted


class EvalRunner:
    def __init__(self, df_path: str | None = None, *, agent: str = "workflow", llm_config=None,
                 model_factory=None, use_dictionary: bool = True, max_attempts: int = 3,
                 datasets: dict | None = None):
        """model_factory：可选，case -> ChatModel。用于离线自检（--oracle）和单测；
        为 None 时用真实模型（llm_config 或环境变量）。
        阶段 3：每题按 case.dataset 取数据表（DATASETS）；df_path 若给出，覆盖 "sales" 表的路径（兼容旧的 --data）。"""
        self.datasets = dict(DATASETS if datasets is None else datasets)
        if df_path:
            self.datasets["sales"] = df_path
        self.df_path = self.datasets["sales"]
        self._frames = {}
        self.agent = agent
        self.llm_config = llm_config
        self.model_factory = model_factory
        self.use_dictionary = use_dictionary
        self.max_attempts = max_attempts

    def path_for(self, case: EvalCase) -> str:
        if case.dataset not in self.datasets:
            raise KeyError(f"未知数据表 {case.dataset!r}，可选：{', '.join(self.datasets)}")
        return self.datasets[case.dataset]

    def frame(self, name: str = "sales"):
        if name not in self._frames:
            self._frames[name] = read_csv(self.datasets[name])
        return self._frames[name]

    @property
    def df(self):
        return self.frame("sales")

    def _run_code(self, code: str, dataset: str = "sales"):
        """执行标准答案（可信代码，本进程执行，不走子进程沙箱），返回 (result, error)。"""
        result, error = run_trusted(code, self.frame(dataset).copy())
        return result, error or None

    def expected_all(self, case: EvalCase):
        """标准答案及歧义题的其他合理答案。返回 ([结果...], 第一个报错)。"""
        outs, first_err = [], None
        for code in [case.ground_truth, *case.alt_ground_truths]:
            r, err = self._run_code(code, case.dataset)
            if err:
                first_err = first_err or err
            else:
                outs.append(r)
        return outs, first_err

    def run_single(self, case: EvalCase):
        """执行单条用例，返回结果 dict。

        executed: bool      — 是否有代码执行成功并拿到结果
        correct: bool       — 结果是否正确（只有 executed 才可能为 True）
        initial_error: bool — 第一次执行是否报错（用于修复率）
        infra_error: bool   — 是否因 LLM/基础设施失败而没有答案（超时、限流、缺 Key 等）
        error / error_kind  — 最终错误
        attempts / expected / actual / code / answer / chart / duration_s / tokens
        """
        out = {
            "case": case, "agent": self.agent, "executed": False, "correct": False,
            "initial_error": False, "infra_error": False, "error": None, "error_kind": None,
            "attempts": 0, "expected": None, "actual": None, "code": "", "answer": "",
            "chart": None, "duration_s": None, "tokens": None,
        }

        # 1. ground truth
        expected_list, gt_error = self.expected_all(case)
        if gt_error:
            out["error"], out["error_kind"] = f"[ground_truth 执行失败] {gt_error}", "ground_truth"
            return out
        out["expected"] = expected_list[0]

        # 2. 被测 Agent
        chat_model = self.model_factory(case) if self.model_factory else None
        res = analyze(self.path_for(case), case.question, agent=self.agent, llm_config=self.llm_config,
                      chat_model=chat_model, max_attempts=self.max_attempts,
                      use_dictionary=self.use_dictionary, log=False)
        out.update({
            "attempts": res.attempts, "code": res.code, "answer": res.answer,
            "initial_error": res.initial_error is not None,
            "infra_error": res.error_kind in ("llm", "dataset"),
            "error": res.error, "error_kind": res.error_kind,
            "chart": res.chart_path, "duration_s": res.timings.get("total"),
            "tokens": res.usage.total_tokens if res.usage.reported else None,
        })

        # 3. 打分：直接用 analyze 的结构化结果
        if res.executed:
            out["executed"] = True
            out["actual"] = res.result
            out["correct"] = score(res.result, case, expected_list)
        return out

    def run_all(self, cases: list[EvalCase] = None, verbose: bool = False):
        """逐个执行用例，返回 results list。"""
        from app.eval.cases import ALL_CASES
        cases = cases or ALL_CASES
        results = []
        total = len(cases)
        for i, case in enumerate(cases, 1):
            if verbose:
                print(f"  [{i}/{total}] {case.id} ...", end=" ", flush=True)
            r = self.run_single(case)
            if verbose:
                mark = "✅" if r["correct"] else ("⚠️" if r["executed"] else "❌")
                detail = ""
                if r.get("initial_error"):
                    detail = f"(reviewer修复{'成功' if r['executed'] else '失败'})"
                elif not r["executed"]:
                    detail = f"({(r.get('error') or '')[:60]})"
                print(f"{mark} {detail}")
            results.append(r)
        return results


def score(actual, case: EvalCase, expected_list: list) -> bool:
    """阶段 3 打分：应拒答题看是否拒答且给了原因；其他题拒答即错，否则与任一合理答案相等即对。"""
    if case.expect_refusal:
        return is_refusal(actual)
    if is_refusal(actual):
        return False
    return any(results_equal(actual, e, ordered=case.ordered, percent_equiv=case.percent_equiv)
               for e in expected_list)
