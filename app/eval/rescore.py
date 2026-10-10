"""离线重新打分（B26）：比较器或标准答案改了之后，不再调用模型，直接用报告里存下的结构化结果重算。

- 只支持带 actual_obj 的报告（阶段 1.5 起）；更早的报告只存了文本预览，无法还原。
- 标准答案按当前 cases.py 在数据文件上重新执行，所以 gold 修正会生效。
- 还原后的对象索引类型可能变成字符串（JSON 限制），比较器对月份标签有归一规则；个别题可能与在线打分不同，
  差异会逐题列出，便于人工核对。
"""
import json

from app.core.result import refusal_from_answer
from app.eval.cases import ALL_CASES
from app.eval.report import load_obj
from app.eval.runner import EvalRunner, score


def rescore(report_path: str, data_path: str | None = None) -> dict:
    data = json.load(open(report_path, encoding="utf-8"))
    cases = {c.id: c for c in ALL_CASES}
    runner = EvalRunner(data_path or data.get("data"))     # 阶段 3：按题目的 dataset 取表
    rows, changed, skipped = [], [], []
    for row in data["cases"]:
        case = cases.get(row["id"])
        refusal = refusal_from_answer(row.get("answer"))
        if case is not None and refusal is not None and not row.get("actual_obj"):
            # B40：ReAct 没调工具、直接在结论里按契约拒答，旧报告里 result 为空
            expected_list, err = runner.expected_all(case)
            ok = (err is None) and score(refusal, case, expected_list)
            if ok != row.get("correct"):
                changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
            rows.append({"id": row["id"], "category": row["category"],
                         "dataset": row.get("dataset"), "correct": ok})
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
        ok = (err is None) and score(actual, case, expected_list)
        if ok != row.get("correct"):
            changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
        rows.append({"id": row["id"], "category": row["category"], "dataset": row.get("dataset"), "correct": ok})
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
            "changed": changed, "skipped_no_obj": skipped}  # 无结构化结果或还原失败的题，沿用原判定
