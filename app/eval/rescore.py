"""离线重新打分（B26）：比较器或标准答案改了之后，不再调用模型，直接用报告里存下的结构化结果重算。

- 只支持带 actual_obj 的报告（阶段 1.5 起）；更早的报告只存了文本预览，无法还原。
- 标准答案按当前 cases.py 在数据文件上重新执行，所以 gold 修正会生效。
- 还原后的对象索引类型可能变成字符串（JSON 限制），比较器对月份标签有归一规则；个别题可能与在线打分不同，
  差异会逐题列出，便于人工核对。
"""
import json

from app.eval.cases import ALL_CASES
from app.eval.comparator import results_equal
from app.eval.report import load_obj
from app.tools.csv_io import read_csv
from app.tools.sandbox import run_trusted


def rescore(report_path: str, data_path: str | None = None) -> dict:
    data = json.load(open(report_path, encoding="utf-8"))
    cases = {c.id: c for c in ALL_CASES}
    df = read_csv(data_path or data["data"])
    rows, changed, skipped = [], [], []
    for row in data["cases"]:
        case = cases.get(row["id"])
        if case is None or not row.get("executed"):
            rows.append({"id": row["id"], "category": row["category"], "correct": False})
            continue
        if not row.get("actual_obj"):
            skipped.append(row["id"])
            rows.append({"id": row["id"], "category": row["category"], "correct": row.get("correct")})
            continue
        expected, err = run_trusted(case.ground_truth, df.copy())
        try:
            actual = load_obj(row["actual_obj"])
        except Exception:
            skipped.append(row["id"])
            rows.append({"id": row["id"], "category": row["category"], "correct": row.get("correct")})
            continue
        ok = (err is None) and results_equal(actual, expected,
                                             ordered=case.ordered, percent_equiv=case.percent_equiv)
        if ok != row.get("correct"):
            changed.append({"id": row["id"], "before": row.get("correct"), "after": ok})
        rows.append({"id": row["id"], "category": row["category"], "correct": ok})
    by_cat = {}
    for r in rows:
        b = by_cat.setdefault(r["category"], [0, 0])
        b[0] += bool(r["correct"])
        b[1] += 1
    n = len(rows)
    correct = sum(bool(r["correct"]) for r in rows)
    return {"report": report_path, "n": n, "correct": correct,
            "correctness_rate": correct / n * 100 if n else None,
            "by_category": {k: {"correct": c, "n": t} for k, (c, t) in by_cat.items()},
            "changed": changed, "skipped_no_obj": skipped}  # 无结构化结果或还原失败的题，沿用原判定
