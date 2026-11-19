"""对快照目录跑契约；对两份快照集做差分（phase75-assess.md §0 ②、§2 第 1 步验收 ④）。

- `assess_dir(dir)`：每个快照文件 = 一题一次运行；逐个 node 行跑 contracts.check。
- `diff(before, after)`：按「题 → 环（节点#第几次）→ 契约」对齐，列出状态变化（ok / warn / fail / not_checked
  四态之间任意两态的变化都列，含 ok↔not_checked），以及只在一边出现的环。一边整题没有快照的题报
  `snapshot_missing`（写明缺 before 还是 after），不当成「没变化」。**只列不判**：没有总分、没有通过线，
  调用方退出码恒为 0。

题的键：run 行里有 case_id 就用它，否则用「数据集文件名::原问题」；同一键出现多次（--repeat）时依次加 #2、#3。
评估的任何数字都不是准确率（§0 规则 1）。
"""
from __future__ import annotations

import os
from collections import Counter

from app.assess import snapshot as snap
from app.assess.contracts import NOT_CHECKED, STATUSES, Context, check
from app.assess.snapshot import decode_state

_ORDER = {"ok": 0, "warn": 1, "fail": 2}       # not_checked 不在序里：它和任何一态之间都不是「好 / 坏」，而是「查没查」
_BROKEN = "<坏文件>"


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
            runs.append({"file": os.path.basename(p), "key": f"{_BROKEN}{os.path.basename(p)}", "error": str(e),
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
    # 四态都写出来（含 0）：not_checked 单列统计，不能因为是 0 就从 JSON 里消失，也不能并进 ok。
    full = lambda c: {s: c.get(s, 0) for s in STATUSES}  # noqa: E731
    return {"directory": os.path.abspath(directory), "runs": runs,
            "summary": {"runs": len(runs), "verdicts": full(counts), "not_checked": counts.get(NOT_CHECKED, 0),
                        "by_contract": {k: full(c) for k, c in sorted(by_contract.items())}}}


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
    # 一边整题没有快照：不是「没变化」，单独报 snapshot_missing，写明缺哪一边。坏文件（读不出题键）另列。
    for key, missing in [(k, "after") for k in only_before] + [(k, "before") for k in only_after]:
        if key.startswith(_BROKEN):
            continue
        changes.append({"case": key, "ring": "-", "contract": "-",
                        "before": "missing" if missing == "before" else "present",
                        "after": "missing" if missing == "after" else "present",
                        "before_reason": "", "after_reason": "",
                        "direction": "snapshot_missing", "missing": missing})
    unreadable = {"before": sorted(k[len(_BROKEN):] for k in a if k.startswith(_BROKEN)),
                  "after": sorted(k[len(_BROKEN):] for k in b if k.startswith(_BROKEN))}
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
            "only_before": only_before, "only_after": only_after, "unreadable": unreadable,
            "snapshot_missing": [{"case": c["case"], "missing": c["missing"]}
                                 for c in changes if c["direction"] == "snapshot_missing"],
            "changes": changes,
            "counts": dict(Counter(c["direction"] for c in changes))}


def _direction(sa: str, sb: str) -> str:
    """absent：这一环 / 这条契约只在一边出现；not_checked ↔ 其他三态：查没查变了（不是好坏）；其余按 ok<warn<fail。"""
    if "absent" in (sa, sb):
        return "appeared" if sa == "absent" else "disappeared"
    if sb == NOT_CHECKED:
        return "now_unchecked"
    if sa == NOT_CHECKED:
        return "now_checked"
    return "worse" if _ORDER[sb] > _ORDER[sa] else "better"


# ------------------------------------------------------------------ markdown
def _cell(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")[:160]


def report_markdown(report: dict) -> str:
    s = report["summary"]
    v = s["verdicts"]
    lines = ["# 评估报告（契约，不是准确率）", "",
             f"- 目录：`{report['directory']}`", f"- 运行数：{s['runs']}",
             "- 判定：" + "，".join(f"{k} {v.get(k, 0)}" for k in STATUSES),
             f"- 未检查（not_checked）：{s.get('not_checked', v.get(NOT_CHECKED, 0))} —— 契约没有可判断的材料，**不计入 ok**",
             "", "## 按契约", "", "| 契约 | ok | warn | fail | not_checked |", "|---|---|---|---|---|"]
    for c, cnt in s["by_contract"].items():
        lines.append(f"| {c} | {cnt.get('ok', 0)} | {cnt.get('warn', 0)} | {cnt.get('fail', 0)} | {cnt.get(NOT_CHECKED, 0)} |")
    lines += ["", "## warn / fail 的判定", "", "| 题 | 环 | 契约 | 状态 | 原因 |", "|---|---|---|---|---|"]
    unchecked: Counter = Counter()
    for r in report["runs"]:
        if r.get("error"):
            lines.append(f"| {_cell(r['key'])} | - | - | error | {_cell(r['error'])} |")
        for v in r["verdicts"]:
            if v["status"] == NOT_CHECKED:
                unchecked[(v["contract"], v["reason"])] += 1
            elif v["status"] != "ok":
                lines.append(f"| {_cell(r['key'])} | {v['ring']} | {v['contract']} | {v['status']} | {_cell(v['reason'])} |")
    lines += ["", "## not_checked 的原因（按契约汇总）", "", "| 契约 | 原因 | 次数 |", "|---|---|---|"]
    for (c, why), n in sorted(unchecked.items(), key=lambda x: (x[0][0], -x[1], x[0][1])):
        lines.append(f"| {c} | {_cell(why)} | {n} |")
    return "\n".join(lines) + "\n"


def diff_markdown(d: dict) -> str:
    lines = ["# 评估差分（只列变化，不判对错）", "",
             f"- before：`{d['before']}`", f"- after：`{d['after']}`",
             "- 变化：" + ("，".join(f"{k} {v}" for k, v in sorted(d["counts"].items())) or "无"), ""]
    miss = d.get("snapshot_missing") or []
    if miss:
        lines += ["## snapshot_missing（一边没有这道题的快照，不是没变化）", ""]
        lines += [f"- 缺 {m['missing']}：{_cell(m['case'])}" for m in miss]
        lines.append("")
    unread = d.get("unreadable") or {}
    if unread.get("before") or unread.get("after"):
        lines += ["## 读不出的快照文件", ""]
        lines += [f"- {side}：{_cell(f)}" for side in ("before", "after") for f in unread.get(side, [])]
        lines.append("")
    lines += ["## 逐题、逐环", "", "| 题 | 环 | 契约 | before | after | 方向 | before 原因 | after 原因 |",
              "|---|---|---|---|---|---|---|---|"]
    for c in d["changes"]:
        if c["direction"] == "snapshot_missing":
            continue
        lines.append(f"| {_cell(c['case'])} | {c['ring']} | {c['contract']} | {c['before']} | {c['after']} | "
                     f"{c['direction']} | {_cell(c['before_reason'])} | {_cell(c['after_reason'])} |")
    return "\n".join(lines) + "\n"
