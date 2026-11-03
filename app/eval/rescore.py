"""离线重新打分（B26）：比较器或标准答案改了之后，不再调用模型，直接用报告里存下的结构化结果重算。

- 只支持带 actual_obj 的报告（阶段 1.5 起）；更早的报告只存了文本预览，无法还原。
- 标准答案按当前 cases.py 在数据文件上重新执行，所以 gold 修正会生效。
- 还原后的对象索引类型可能变成字符串（JSON 限制），比较器对月份标签有归一规则；个别题可能与在线打分不同，
  差异会逐题列出，便于人工核对。
"""
import json
import os
from collections import Counter

from app.core.llm import api_error_text
from app.core.result import refusal_from_answer
from app.eval.case_model import EvalCase
from app.eval.cases import ALL_CASES
from app.eval.report import load_obj
from app.eval.report import evalset_fingerprint
from app.eval.runner import EvalRunner, score_detail
from app.eval.comparator import refusal_leak


def _questions_sha(questions) -> str:
    """题面数组的稳定哈希，**必须**与 `scripts/holdout/run_holdout.py:_sha256` 逐字节一致。

    算法抄了一份（scripts/ 不在包路径里，import 不进来），所以
    `tests/test_rescore_holdout.py::test_questions_sha_matches_run_holdout` 拿同一份数据
    对比两边的结果 —— 谁改了算法而没改另一边，那条测试立刻红。
    """
    import hashlib

    blob = json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _holdout_setup(meta: dict):
    """holdout 报告：题目不在 ALL_CASES 里，得从题库目录重建 cases 与 datasets。

    不重建会怎样：`cases.get(row["id"])` 对 63 个 holdout 题号一律返回 None，全走
    `case is None` 分支判 correct=False —— 一份 54/63 的报告 rescore 出来是 **0.0%**，
    而且 `changed` 是空的（压根没进新旧对比），看上去像"新判分器把题全判错了"。
    实测过一次：n=63 / correct=0 / rate=0.0 / changed=0。

    题库目录读不到时**抛错**，不返回空 dict —— 静默退化成分数归零比报错危险得多。

    重建规则与 `scripts/holdout/run_holdout.py:build_cases` 一致（题面取 questions.json，
    答案取 answers.json 的 ground_truth 表达式）。那侧的一致性校验（缺答案/题号重复/
    数据集没注册）在这里降级成只报"缺东西"，因为 rescore 面对的是已经跑完的报告。

    另外核对题库哈希：报告记了 `holdout.questions_sha256`，题库后来被改过（补题面提示、
    改答案）就对不上。**只警告不拦** —— 硬失败会让"改过题面的报告永远不能再判"，
    而重判恰恰是这类报告最需要的能力；但不说一声就等于用新答案判旧输出。
    """
    base = (meta or {}).get("dir")
    if not base:
        return {}, None, None
    qpath = os.path.join(base, "questions.json")
    apath = os.path.join(base, "answers.json")
    if not (os.path.exists(qpath) and os.path.exists(apath)):
        raise FileNotFoundError(
            f"holdout 题库目录不可用：{base}（缺 questions.json 或 answers.json）\n"
            "这份报告是用那份题库跑出来的，重建不了标准答案就不该 rescore。"
        )
    with open(qpath, encoding="utf-8") as f:
        spec = json.load(f)
    with open(apath, encoding="utf-8") as f:
        ans = (json.load(f).get("answers") or {})

    cases = {}
    problems = []
    for q in spec.get("questions") or []:
        cid = q.get("id")
        a = ans.get(cid) or {}
        gt = (a.get("ground_truth") or "").strip()
        if not cid or not gt:
            # 不能 continue：漏一道题就是 `case is None` → 静默判 correct=False，
            # 而且这一路不写 changed，分数掉了也看不出是哪道题掉的。
            problems.append(f"{cid or '<无 id>'}: 题面或答案缺失")
            continue
        if q.get("dataset") not in (spec.get("datasets") or {}):
            problems.append(f"{cid}: dataset={q.get('dataset')!r} 未在 datasets 里注册")
        cases[cid] = EvalCase(
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
        )

    datasets = {}
    for name, rel in (spec.get("datasets") or {}).items():
        datasets[name] = rel if os.path.isabs(rel) else os.path.abspath(os.path.join(base, rel))
    if problems:
        raise ValueError(
            f"holdout 题库 {base} 与报告对不上（{len(problems)} 处）：\n  "
            + "\n  ".join(problems[:10])
            + ("\n  …" if len(problems) > 10 else "")
        )
    if datasets and "sales" not in datasets:
        # 同 run_holdout._pad_sales：runner.py:79 硬依赖 datasets["sales"]，赋值后无人读取
        datasets["sales"] = next(iter(datasets.values()))

    drift = None
    want = (meta or {}).get("questions_sha256")
    got = _questions_sha(spec.get("questions"))
    if want and want != got:
        drift = {"report": want, "bank": got}
    return cases, (datasets or None), drift


def rescore(report_path: str, data_path: str | None = None) -> dict:
    data = json.load(open(report_path, encoding="utf-8"))
    cases = {c.id: c for c in ALL_CASES}
    holdout_cases, holdout_datasets, bank_drift = _holdout_setup(data.get("holdout"))
    cases.update(holdout_cases)
    if bank_drift:
        print(
            "⚠️  题库与这份报告不是同一版（questions 哈希对不上）：\n"
            f"     报告记录：{bank_drift['report']}\n"
            f"     题库现在：{bank_drift['bank']}\n"
            "   题面或答案在报告跑完之后被改过 —— 下面的判定用的是**现在的**答案。"
        )
    if holdout_cases:
        # holdout 报告的题号必须全在题库里：缺一道就会走 `case is None` 静默判 False
        unknown = sorted({r["id"] for r in data["cases"]} - set(cases))
        if unknown:
            raise ValueError(
                f"报告里有 {len(unknown)} 道题在题库中找不到：{unknown[:8]}"
                + ("…" if len(unknown) > 8 else "")
            )
    runner = EvalRunner(data_path or data.get("data"), datasets=holdout_datasets)     # 阶段 3：按题目的 dataset 取表
    rows, changed, skipped, infra = [], [], [], []
    for row in data["cases"]:
        case = cases.get(row["id"])
        if api_error_text(row.get("answer")) is not None:
            infra.append(row["id"])          # B45：旧报告里网关错误 JSON 被当成了结论，按基础设施失败记
        refusal = refusal_from_answer(row.get("answer"))
        if case is not None and refusal is not None and not row.get("actual_obj"):
            # B40：ReAct 没调工具、直接在结论里按契约拒答，旧报告里 result 为空
            expected_list, err = runner.expected_all(case)
            kind = score_detail(refusal, case, expected_list) if err is None else None
            ok = kind is not None
            leak, why = refusal_leak(row.get("answer")) if (ok and case.expect_refusal) else (None, "")
            if leak:
                ok, kind = False, None            # 缺口 14b：拒答越界，见 comparator 规则 24
            if ok != row.get("correct"):
                changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
            rows.append({"id": row["id"], "category": row["category"],
                         "dataset": row.get("dataset"), "correct": ok, "match": kind,
                         "refusal_leak": leak, "refusal_leak_why": why})
            continue
        if case is None or not row.get("executed"):
            rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"), "correct": False})
            continue
        if not row.get("actual_obj"):
            skipped.append(row["id"])
            rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"), "correct": row.get("correct")})
            continue
        expected_list, err = runner.expected_all(case)
        try:
            actual = load_obj(row["actual_obj"])
        except Exception:
            skipped.append(row["id"])
            rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"), "correct": row.get("correct")})
            continue
        kind = score_detail(actual, case, expected_list) if err is None else None
        ok = kind is not None
        leak, why = refusal_leak(row.get("answer")) if (ok and case.expect_refusal) else (None, "")
        if leak:
            ok, kind = False, None                # 缺口 14b：拒答越界，见 comparator 规则 24
        if ok != row.get("correct"):
            changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
        rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"),
                     "correct": ok, "match": kind,
                     "refusal_leak": leak, "refusal_leak_why": why})
    by_cat = {}
    for r in rows:
        b = by_cat.setdefault(r["category"], [0, 0])
        b[0] += bool(r["correct"])
        b[1] += 1
    by_ds = {}
    for r in rows:
        b = by_ds.setdefault(r.get("dataset") or "sales", [0, 0])
        b[0] += bool(r["correct"])
        b[1] += 1
    n = len(rows)
    correct = sum(bool(r["correct"]) for r in rows)
    return {"report": report_path, "n": n, "correct": correct,
            "correctness_rate": correct / n * 100 if n else None,
            "by_category": {k: {"correct": c, "n": t} for k, (c, t) in by_cat.items()},
            "by_dataset": {k: {"correct": c, "n": t} for k, (c, t) in by_ds.items()},
            "match_kinds": dict(Counter(r.get("match") or "?" for r in rows if r["correct"])),
            "needs_audit": [r["id"] for r in rows if r["correct"] and r.get("match") not in ("strict", "rounded", "refusal", "alt:strict", "alt:rounded")],
            "evalset_now": evalset_fingerprint()["sha256"],
            "evalset_report": (data.get("evalset") or {}).get("sha256"),
            # 缺口 14b：这份报告里有多少应拒答题是"result 拒答了、answer 还是把问题答了"
            "refusal_leaks": [{"id": r["id"], "why": r.get("refusal_leak_why")}
                              for r in rows if r.get("refusal_leak")],
            "changed": changed, "skipped_no_obj": skipped, "infra_errors": infra,  # 无结构化结果或还原失败的题，沿用原判定
            "bank_drift": bank_drift,          # 题库换过版本时记下两边的哈希，None = 同一版
            "rows": rows}


def apply_rescore(report_path: str, result: dict) -> dict:
    """把 rescore 的逐题判定写回报告，让报告、台账、指纹三者对得上。

    只改判定，不动模型输出（code / answer / actual 原样保留）。同时记两块元信息：
    `rescored`（判分用的代码指纹与变化清单）和 `run_code_sha12`（模型跑在哪份代码上）。
    判分器在 A 组指纹里，改它会让 code_sha12 变——不把"跑的指纹"单独留一份，
    之后就没法回答"这份报告到底是哪套被测系统跑出来的"。
    """
    import json
    from datetime import datetime

    from app.eval.fingerprint import code_fingerprint

    data = json.load(open(report_path, encoding="utf-8"))
    old_fp = (data.get("fingerprints") or {}).get("code_sha12")
    by_id = {r["id"]: r for r in result["rows"]}
    for row in data.get("cases", []):
        r = by_id.get(row["id"])
        if r is None:
            continue
        row["correct"] = bool(r["correct"])
        row["match"] = r.get("match")
        # 缺口 14b：越界标记要跟着判定一起写回，否则报告里"为什么判错"又看不见了
        row["refusal_leak"] = r.get("refusal_leak")
        row["refusal_leak_why"] = r.get("refusal_leak_why") or ""

    overall = data.setdefault("overall", {})
    n_ok = sum(1 for r in data["cases"] if r.get("correct"))
    n = len(data["cases"])
    executed = sum(1 for r in data["cases"] if r.get("executed"))
    overall["correct"] = n_ok
    overall["correctness_rate"] = n_ok / n * 100 if n else None
    overall["conditional_correctness_rate"] = n_ok / executed * 100 if executed else None
    overall["match_kinds"] = dict(Counter(r.get("match") or "?" for r in data["cases"] if r.get("correct")))
    # 缺口 14b：越界清单也要跟着逐题判定一起重算，否则报告顶层还留着旧尺子的结论
    overall["refusal_leaks"] = [{"id": row.get("id"), "why": row.get("refusal_leak_why") or ""}
                                for row in data["cases"] if row.get("refusal_leak")]
    for key, field in (("by_category", "category"), ("by_dataset", "dataset")):
        bucket = data.get(key) or {}
        tot = {}
        kinds = {}
        for r in data["cases"]:
            k = r.get(field) or "sales"
            b = tot.setdefault(k, [0, 0])
            b[0] += bool(r.get("correct"))
            b[1] += 1
            if r.get("correct"):
                kinds.setdefault(k, Counter())[r.get("match") or "?"] += 1
        for k, b in bucket.items():
            if k in tot:
                b["correct"], b["n"] = tot[k][0], tot[k][1]
                b["correctness_rate"] = tot[k][0] / tot[k][1] * 100 if tot[k][1] else None
                b["match_kinds"] = dict(kinds.get(k, {}))

    fp_now = code_fingerprint()["affects_results_sha256"][:12]
    data["run_code_sha12"] = data.get("run_code_sha12") or old_fp
    data.setdefault("fingerprints", {})["code_sha12"] = fp_now
    data.setdefault("rescored", []).append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "runner_before": old_fp, "scorer": fp_now,
        "changed": result["changed"], "n_correct": n_ok, "n": n,
        # 题库换过版本时留痕：报告跑在旧题面、判定用的是新答案，这件事不能只活在 stdout 里
        "bank_drift": result.get("bank_drift"),
    })
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return {"path": report_path, "n": n, "correct": n_ok, "changed": result["changed"],
            "run_code_sha12": data["run_code_sha12"], "scorer_sha12": fp_now,
            "bank_drift": result.get("bank_drift")}
