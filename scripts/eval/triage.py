"""EV-D2 失败归因：把报告里的失败码翻成"该去改哪个模块"。

用法：
    python scripts/eval/triage.py docs/eval/gate_20261012_104407_react.json
    python scripts/eval/triage.py outputs/mul_state.json --json
    python scripts/eval/triage.py outputs/gate.json outputs/eval.json   # 多份合并

读两种报告，语义不同、**都不猜**：
1. **闸门报告**（`scripts/gate/`）：人工填 `failure_class`（1–6 或自由文本）。
2. **评测报告**（`run_eval.py`）：机器填 `evidence.failures`（`ANSWER_RESULT_MISMATCH` 等）。

三条纪律（与 `app/eval/failure_classes.py` 的模块注释同源）：
- 映射不上的 `failure_class` **一律打印**并以非 0 退出 —— 静默丢弃等于假装归因完成；
- `error` / tier=llm/cancelled/interrupted 的行归 `infra` 桶，不算模型错；
- 报告里根本没有失败字段时，明说"这份报告没带失败信息"，不输出一行"0 未映射"冒充检查过。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from app.eval import failure_classes as FC  # noqa: E402

INFRA_TIERS = {"llm", "cancelled", "interrupted", "dataset"}


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rows(report: dict) -> list[dict]:
    return report.get("cases") or report.get("rows") or []


def collect(report: dict, src: str) -> dict:
    """把一份报告拆成 {human, auto, infra, unlabeled}，每个元素都带来源文件名。"""
    human, auto, infra, unlabeled = [], [], [], []
    for r in _rows(report):
        cid = r.get("id") or r.get("case_id") or "?"
        tier = (r.get("tier") or "").lower()
        if r.get("error") or tier in INFRA_TIERS:
            infra.append({"src": src, "id": cid, "why": str(r.get("error") or tier)[:160]})
            continue
        fc = r.get("failure_class")
        if fc not in (None, "", 0):
            human.append({"src": src, "id": cid, "raw": fc})
        for code in ((r.get("evidence") or {}).get("failures") or []):
            auto.append({"src": src, "id": cid, "raw": code})
        # 判错了但既没 error 也没任何失败码 → 归因缺口，必须暴露
        failed = r.get("correct") is False or r.get("human_correct") is False
        if failed and fc in (None, "", 0) and not ((r.get("evidence") or {}).get("failures") or []):
            # 扰动题例外：variant_kind 本身就是确定性归因信号（哪种鲁棒性被打破）
            vcode = FC.code_for_variant(r.get("variant_kind"))
            if vcode:
                auto.append({"src": src, "id": cid, "raw": vcode,
                             "via": f"variant_kind={r.get('variant_kind')}"})
            else:
                unlabeled.append({"src": src, "id": cid})
    return {"human": human, "auto": auto, "infra": infra, "unlabeled": unlabeled}


def triage(reports: dict[str, dict]) -> dict:
    buckets: dict[str, list[dict]] = {}
    unmapped: list[dict] = []
    infra: list[dict] = []
    unlabeled: list[dict] = []
    seen_failure_field = False

    for src, report in reports.items():
        got = collect(report, src)
        if got["human"] or got["auto"]:
            seen_failure_field = True
        infra += got["infra"]
        unlabeled += got["unlabeled"]
        for item in got["human"] + got["auto"]:
            # 已经是稳定码就直接归，不再走关键词（防止新码的关键词覆盖不到自己）
            cls = FC.BY_CODE.get(str(item["raw"])) if isinstance(item["raw"], str) else None
            cls = cls or FC.match(item["raw"])
            if cls is None:
                unmapped.append(item)
                continue
            entry = {"src": item["src"], "id": item["id"], "raw": item["raw"]}
            if item.get("via"):
                entry["via"] = item["via"]
            buckets.setdefault(cls.code, []).append(entry)
    return {"buckets": buckets, "unmapped": unmapped, "infra": infra,
            "unlabeled": unlabeled, "saw_failure_field": seen_failure_field}


def render(result: dict) -> str:
    out = []
    if not result["saw_failure_field"] and not result["unlabeled"]:
        out.append("这份报告没有带失败信息（既无 failure_class 也无 evidence.failures，且无判错行）"
                   " —— 没有归因可做，不是「检查通过」。")
        return "\n".join(out)

    if result["buckets"]:
        out.append("## 按码归因")
        for code in sorted(result["buckets"]):
            items = result["buckets"][code]
            c = FC.BY_CODE[code]
            out.append(f"\n[{code}] {c.label}  —— {len(items)} 例")
            out.append(f"  落点：{c.module}")
            out.append(f"  首修：{c.fix}")
            ids = "、".join(f"{i['id']}@{os.path.basename(i['src'])}" for i in items[:8])
            more = f" …另 {len(items) - 8} 例" if len(items) > 8 else ""
            out.append(f"  题号：{ids}{more}")

    if result["unmapped"]:
        out.append("\n## 未映射（必须清零：补 failure_classes.py + failure-map.md 的码与关键词）")
        for i in result["unmapped"]:
            out.append(f"  - {i['id']}@{os.path.basename(i['src'])}: {i['raw']!r}")

    if result["unlabeled"]:
        out.append("\n## 判错但没有失败码（归因缺口：先补标注，别让 triage 假装覆盖）")
        for i in result["unlabeled"][:10]:
            out.append(f"  - {i['id']}@{os.path.basename(i['src'])}")
        if len(result["unlabeled"]) > 10:
            out.append(f"  …另 {len(result['unlabeled']) - 10} 例")

    if result["infra"]:
        out.append("\n## infra（不算模型错，别混进失败率）")
        for i in result["infra"][:10]:
            out.append(f"  - {i['id']}@{os.path.basename(i['src'])}: {i['why']}")
        if len(result["infra"]) > 10:
            out.append(f"  …另 {len(result['infra']) - 10} 例")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="失败归因（EV-D2）")
    ap.add_argument("reports", nargs="+", help="一份或多份报告 JSON")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args(argv)

    reports = {p: load(p) for p in args.reports}
    result = triage(reports)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 1 if result["unmapped"] else 0


if __name__ == "__main__":
    sys.exit(main())
