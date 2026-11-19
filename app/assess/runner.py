"""对快照目录跑契约；对两份快照集做差分（phase75-assess.md §0 ②、§2 第 1 步验收 ④）。

- `assess_dir(dir)`：每个快照文件 = 一题一次运行；逐个 node 行跑 contracts.check。
- `diff(before, after)`：按「题 → 环（节点#第几次）→ 契约」对齐，列出状态变化（ok↔fail，含 warn），
  以及只在一边出现的题 / 环。**只列不判**：没有总分、没有通过线，调用方退出码恒为 0。

题的键：run 行里有 case_id 就用它，否则用「数据集文件名::原问题」；同一键出现多次（--repeat）时依次加 #2、#3。
评估的任何数字都不是准确率（§0 规则 1）。
"""
from __future__ import annotations

import os
from collections import Counter

from app.assess import snapshot as snap
from app.assess.contracts import Context, check
from app.assess.snapshot import decode_state

_ORDER = {"ok": 0, "warn": 1, "fail": 2}


def case_key(run: dict) -> str:
    if run.get("case_id"):
        return str(run["case_id"])
    ds = run.get("dataset")
    if isinstance(ds, list):
        label = "+".join(os.path.basename(str(p)) for p in ds)
    else:
        label = os.path.basename(str(ds or "").rstrip("/\\"))
    return f"{label}::{run.get('question') or ''}"


def assess_snapshot(path: str) -> dict:
    s = snap.load(path)
    ctx = Context.from_run(s.run)
    rows = []
    for rec in s.nodes:
        state = decode_state(rec.get("input_state") or {})
        upd = decode_state(rec.get("updates") or {})
        for v in check(rec["node"], state, upd, ctx):
            d = v.to_dict()
            d.update({"node": rec["node"], "occurrence": rec["occurrence"], "seq": rec["seq"],
                      "ring": f"{rec['node']}#{rec['occurrence']}"})
            rows.append(d)
    return {"file": os.path.basename(path), "key": case_key(s.run), "question": s.run.get("question"),
            "trace_id": s.run.get("trace_id"), "today": s.run.get("today"),
            "complete": s.end is not None, "verdicts": rows}


def assess_dir(directory: str) -> dict:
    runs, seen = [], Counter()
    for p in snap.list_snapshots(directory):
        try:
            r = assess_snapshot(p)
        except Exception as e:  # noqa: BLE001  坏文件列出来，不中断整批
            runs.append({"file": os.path.basename(p), "key": f"<坏文件>{os.path.basename(p)}", "error": str(e),
                         "verdicts": []})
            continue
        seen[r["key"]] += 1
        if seen[r["key"]] > 1:
            r["key"] = f"{r['key']}#{seen[r['key']]}"
        runs.append(r)
    counts = Counter(v["status"] for r in runs for v in r["verdicts"])
    by_contract: dict = {}
    for r in runs:
        for v in r["verdicts"]:
            by_contract.setdefault(v["contract"], Counter())[v["status"]] += 1
    return {"directory": os.path.abspath(directory), "runs": runs,
            "summary": {"runs": len(runs), "verdicts": dict(counts),
                        "by_contract": {k: dict(c) for k, c in sorted(by_contract.items())}}}


def _index(report: dict) -> dict:
    out = {}
    for r in report["runs"]:
        rings = {}
        for v in r["verdicts"]:
            rings[(v["ring"], v["contract"])] = v
        out[r["key"]] = rings
    return out


def diff(before: dict, after: dict) -> dict:
    a, b = _index(before), _index(after)
    changes, only_before, only_after = [], sorted(set(a) - set(b)), sorted(set(b) - set(a))
    for key in sorted(set(a) & set(b)):
        ra, rb = a[key], b[key]
        for k in sorted(set(ra) | set(rb), key=lambda x: (x[0], x[1])):
            va, vb = ra.get(k), rb.get(k)
            sa = va["status"] if va else "absent"
            sb = vb["status"] if vb else "absent"
            if sa == sb:
                continue
            changes.append({"case": key, "ring": k[0], "contract": k[1], "before": sa, "after": sb,
                            "before_reason": (va or {}).get("reason", ""), "after_reason": (vb or {}).get("reason", ""),
                            "direction": _direction(sa, sb)})
    return {"before": before.get("directory"), "after": after.get("directory"),
            "only_before": only_before, "only_after": only_after, "changes": changes,
            "counts": dict(Counter(c["direction"] for c in changes))}


def _direction(sa: str, sb: str) -> str:
    if "absent" in (sa, sb):
        return "appeared" if sa == "absent" else "disappeared"
    return "worse" if _ORDER[sb] > _ORDER[sa] else "better"


# ------------------------------------------------------------------ markdown
def _cell(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")[:160]


def report_markdown(report: dict) -> str:
    s = report["summary"]
    lines = ["# 评估报告（契约，不是准确率）", "",
             f"- 目录：`{report['directory']}`", f"- 运行数：{s['runs']}",
             "- 判定：" + "，".join(f"{k} {v}" for k, v in sorted(s["verdicts"].items())), "",
             "## 按契约", "", "| 契约 | ok | warn | fail |", "|---|---|---|---|"]
    for c, cnt in s["by_contract"].items():
        lines.append(f"| {c} | {cnt.get('ok', 0)} | {cnt.get('warn', 0)} | {cnt.get('fail', 0)} |")
    lines += ["", "## 非 ok 的判定", "", "| 题 | 环 | 契约 | 状态 | 原因 |", "|---|---|---|---|---|"]
    for r in report["runs"]:
        if r.get("error"):
            lines.append(f"| {_cell(r['key'])} | - | - | error | {_cell(r['error'])} |")
        for v in r["verdicts"]:
            if v["status"] != "ok":
                lines.append(f"| {_cell(r['key'])} | {v['ring']} | {v['contract']} | {v['status']} | {_cell(v['reason'])} |")
    return "\n".join(lines) + "\n"


def diff_markdown(d: dict) -> str:
    lines = ["# 评估差分（只列变化，不判对错）", "",
             f"- before：`{d['before']}`", f"- after：`{d['after']}`",
             "- 变化：" + ("，".join(f"{k} {v}" for k, v in sorted(d["counts"].items())) or "无"), ""]
    if d["only_before"] or d["only_after"]:
        lines += ["## 只在一边出现的题", ""]
        lines += [f"- 仅 before：{_cell(k)}" for k in d["only_before"]]
        lines += [f"- 仅 after：{_cell(k)}" for k in d["only_after"]]
        lines.append("")
    lines += ["## 逐题、逐环", "", "| 题 | 环 | 契约 | before | after | before 原因 | after 原因 |",
              "|---|---|---|---|---|---|---|"]
    for c in d["changes"]:
        lines.append(f"| {_cell(c['case'])} | {c['ring']} | {c['contract']} | {c['before']} | {c['after']} | "
                     f"{_cell(c['before_reason'])} | {_cell(c['after_reason'])} |")
    return "\n".join(lines) + "\n"
