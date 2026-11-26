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

产品口径算不出的题分两列，不静默丢掉：ReAct（没有节点行，本来就不适用）和
工作流缺快照（数据缺失，正常应为 0，可当作快照带出是否完整的检查）。

## 四类（判定顺序即优先级）

1. 百分比：数字带 % / ％，或后面紧跟「个百分点 / 百分点」。
2. 派生数：数字前 8 个字内（截到最近的逗号/句号/分号之后，不跨子句）出现差、和、比、均值一类的词（增长、下降、相差、合计、平均、占比、
   环比、同比……），或后面紧跟「倍」。这类数本来就不在证据里，是假阳的主要来源。
3. 带单位的计数/金额：数字前有货币符号（¥ ￥ $），或带 万/亿，或后面 3 个字内紧跟量词/货币单位
   （元、单、件、个、人、次、笔……；去掉空白后紧跟）。S 的门槛（假阳率 <5% 才考虑拦）只看这一类。
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
from app.core.grounding import _NUM_RE, _significant, _tokens, unverified_numbers  # noqa: E402
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
_CLAUSE_BREAK = "，,。；;：:！!？?\n"


# ------------------------------------------------------------------ 分类
def _find(raw: str, answer: str) -> int:
    """raw 在结论里第一次出现的位置（与 grounding 的去重保序一致：只看首次）。

    用 grounding 同一个 _NUM_RE 切数字，按整段数字比对，不会命中更长数字的一部分
    （「1,500 单；评分 500 分」里的 500 落在后一处）。"""
    for m in _NUM_RE.finditer(answer or ""):
        if m.group(0).strip() == raw:
            return m.start()
    i = (answer or "").find(raw)
    return i if i >= 0 else 0


def classify(raw: str, answer: str) -> str:
    """一个未核实数字（grounding 给的原文写法）属于四类中的哪一类。

    先去掉 markdown 的 * 和 `：结论常写成「**2,350** 件」，不去掉的话量词前隔着 **，判不成计数。"""
    answer = re.sub(r"[*`]", "", answer or "")
    i = _find(raw, answer)
    before = answer[max(0, i - 8):i]
    cut = max(before.rfind(c) for c in _CLAUSE_BREAK)
    if cut >= 0:
        before = before[cut + 1:]                # 派生词只在本子句里找
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
    """产品口径的未核实列表；不适用（未执行、拒答）返回 []，无快照返回 None。先判适用再判快照。"""
    answer = case.get("answer") or ""
    if not (answer and case.get("executed")) or refusal_from_answer(answer) is not None:
        return []
    if s is None:
        return None
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
def _agent_of(case: dict, report: dict) -> str:
    a = case.get("agent") or report.get("agent") or "workflow"
    return a if isinstance(a, str) else "mixed"


def measure(report: dict, snapshots: dict) -> dict:
    entries, react, missing = [], [], []
    eval_total = product_total = 0
    base = Counter()          # 分母：产品口径适用题的结论里，grounding 会检查的数字（去重）按类计数
    applicable = 0
    for case in report.get("cases") or []:
        cid = str(case.get("id") or "")
        answer = case.get("answer") or ""
        ev_list = eval_scope(case)
        pr_list = product_scope(case, snapshots.get(cid))
        if pr_list is None:
            (react if _agent_of(case, report) == "react" else missing).append(cid)
        a = case.get("answer") or ""
        if a and case.get("executed") and refusal_from_answer(a) is None:
            applicable += 1
            seen = set()
            for raw, v, dec, unit, after in _tokens(a):
                if _significant(v, dec, unit, after) and raw not in seen:
                    seen.add(raw)
                    base[classify(raw, a)] += 1
        eval_total += len(ev_list or [])
        product_total += len(pr_list or [])
        union = list(dict.fromkeys((pr_list or []) + (ev_list or [])))
        for raw in union:
            entries.append({
                "id": cid, "number": raw, "kind": classify(raw, answer),
                "sentence": sentence_of(raw, answer),
                "product_unverified": None if pr_list is None else raw in pr_list,
                "eval_unverified": None if ev_list is None else raw in ev_list,
            })
    by_kind = {k: Counter({"结论数字": base[k]}) for k in KINDS}
    for e in entries:
        c = by_kind[e["kind"]]
        c["条目"] += 1
        c["产品口径未核实"] += e["product_unverified"] is True
        c["评测口径未核实"] += e["eval_unverified"] is True
        c["仅评测口径"] += e["eval_unverified"] is True and e["product_unverified"] is False
        c["仅产品口径"] += e["product_unverified"] is True and e["eval_unverified"] is False
    return {"entries": entries, "by_kind": {k: dict(v) for k, v in by_kind.items()},
            "eval_total": eval_total, "product_total": product_total, "union_total": len(entries),
            "react": react, "missing_snapshot": missing, "applicable": applicable,
            "cases": len(report.get("cases") or [])}


def _cell(v) -> str:
    return "—" if v is None else ("是" if v else "否")


def render_md(m: dict, report_name: str) -> str:
    cols = ("结论数字", "条目", "产品口径未核实", "评测口径未核实", "仅评测口径", "仅产品口径")
    out = [f"# grounding 假阳率量测读数（{report_name}，{m['cases']} 题）", "",
           "| 类别 | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for k in KINDS:
        out.append(f"| {k} | " + " | ".join(str(m["by_kind"][k].get(c, 0)) for c in cols) + " |")
    def _ids(xs):
        return f"{len(xs)}" + (f"（{', '.join(xs)}）" if xs else "")
    out += ["", f"- 条目守恒：并集 {m['union_total']} 条（逐条列在下表）；"
            f"评测口径 {m['eval_total']} 条（报告 answer_nums_missing 之和）；产品口径 {m['product_total']} 条。",
            f"- 「结论数字」= 产品口径适用的 {m['applicable']} 题（已执行、非拒答）里，grounding 会检查的数字（每题去重）按类计数，"
            "是「未核实条目 / 结论数字」的分母；未核实不等于假阳，真假由人工标注。",
            f"- 产品口径算不出的题：ReAct（不适用）{_ids(m['react'])}；工作流缺快照（数据缺失）{_ids(m['missing_snapshot'])}。",
            "- 「仅评测口径」= 产品证据里有（问题、原问题或 metrics_block）、评测证据里没有的条目；"
            "「仅产品口径」= 评测证据（含 str(result)）里有、产品证据里没有的条目。", "",
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
