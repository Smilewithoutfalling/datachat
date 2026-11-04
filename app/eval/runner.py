"""评测执行器：对每条用例调用 analyze()，执行 ground truth，比较结果。

阶段 1 变化：
- 走统一的 analyze()，两种 Agent 都能测（agent="workflow" | "react"）。
- 直接用 analyze() 返回的结构化 result 打分，不再把最终代码重跑一遍（B07：消除双重执行）。
- 每题记录耗时与 token；LLM/基础设施失败（error_kind="llm"）单独计数，不与"代码写错"混在一起。
- 记忆（阶段 6.6）：抄录 `memory_mode` / `history_tokens` / `memory_trimmed`，让记忆消融的
  报告能自证"这一轮确实开了记忆、历史确实被裁过"。用 getattr 兜底——批 1 合入之前
  AnalysisResult 没有这三个字段，报告照跑，值恒为 off / 0 / []。
"""
import os

from app.core import analyze
from app.eval.chart_smoke import chart_row
from app.eval.cases import DATASETS, EvalCase
from app.eval.comparator import is_refusal, match_kind, refusal_leak, results_equal
from app.eval.consistency import check_consistency
from app.eval.negative import negative_verdict, refusal_text
from app.eval.provenance import describe as describe_provenance
from app.tools.dataset import copy_data, load_data
from app.tools.sandbox import run_trusted



def usage_fields(u) -> dict:
    """评测 / 闸门报告每题的 token 拆分（V2d §1）。没上报的项为 None。"""
    rep = bool(u.reported)
    return {"tokens_in": u.input_tokens if rep else None, "tokens_out": u.output_tokens if rep else None,
            "tokens_cache_read": u.cache_read_tokens, "tokens_reasoning": u.reasoning_tokens,
            "tokens_reported": u.reported, "tokens_estimated": u.estimated}


def _refused(res) -> bool:
    """这一轮是否按契约拒答。实现只有一份：negative.refusal_text。

    原来这里自己写了一版（result 优先、没执行才看 answer 首行），B7 需要同一判断
    的**文本**（要查原因里有没有点名缺失对象），于是复制了逻辑。两份判断迟早会漂，
    改成一份：这里只关心"有没有"，那边返回文本。
    """
    return refusal_text(res) is not None


def _merge_usage(usages: list):
    """多轮时把各轮 TokenUsage 相加。

    只取最后一轮会低估成本：多轮题的真实花费是各轮之和，而报告里的 tokens 是给人
    判断"跑这一批要多少钱"用的，少算了就没人会去核对。
    """
    if not usages:
        return None
    if len(usages) == 1:
        return usages[0]
    from app.core.llm import TokenUsage
    t = TokenUsage()
    flags = [u.reported for u in usages]
    t.reported = True if all(f is True for f in flags) else (None if all(f is None for f in flags) else False)
    for u in usages:
        t.calls += u.calls
        t.input_tokens += u.input_tokens
        t.output_tokens += u.output_tokens
        t.total_tokens += u.total_tokens
        t.estimated_tokens += u.estimated_tokens
        t.retries = None if (t.retries is None or u.retries is None) else t.retries + u.retries
        t.estimated = t.estimated or u.estimated
        t.budget_hit = t.budget_hit or u.budget_hit
        t.budget = max(t.budget, u.budget)
    for name in ("cache_read_tokens", "reasoning_tokens"):
        vals = [getattr(u, name) for u in usages]
        setattr(t, name, None if any(v is None for v in vals) else sum(vals))
    return t


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
        if case.dataset in self.datasets:
            return self.datasets[case.dataset]
        # EV-B6 扰动题：dataset 是直接路径（脏表），不在 DATASETS 里
        if os.path.isabs(case.dataset) and os.path.exists(case.dataset):
            return case.dataset
        raise KeyError(f"未知数据表 {case.dataset!r}，可选：{', '.join(self.datasets)}")

    def frame(self, name: str = "sales"):
        """单表返回 DataFrame，多表（目录 / 路径列表）返回 {表名: DataFrame}。

        走 load_data 而不是 read_csv：`analyze()` 早就支持多表（代码里用 df['表名']），
        但评测这一侧一直只 read_csv，所以 130 道题全是单表——多表能力从没被测过。
        缓存的是原始数据，调用方要改必须先 copy（见 _run_code），多道题共用一份。
        缓存键是**解析后的路径**：`_run_code` 允许直接传路径（扰动题的 gold_dataset），
        按名字缓存会在路径与名字混用时读错表。
        """
        path = self.datasets.get(name, name)
        if path not in self._frames:
            data, _ = load_data(path)
            self._frames[path] = data
        return self._frames[path]

    @property
    def df(self):
        return self.frame("sales")

    def _run_code(self, code: str, dataset: str = "sales"):
        """执行标准答案（可信代码，本进程执行，不走子进程沙箱），返回 (result, error)。

        `dataset` 可以是 DATASETS 的键，也可以是直接路径 —— EV-B6 扰动题的
        `gold_dataset` 是 outputs/ 下的绝对路径，不在 DATASETS 里。
        """
        result, error = run_trusted(code, copy_data(self.frame(dataset)))
        return result, error or None

    def _gold_source(self, case: EvalCase) -> str:
        """gold 用哪份数据：声明了 gold_dataset（干净表）就用它，否则与 agent 同表。

        扰动题的设计是 agent 看脏表、gold 在干净表上算 —— "答错"才归因到
        数据处理而不是期望值本身（case_model.py 的字段注释）。空值回退到
        `path_for(case)`，183 条旧题行为逐字节不变。
        """
        return case.gold_dataset or self.path_for(case)

    def expected_all(self, case: EvalCase):
        """标准答案及歧义题的其他合理答案。返回 ([结果...], 第一个报错)。

        gold 在 `gold_dataset`（干净表）上跑 —— EV-B6 扰动题 agent 看脏表；
        没声明的题回退到 agent 同表，旧行为不变。
        """
        outs, first_err = [], None
        gold_src = self._gold_source(case)
        for code in [case.ground_truth, *case.alt_ground_truths]:
            r, err = self._run_code(code, gold_src)
            if err:
                first_err = first_err or err
            else:
                outs.append(r)
        return outs, first_err

    def _run_one(self, case: EvalCase, question: str, history, chat_model):
        """跑一轮。单轮传 history=None；多轮传已有的 [(问, 答), ...]。

        单轮必须是 None 而不是 []：service.py 里 `nudge_no_exec = memory is None and not history`，
        两者对 nudge 的取值虽然一样，但"有没有历史"这件事在别处（如日志、轨迹）是要区分的，
        别让单轮看起来像"多轮的第一轮"。
        """
        return analyze(self.path_for(case), question, agent=self.agent, llm_config=self.llm_config,
                       chat_model=chat_model, max_attempts=self.max_attempts,
                       use_dictionary=self.use_dictionary, log=False, history=history)

    @staticmethod
    def _turn_status(res, expect: str) -> str:
        """这一轮是否满足 expect_turns 的约束。值域："ok" / "fail:<期望>" / "error"。

        error 优先于 fail：模型超时、限流时"没执行代码"不是模型的错，记成 fail 会把
        基础设施问题算进能力问题——这正是 infra_error 从 initial_error 里拆出来的理由。
        """
        if res.error_kind in ("llm", "dataset"):
            return "error"
        if not expect or expect == "any":
            return "ok"
        if expect == "exec":
            return "ok" if res.executed else "fail:exec"
        if expect == "refusal":
            return "ok" if _refused(res) else "fail:refusal"
        if expect.startswith("inherit:"):
            import re
            try:
                return "ok" if re.search(expect[len("inherit:"):], res.code or "") else "fail:inherit"
            except re.error:
                return "fail:inherit(bad-regex)"
        return "ok"

    def run_single(self, case: EvalCase):
        """执行单条用例，返回结果 dict。

        executed: bool      — 是否有代码执行成功并拿到结果
        correct: bool       — 结果是否正确（只有 executed 才可能为 True）
        initial_error: bool — 第一次执行是否报错（用于修复率）
        infra_error: bool   — 是否因 LLM/基础设施失败而没有答案（超时、限流、缺 Key 等）
        error / error_kind  — 最终错误
        attempts / expected / actual / code / answer / chart / duration_s / tokens
        result_origin       — 缺口 12：答案值来自运行时计算（computed）还是字面量（literal_*）
        result_missing      — 缺口 11：executed=True 却没有 result 时，没交卷的具体原因
        refusal_leak        — 缺口 14b：应拒答题 result 拒答了、answer 却仍给了量化分析（越界）
        """
        out = {
            "case": case, "agent": self.agent, "executed": False, "correct": False,
            "initial_error": False, "infra_error": False, "error": None, "error_kind": None,
            "attempts": 0, "expected": None, "actual": None, "code": "", "answer": "",
            "chart": None, "duration_s": None, "tokens": None,
            # 多轮（EV-A2）。单轮留空列表，不是 None——报告里的形状保持稳定
            "turn_answers": [], "turn_status": [],
            # 记忆（阶段 6.6）。记忆模块尚未合入时恒为 off / 0 / []，形状不随模块存不存在而变
            "memory_mode": "off", "history_tokens": 0, "memory_trimmed": [],
            # 缺口 14b：拒答越界。所有题都有这两个键（非拒答题恒为 None / ""），形状稳定
            "refusal_leak": None, "refusal_leak_why": "",
            # 负向题判错的现场（EV-B7）：只写"判错"等于让人回去翻原始输出。
            # 非负向题恒为空串，形状稳定。
            "negative_why": "",
            # 证据一致性（EV-B4）：三条断言，**只作 warnings 展示不改 correct**
            # （升级门槛见 consistency.py 模块 docstring）。全部题都有这个键，形状稳定。
            "evidence": {"applicable": False, "failures": [], "detail": {}},
            # 跨轮数字断言（EV-B5 mt_007 附加项）：recall_turn 题专用，其余恒为 ""。
            "recall_why": "",
        }

        # 1. ground truth
        expected_list, gt_error = self.expected_all(case)
        if gt_error:
            out["error"], out["error_kind"] = f"[ground_truth 执行失败] {gt_error}", "ground_truth"
            return out
        out["expected"] = expected_list[0]

        # 2. 被测 Agent：多轮逐轮累积 history，打分只看最后一轮
        multi = bool(case.turns)
        turns = list(case.turns) if multi else [case.question]
        history = [] if multi else None
        turn_answers, turn_status, durations, usages = [], [], [], []
        turn_result_texts = []   # 每轮的 result_text（recall_turn 断言要用）
        memory_by_turn = []      # [(mode, history_tokens, [trimmed...]), ...]
        res = None
        for i, q in enumerate(turns):
            # 每轮新建 chat_model，不在循环外建一次。注入的模型是"一轮 = 一个会话"的
            # 前提：oracle 桩靠 self.state["n"] 计数（第 1 次发工具调用、第 2 次给结论），
            # 共享一个实例会让第 2 轮起直接吐结论文本、不再执行代码，多轮题全部 executed=False。
            # 真实路径下 model_factory 是 None，这行恒为 None，不产生任何行为差异。
            chat_model = self.model_factory(case) if self.model_factory else None
            res = self._run_one(case, q, history, chat_model)
            expect = case.expect_turns[i] if i < len(case.expect_turns) else ""
            turn_status.append(self._turn_status(res, expect))
            answer = res.answer or ""
            turn_answers.append(answer)
            turn_result_texts.append(getattr(res, "result_text", "") or "")
            if res.timings.get("total"):
                durations.append(res.timings["total"])
            usages.append(res.usage)
            memory_by_turn.append((
                getattr(res, "memory_mode", "off") or "off",
                getattr(res, "history_tokens", 0) or 0,
                list(getattr(res, "memory_trimmed", None) or []),
            ))
            if i < len(turns) - 1:
                # 失败也要照实追加空串：换成占位文案会让下一轮以为上一轮真答了东西
                #
                # 第 3 个元素是代码。service.history_messages 只取 h[0] / h[1]，所以 off 路径
                # 逐字节不变；coerce 见到三元组才填 snap.code。不传的话 fold() 拿不到任何代码，
                # 工作状态块恒为空 —— 评测里跑 state 等于只跑了一半（历史块有、状态块没有）。
                # 按 executed 门控：fold() 把「有 code 的快照」当作可信前提，喂进失败轮次的
                # 代码会给下一轮一个假前提。
                history.append((q, answer, res.code if res.executed else ""))

        merged = _merge_usage(usages)
        out.update({
            "attempts": res.attempts, "code": res.code, "answer": res.answer,
            "initial_error": res.initial_error is not None,
            "infra_error": res.error_kind in ("llm", "dataset"),
            "error": res.error, "error_kind": res.error_kind,
            "chart": res.chart_path, "chart_info": chart_row(res), "duration_s": sum(durations) or None,
            "tokens": merged.total_tokens if merged.reported else None,
            # V2d §1：拆分字段；旧报告只有 tokens（total），可比性只看它
            **usage_fields(merged),
            "turn_answers": turn_answers if multi else [],
            "turn_status": turn_status if multi else [],
            # 记忆：模式取最后一轮（同一进程里不该变），历史体积取最后一轮（多轮里它最大），
            # trimmed 取全轮并集（"这条用例被裁过没有"才是消融表要看的）
            "memory_mode": memory_by_turn[-1][0] if memory_by_turn else "off",
            "history_tokens": memory_by_turn[-1][1] if memory_by_turn else 0,
            "memory_trimmed": sorted({b for _, _, t in memory_by_turn for b in t}),
            # 归因（缺口 11 / 12）：`result` 是算出来的还是写出来的 /
            # 没交卷时到底是没赋、赋了空、还是分支没走到。**只记录，不参与判分。**
            **describe_provenance(res.code or "", bool(res.executed), res.result),
        })

        # 3. 打分：直接用 analyze 的结构化结果
        out["executed"] = bool(res.executed)
        if res.executed:
            out["actual"] = res.result

        # 负向题（EV-B7）走自己的判据，不走 score_detail：clarify 要看 answer 与 executed，
        # 而 score_detail 只拿得到 result 一个值。硬塞进去等于让一个纯函数依赖整个 res。
        # expect_kind 为空时这里不触发，旧题路径逐字节不变。
        if case.expect_kind:
            verdict = negative_verdict(res, case)
            out["match"], out["negative_why"] = verdict["match"], verdict["why"]
            out["correct"] = verdict["match"] is not None
        elif res.executed:
            out["match"] = score_detail(res.result, case, expected_list)
            out["correct"] = out["match"] is not None

        # 缺口 14b：越界检查。clarify 也要查 —— 一边说"口径没说清"，一边给出百分比分布，
        # 用户看到的仍是推断结论，和拒答后又给分析是同一件事。
        if out["correct"] and (case.expect_refusal or case.expect_kind == "clarify"):
            leak, why = refusal_leak(res.answer)
            out["refusal_leak"], out["refusal_leak_why"] = leak, why
            if leak:
                out["correct"], out["match"] = False, None

        # 跨轮数字断言（EV-B5，规格 mt_007 的附加项）：最后一轮 answer 里的"有分量"数字
        # 必须能在第 recall_turn 轮的 result_text 里找到。这是结果层测不到的失败——
        # gold 是独立重算的，模型把第 1 轮的数记错、只要最后一轮逻辑对照样判对。
        # 证据取**最后一轮之前**的全部 result_text 而不只第 n 轮：最终答案常常同时复述
        # 几个轮次的数（"合计 X，其中 6 月 Y"），只认第 n 轮会把这些误判成编造；
        # 而幻觉了旧数字的失败样样都抓得到。这与规格字面（"∈ 第 1 轮"）的偏差记在
        # memory.md。没有 result_text 的轮次（执行失败）等于没有证据，此时不断言。
        if getattr(case, "recall_turn", 0) and multi and out["correct"]:
            from app.core.grounding import unverified_numbers
            src = "\n".join(t for t in turn_result_texts[:len(turn_result_texts) - 1] if t)
            missing = unverified_numbers(res.answer or "", [src]) if src else []
            if missing:
                out["correct"], out["match"] = False, None
                out["recall_why"] = (
                    f"答案里的数字 {missing} 在前几轮的 result_text 里都找不到（recall_turn={case.recall_turn}）")

        # 证据一致性（EV-B4）：三条断言，只作 warnings 展示不改 correct（升级门槛见模块 docstring）
        out["evidence"] = check_consistency(res, case)
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
    return score_detail(actual, case, expected_list) is not None


def score_detail(actual, case: EvalCase, expected_list: list):
    """判错返回 None；判对返回靠的是哪一层（M02）："refusal"，或 match_kind 的结果，
    匹配的是歧义题的备选答案时前面加 "alt:"（如 "alt:strict"）。"""
    if case.expect_refusal:
        return "refusal" if is_refusal(actual) else None
    if is_refusal(actual):
        return None
    for i, e in enumerate(expected_list):
        # 对错仍以 results_equal 为准（与阶段 3 判分逐题一致），match_kind 只负责标注层级
        if results_equal(actual, e, ordered=case.ordered, percent_equiv=case.percent_equiv):
            kind = match_kind(actual, e, ordered=case.ordered, percent_equiv=case.percent_equiv) or "relaxed"
            return kind if i == 0 else f"alt:{kind}"
    return None
