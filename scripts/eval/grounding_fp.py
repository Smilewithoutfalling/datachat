"""S3-4 grounding 假阳率量测（issue #132，phase75-step3 §5）：只量不改。

用法：
    python scripts/eval/grounding_fp.py REPORT.json --snapshots SNAP_DIR [--md OUT.md] [--json OUT.json]

## 输入为什么是「报告 + 同批快照」，不是 report_adapter 的 unverified

issue #132 原稿写的是「用 report_adapter 的 unverified 条目」。代码里拿不到：
202 题报告由 `app/eval/runner.py` 写，它的逐题字典**没有** `unverified_numbers`
（只有 `scripts/gate/run_gate.py` 的 25 题闸门报告写这个键），所以
`report_adapter.Row.unverified` 对 202 题报告恒为 0。照原稿做，「条目数守恒」会是 0 = 0 的假绿。

两种证据口径分别从这两处取：

- **评测口径**（`app/eval/consistency.py` 断言 1，证据 = result_text + str(result)，不含问题原文）：
  报告逐题的 `evidence.detail.answer_nums_missing`，`evidence.applicable` 为假的题不适用。
- **产品口径**（`app/core/service.py:427-430`，证据 = 问题（改写后）+ result_text + metrics_block，
  改写过时再加原问题；只算已执行且非拒答的题）：报告里没有 result_text / metrics_block，
  从同一批的节点快照重算——取该题最后一份快照里最后一次 summarizer 的 input_state
  （即总结时看到的最终状态），调用同一个 `app.core.grounding.unverified_numbers`。
  结论文本两种口径都用报告里的 `answer`（同一个 res.answer）。

ReAct 没有节点行，这类题的产品口径记为「无快照」，单独计数，不静默丢掉。

## 四类（判定顺序即优先级）

1. 百分比：数字带 % / ％，或后面紧跟「个百分点 / 百分点」。
2. 派生数：数字前 8 个字内出现差、和、比、均值一类的词（增长、下降、相差、合计、平均、占比、
   环比、同比……），或后面紧跟「倍」。这类数本来就不在证据里，是假阳的主要来源。
3. 带单位的计数/金额：数字前有货币符号（¥ ￥ $），或带 万/亿，或后面 3 个字内紧跟量词/货币单位
   （元、单、件、个、人、次、笔……）。S 的门槛（假阳率 <5% 才考虑拦）只看这一类。
4. 其他：以上都不是。

本脚本只分类、只列条目，不判「是不是真编造」——那是 #135 的人工标注。
退出码：0 正常；2 输入有问题（文件不存在、不是 202 题评测报告、快照目录不存在）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.assess import snapshot as snap  # noqa: E402
from app.core.grounding import unverified_numbers  # noqa: E402
from app.core.result import refusal_from_answer  # noqa: E402
from app.eval.report_adapter import KIND_EVAL, ReportError, kind_of, load as load_json  # noqa: E402

KINDS = ("带单位的计数/金额", "百分比", "派生数", "其他")
K_COUNT, K_PCT, K_DERIVED, K_OTHER = KINDS

_DERIVED_WORDS = ("增长", "增加", "增幅", "下降", "减少", "降幅", "降低", "提升", "上升", "回落",
                  "相差", "差距", "差额", "差值", "高出", "低于", "多出", "少了", "多了",
                  "合计", "总计", "共计", "总和", "累计", "平均", "均值", "人均", "中位数",
                  "占比", "比例", "比重", "环比", "同比", "倍")
_COUNT_UNITS = ("万元", "亿元", "元", "块", "美元", "单", "件", "个", "人", "名", "位", "次", "笔",
                "台", "家", "户", "条", "张", "份", "箱", "袋", "瓶", "辆", "套", "项", "笔",
                "千克", "公斤", "吨", "克", "kg", "天", "小时", "分钟", "单位")
_CURRENCY = ("¥", "￥", "$")
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


# ------------------------------------------------------------------ 分类
def _find(raw: str, answer: str) -> int:
    """raw 在结论里第一次出现的位置（与 grounding 的去重保序一致：只看首次）。"""
    i = answer.find(raw)
    return i if i >= 0 else 0


def classify(raw: str, answer: str) -> str:
    """一个未核实数字（grounding 给的原文写法）属于四类中的哪一类。"""
    i = _find(raw, answer)
    before = answer[max(0, i - 8):i]
    after = answer[i + len(raw):i + len(raw) + 8].lstrip()
    if raw.endswith(("%", "％")) or after.startswith(("个百分点", "百分点")):
        return K_PCT
    if any(w in before for w in _DERIVED_WORDS) or after.startswith("倍"):
        return K_DERIVED
    if before.rstrip().endswith(_CURRENCY) or raw.endswith(("万", "亿")) \
            or any(after.startswith(u) for u in _COUNT_UNITS):
        return K_COUNT
    return K_OTHER


def sentence_of(raw: str, answer: str) -> str:
    for s in _SENT_SPLIT.split(answer or ""):
        if raw in s:
            return s.strip()
    return ""


# ------------------------------------------------------------------ 两种口径
def eval_scope(case: dict):
    """评测口径的未核实列表；不适用（未执行、拒答类、旧报告无 evidence）时返回 None。"""
    ev = case.get("evidence")
    if not isinstance(ev, dict) or not ev.get("applicable"):
        return None
    return list((ev.get("detail") or {}).get("answer_nums_missing") or [])


def product_evidence(s: snap.Snapshot):
    """按 service.py:427-430 拼产品口径的证据；快照里没有 summarizer 时返回 None。"""
    rows = [r for r in s.nodes if r.get("node") == "summarizer"]
    if not rows:
        return None
    st = snap.decode_state(rows[-1].get("input_state") or {})
    question = st.get("question") or s.run.get("rewritten_question") or ""
    ev = [question, st.get("result_text") or ""]
    if st.get("metrics_block"):
        ev.append(st["metrics_block"])
    original = s.run.get("question") or ""
    if original and original != question:
        ev.append(original)
    return ev


def product_scope(case: dict, s):
    """产品口径的未核实列表；无快照返回 None，不适用（未执行、拒答）返回 []。"""
    if s is None:
        return None
    answer = case.get("answer") or ""
    if not (answer and case.get("executed")) or refusal_from_answer(answer) is not None:
        return []
    ev = product_evidence(s)
    if ev is None:
        return None
    return unverified_numbers(answer, ev)


def index_snapshots(directory: str) -> dict:
    """case_id → 该题最后一份快照（多轮题取最后一轮；按 run 行的 started_at_utc，再按文件名）。"""
    best = {}
    for path in snap.list_snapshots(directory):
        try:
            s = snap.load(path)
        except (ValueError, json.JSONDecodeError):
            continue
        cid = s.run.get("case_id")
        if not cid:
            continue
        key = (s.run.get("started_at_utc") or "", os.path.basename(path))
        if cid not in best or key > best[cid][0]:
            best[cid] = (key, s)
    return {k: v[1] for k, v in best.items()}


# ------------------------------------------------------------------ 汇总
def measure(report: dict, snapshots: dict) -> dict:
    entries, no_snapshot, eval_total = [], [], 0
    for case in report.get("cases") or []:
        cid = str(case.get("id") or "")
        answer = case.get("answer") or ""
        ev_list = eval_scope(case)
        pr_list = product_scope(case, snapshots.get(cid))
        if pr_list is None and case.get("executed") and answer:
            no_snapshot.append(cid)
        eval_total += len(ev_list or [])
        union = list(dict.fromkeys((pr_list or []) + (ev_list or [])))
        for raw in union:
            entries.append({
                "id": cid, "number": raw, "kind": classify(raw, answer),
                "sentence": sentence_of(raw, answer),
                "product_unverified": None if pr_list is None else raw in pr_list,
                "eval_unverified": None if ev_list is None else raw in ev_list,
            })
    by_kind = {k: Counter() for k in KINDS}
    for e in entries:
        c = by_kind[e["kind"]]
        c["条目"] += 1
        c["产品口径未核实"] += e["product_unverified"] is True
        c["评测口径未核实"] += e["eval_unverified"] is True
        c["仅评测口径"] += e["eval_unverified"] is True and e["product_unverified"] is False
        c["仅产品口径"] += e["product_unverified"] is True and e["eval_unverified"] is False
    return {"entries": entries, "by_kind": {k: dict(v) for k, v in by_kind.items()},
            "eval_total": eval_total, "no_snapshot": no_snapshot,
            "cases": len(report.get("cases") or [])}


def _cell(v) -> str:
    return "—" if v is None else ("是" if v else "否")


def render_md(m: dict, report_name: str) -> str:
    cols = ("条目", "产品口径未核实", "评测口径未核实", "仅评测口径", "仅产品口径")
    out = [f"# grounding 假阳率量测读数（{report_name}，{m['cases']} 题）", "",
           "| 类别 | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for k in KINDS:
        out.append(f"| {k} | " + " | ".join(str(m["by_kind"][k].get(c, 0)) for c in cols) + " |")
    out += ["", f"- 评测口径条目总数（报告 answer_nums_missing 之和）：{m['eval_total']}",
            f"- 有结论但无快照、产品口径算不出的题：{len(m['no_snapshot'])}"
            + (f"（{', '.join(m['no_snapshot'])}）" if m["no_snapshot"] else ""),
            "- 「仅评测口径」= 问题原文里有这个数、产品口径因此放行的条目。", "",
            "## 待标注清单（逐条）", "",
            "| 题号 | 数字 | 类别 | 产品口径未核实 | 评测口径未核实 | 结论原句 |", "|---|---|---|---|---|---|"]
    for e in m["entries"]:
        sent = e["sentence"].replace("|", "\\|").replace("\n", " ")
        out.append(f"| {e['id']} | {e['number']} | {e['kind']} | {_cell(e['product_unverified'])} "
                   f"| {_cell(e['eval_unverified'])} | {sent} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report")
    ap.add_argument("--snapshots", required=True, help="同一批的快照目录（DATACHAT_SNAPSHOT_DIR）")
    ap.add_argument("--md", help="读数表写到这个文件（默认打印）")
    ap.add_argument("--json", help="逐条结果另存 JSON")
    a = ap.parse_args(argv)
    try:
        report = load_json(a.report)
    except ReportError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    if kind_of(report) != KIND_EVAL:
        print(f"错误：{a.report} 不是逐题评测报告（kind={kind_of(report)}）", file=sys.stderr)
        return 2
    if not os.path.isdir(a.snapshots):
        print(f"错误：快照目录不存在：{a.snapshots}", file=sys.stderr)
        return 2
    m = measure(report, index_snapshots(a.snapshots))
    md = render_md(m, os.path.basename(a.report))
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
