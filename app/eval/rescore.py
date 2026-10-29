"""离线重新打分（B26）：比较器或标准答案改了之后，不再调用模型，直接用报告里存下的结构化结果重算。

- 只支持带 actual_obj 的报告（阶段 1.5 起）；更早的报告只存了文本预览，无法还原。
- 标准答案按当前 cases.py 在数据文件上重新执行，所以 gold 修正会生效。
- 还原后的对象索引类型可能变成字符串（JSON 限制），比较器对月份标签有归一规则；个别题可能与在线打分不同，
  差异会逐题列出，便于人工核对。
"""
import json
from collections import Counter

from app.core.llm import api_error_text
from app.core.result import refusal_from_answer
from app.eval.cases import ALL_CASES
from app.eval.report import load_obj
from app.eval.report import evalset_fingerprint
from app.eval.runner import EvalRunner, score_detail


def rescore(report_path: str, data_path: str | None = None) -> dict:
    data = json.load(open(report_path, encoding="utf-8"))
    cases = {c.id: c for c in ALL_CASES}
    runner = EvalRunner(data_path or data.get("data"))     # 阶段 3：按题目的 dataset 取表
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
            if ok != row.get("correct"):
                changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
            rows.append({"id": row["id"], "category": row["category"],
                         "dataset": row.get("dataset"), "correct": ok, "match": kind})
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
        if ok != row.get("correct"):
            changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
        rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"),
                     "correct": ok, "match": kind})
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
            "changed": changed, "skipped_no_obj": skipped, "infra_errors": infra,  # 无结构化结果或还原失败的题，沿用原判定
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

    overall = data.setdefault("overall", {})
    n_ok = sum(1 for r in data["cases"] if r.get("correct"))
    n = len(data["cases"])
    executed = sum(1 for r in data["cases"] if r.get("executed"))
    overall["correct"] = n_ok
    overall["correctness_rate"] = n_ok / n * 100 if n else None
    overall["conditional_correctness_rate"] = n_ok / executed * 100 if executed else None
    overall["match_kinds"] = dict(Counter(r.get("match") or "?" for r in data["cases"] if r.get("correct")))
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
    })
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return {"path": report_path, "n": n, "correct": n_ok, "changed": result["changed"],
            "run_code_sha12": data["run_code_sha12"], "scorer_sha12": fp_now}
