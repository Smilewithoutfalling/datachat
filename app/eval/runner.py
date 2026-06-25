"""评测执行器：对每条用例调用工作流，执行 ground truth，比较结果。"""

from app.eval.cases import EvalCase
from app.eval.comparator import results_equal
from app.tools.sandbox import run_code
from app.tools.csv_io import read_csv
from app.tools.persist import new_chart_path


class EvalRunner:
    def __init__(self, df_path: str):
        self.df_path = df_path
        self.df = read_csv(df_path)

    def _run_code(self, code: str):
        """在 sandbox 中执行代码，返回 (result, error)。"""
        chart_path = new_chart_path()
        result, chart, error = run_code(code, self.df.copy(), chart_path)
        return result, error or None

    def run_single(self, case: EvalCase):
        """执行单条用例，返回结果 dict。

        结果包含:
            executed: bool     — 工作流是否成功执行（无error）
            correct: bool      — 结果是否正确
            initial_error: str — 初始执行是否报错
            error: str         — 最终错误信息（如果有）
            attempts: int      — 重试次数
            expected: any      — ground truth 期望结果
            actual: any        — 模型生成代码的执行结果
            code: str          — 最终代码
        """
        result = {
            "case": case,
            "executed": False,
            "correct": False,
            "initial_error": None,
            "error": None,
            "attempts": 0,
            "expected": None,
            "actual": None,
            "code": "",
        }

        # 1. 运行 ground truth 获取期望结果
        expected_result, gt_error = self._run_code(case.ground_truth)
        if gt_error:
            result["error"] = f"[ground_truth 执行失败] {gt_error}"
            return result
        result["expected"] = expected_result

        # 2. 调用完整工作流（需要 DeepSeek API）
        try:
            from app.graph import build_graph
            from app.tools.dictionary import augment_question, load_retriever
            from app.tools.schema import describe_csv

            schema = describe_csv(self.df_path)
            retriever = load_retriever(self.df_path)
            app = build_graph()
            state = app.invoke({
                "question": augment_question(case.question, retriever),
                "df_path": self.df_path,
                "schema": schema,
                "attempts": 0,
                "max_attempts": 3,
            })
        except Exception as e:
            result["error"] = f"[工作流调用失败] {e}"
            return result

        result["attempts"] = state.get("attempts", 0)
        result["code"] = state.get("code", "")
        final_error = state.get("error", "")

        # 判断初始是否报错
        if result["attempts"] > 0:
            result["initial_error"] = True

        if not final_error:
            # 3. 无错误：执行模型生成的代码，比较结果
            actual_result, exec_error = self._run_code(state["code"])
            if exec_error:
                result["error"] = f"[最终代码执行失败] {exec_error}"
                return result
            result["executed"] = True
            result["actual"] = actual_result
            result["correct"] = results_equal(actual_result, expected_result)
        elif result["attempts"] >= state.get("max_attempts", 3):
            # 用尽重试仍失败
            result["error"] = final_error
        else:
            # 不应该走到这里（error但未用尽重试），保守处理
            result["error"] = final_error

        return result

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
