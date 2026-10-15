"""阶段 3.5 闸门：跑 datachat、出待人工判定的报告、按预登记规则出结论。

1) 跑模型（需要 API Key，同 run_eval.py 的 DEEPSEEK_* 环境变量）：
       python scripts/gate/run_gate.py --agent react
   → docs/eval/gate_<日期>_<agent>.json。每题有模型答案、比较器的参考判定（auto_correct / match），
     以及留空的人工字段 human_correct / failure_class / reason / guessing。
2) 人工判定：打开 JSON 逐题填 human_correct（true/false）、判错时 failure_class（1–6，见 questions.py）、
   一句 reason；读代码觉得"它在乱猜"的题把 guessing 设为 true。只问"这个答案我会不会拿去用"。
3) 出结论：python scripts/gate/run_gate.py --verdict docs/eval/gate_<日期>_<agent>.json --profile m13
   加 --profile phase35|m13 → 按 docs/gate/thresholds.json 里该 profile 的门槛写回 verdict 段（含门槛原文与文件哈希）。

比较器只做参考：答案外部（answers.json 由 verify_gate.py 独立算出），判定以人工为准。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ANSWERS = os.path.join(ROOT, "docs", "gate", "answers.json")

THRESHOLDS = os.path.join(ROOT, "docs", "gate", "thresholds.json")


def load_profile(name: str) -> tuple[dict, str]:
    """门槛只从 docs/gate/thresholds.json 读（[25]）：返回 (profile, 文件 sha256 前 12 位)。

    哈希前把 CRLF 规范化成 LF：本仓库 core.autocrlf=true，工作区签出是 CRLF，而 git 对象是 LF。
    不规范化的话同一个文件在本机算出的哈希和报告里记的不一样（同目录的 verify_gate.questions_sha256
    一直是这么做的，这里对齐）。
    """
    import hashlib
    raw = open(THRESHOLDS, "rb").read().replace(b"\r\n", b"\n")
    profiles = json.loads(raw.decode("utf-8"))
    if name not in profiles or name.startswith("_"):
        sys.exit(f"未知门槛 profile：{name}；可选：{[k for k in profiles if not k.startswith('_')]}")
    return profiles[name], hashlib.sha256(raw).hexdigest()[:12]

def to_obj(ans):
    import pandas as pd
    k = ans["kind"]
    if k == "scalar":
        return ans["value"]
    if k == "label":
        return ans["value"]
    if k == "list":
        # 有序（Top-N）→ list，按顺序比；无序（"有哪些"）→ frozenset，按集合比（比较器规则 21，B66）
        return list(ans["value"]) if ans.get("ordered") else frozenset(ans["value"])
    if k == "series":
        # answers.json 里的索引是字符串（JSON 键），季度/月份序号还原成整数，与阶段 3 的写法一致（B66：s11）
        idx = [int(i) if isinstance(i, str) and i.isdigit() else i for i in ans["index"]]
        return pd.Series(ans["values"], index=idx)
    return None


def auto_judge(actual, q, ans):
    from app.eval.runner import score_detail
    case = SimpleNamespace(expect_refusal=bool(q.get("expect_refusal")),
                           ordered=ans["gold"].get("ordered") if ans["gold"]["kind"] == "list" else None,
                           percent_equiv=bool(ans.get("percent_equiv")))
    if case.expect_refusal:
        expected = [None]
    else:
        expected = [to_obj(ans["gold"])] + [to_obj(a) for a in ans["alts"]]
    try:
        return score_detail(actual, case, expected)
    except Exception:
        return None


def run(agent: str, use_dictionary: bool, only: list[str] | None):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from app.core import analyze
    from app.core.llm import LLMConfig
    from app.core.result import format_result
    from app.eval.chart_smoke import chart_row, summarize as chart_summary
    from app.eval.report import git_sha, git_sha_note, run_metadata
    from questions import QUESTIONS

    answers = json.load(open(ANSWERS, encoding="utf-8"))
    cfg = LLMConfig.from_env()
    rows = []
    for q in QUESTIONS:
        if only and q["id"] not in only:
            continue
        ans = answers["answers"][q["id"]]
        t0 = time.perf_counter()
        res = analyze(os.path.join(ROOT, q["dataset"]), q["question"], agent=agent, llm_config=cfg,
                      use_dictionary=use_dictionary)
        match = auto_judge(res.result, q, ans) if res.executed else None
        rows.append({
            "id": q["id"], "group": q["group"], "category": q["category"], "dataset": q["dataset"],
            "question": q["question"], "expect_refusal": bool(q.get("expect_refusal")),
            "gold": ans["gold"], "alts": ans["alts"], "note": ans["note"],
            "executed": res.executed, "error_kind": res.error_kind, "error": res.error,
            "answer": res.answer, "result_text": format_result(res.result, max_chars=1500) if res.executed else None,
            "code": res.code, "attempts": res.attempts, "duration_s": round(time.perf_counter() - t0, 2),
            "tokens": res.usage.total_tokens if res.usage.reported else None,
            "auto_correct": match is not None, "match": match,
            "warnings": res.warnings, "unverified_numbers": res.unverified_numbers,
            "chart": chart_row(res),
            "human_correct": None, "failure_class": None, "reason": "", "guessing": None,
        })
        mark = "✓" if match else ("✗" if res.executed else "!")
        print(f"{mark} {q['id']} {q['question'][:30]}  match={match}  {res.error_kind or ''}")
    out = {
        "time": datetime.now().isoformat(timespec="seconds"), "git_sha": (sha := git_sha()),
        **({"git_sha_note": git_sha_note()} if sha.endswith("?") or sha == "unknown" else {}),   # B67
        "agent": agent,
        "use_dictionary": use_dictionary, **run_metadata(cfg),
        "questions_sha256": answers["questions_sha256"], "sources": answers["sources"],
        "n": len(rows), "execution_success": sum(r["executed"] for r in rows),
        "auto_correct": sum(r["auto_correct"] for r in rows),
        "unverified_numbers": sum(bool(r["unverified_numbers"]) for r in rows),
        "note": "auto_correct 只是比较器参考；结论以人工 human_correct 为准（--verdict）。",
        "chart_smoke": chart_summary(rows, [r["id"] for r in rows]),   # M13 图表两条，与准确率分开报
        "cases": rows,
    }
    path = os.path.join(ROOT, "docs", "eval", f"gate_{datetime.now():%Y%m%d_%H%M%S}_{agent}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n执行成功 {out['execution_success']}/{out['n']}，比较器参考判对 {out['auto_correct']}/{out['n']}")
    cs = out["chart_smoke"]
    print(f"图表：出图率 无图 {cs['出图率']['no_chart']}/{cs['出图率']['drew']} 题画图；"
          f"chart_option {cs['chart_option']['ok']}/{cs['chart_option']['called']}；内部错误 {cs['internal_errors']}")
    print(f"报告：{os.path.relpath(path, ROOT)}  —— 下一步人工填 human_correct / failure_class / reason")
    return path


def verdict(path: str, profile: str) -> dict:
    prof, th_sha = load_profile(profile)
    data = json.load(open(path, encoding="utf-8"))
    rows = data["cases"]
    todo = [r["id"] for r in rows if r.get("human_correct") is None]
    if todo:
        sys.exit(f"还有 {len(todo)} 题没填 human_correct：{todo}")
    bad_class = [r["id"] for r in rows if not r["human_correct"] and r.get("failure_class") not in range(1, 7)]
    if bad_class:
        sys.exit(f"判错的题必须填 failure_class（1–6）：{bad_class}")

    def group(g):
        rs = [r for r in rows if r["group"] == g]
        return sum(bool(r["human_correct"]) for r in rs), len(rs)

    s_ok, s_n = group("single")
    m_ok, m_n = group("multi")
    fails = [r["failure_class"] for r in rows if not r["human_correct"]]
    dist = Counter(fails)
    out = {"single": f"{s_ok}/{s_n}", "multi": f"{m_ok}/{m_n}", "failures": len(fails),
           "failure_distribution": {str(k): v for k, v in sorted(dist.items())},
           "execution_success": f"{sum(r['executed'] for r in rows)}/{len(rows)}",
           "guessing": f"{sum(bool(r.get('guessing')) for r in rows)}/{len(rows)}"}
    out.update({"profile": profile, "thresholds": prof, "thresholds_sha256": th_sha,
                "labeled_by": data.get("labeled_by", "")})
    # 显式写 True/False（[30]）：只写 False 的写法让"已终审"没法用这个字段表达，
    # 结果就是 labeled_by 改成"S 终审通过"之后 keys 里仍留着上一轮的 False。
    # labeled_by 为空时不写这个键：没人署名的标注不能被判成"已终审"（10-12 的老报告没有 labeled_by）。
    if out["labeled_by"]:
        out["labels_final"] = "待 S 终审" not in out["labeled_by"]
    else:
        out.pop("labels_final", None)
    if prof["kind"] == "phase35":
        out.update(_verdict_phase35(prof, s_ok, s_n, m_ok, m_n, fails, dist))
    else:
        out.update(_verdict_regression(prof, data.get("agent"), rows))
    if any(r.get("chart") for r in rows):             # [27] 起的报告才有；与准确率判定分开，不影响 regression_verdict
        from app.eval.chart_smoke import summarize as chart_summary
        out["chart_smoke"] = chart_summary(rows, [r["id"] for r in rows])
    data["verdict"] = out
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def _verdict_phase35(p, s_ok, s_n, m_ok, m_n, fails, dist) -> dict:
    out = {}
    if s_n == 15:
        out["single_verdict"] = ("可用，继续阶段 4" if s_ok >= p["single_pass"] else
                                 "路线重估（模型自由写 Python 在真实数据上是否成立）" if s_ok < p["single_rethink"] else
                                 "暂停阶段 4，先修真实数据适配（编码/列名/宽表/契约）")
    if m_n == 10:
        out["multi_verdict"] = ("有救，阶段 7 的 DuckDB 值得做" if m_ok >= p["multi_pass"]
                                else "多表 <40%：后果未预登记，交 S 判断")
    if len(fails) < p["dist_min_failures"]:
        out["distribution_verdict"] = f"失败 {len(fails)} 题 < {p['dist_min_failures']}，只记录分布，不触发分布规则"
    else:
        top_cls, top_n = dist.most_common(1)[0]
        if top_n / len(fails) >= p["dist_dominant"]:
            out["distribution_verdict"] = f"集中：第 {top_cls} 类占 {top_n}/{len(fails)}，列为阶段 4–7 的 P0，方向不变"
        elif len(dist) >= p["dist_scatter_classes"]:
            out["distribution_verdict"] = f"散落 {len(dist)} 类：系统性问题，分数再高也要重估路线"
        else:
            top2 = [str(k) for k, _ in dist.most_common(2)]
            out["distribution_verdict"] = f"中间区间（{len(dist)} 类，最大类 <60%）：第 {'、'.join(top2)} 类都列为 P0，方向不变"
    return out


def _verdict_regression(p, agent, rows) -> dict:
    """回归门槛（[25]）：错题必须全部落在 allowed_fail 里。"""
    if agent not in p["agents"]:
        sys.exit(f"报告的 agent={agent!r} 在 profile 里没有门槛")
    out, ok_all = {}, True
    for g, rule in p["agents"][agent].items():
        rs = [r for r in rows if r["group"] == g]
        allowed = set(rule["allowed_fail"])
        failed = {r["id"] for r in rs if not r["human_correct"]}
        regress = sorted(failed - allowed)
        out[f"{g}_min"] = f"{len(rs) - len(allowed)}/{len(rs)}"
        out[f"{g}_regressions"] = regress
        out[f"{g}_unexpected_pass"] = sorted(allowed - failed)
        ok_all &= not regress
    out["regression_verdict"] = "无回归" if ok_all else "有回归：先看是否与本次改动有关，再下结论"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="阶段 3.5 外部验证闸门")
    ap.add_argument("--agent", choices=["workflow", "react"], default="react")
    ap.add_argument("--no-dict", action="store_true", help="闸门数据没有字典，此开关只为对齐 run_eval 的用法")
    ap.add_argument("--only", nargs="*", help="只跑这些题号（调试用；正式结论必须全跑）")
    ap.add_argument("--verdict", metavar="REPORT", help="对已人工判定的报告出结论（必须同时给 --profile）")
    ap.add_argument("--profile", help="docs/gate/thresholds.json 里的门槛：phase35（阶段 3.5 原判）/ m13（阶段 5 回归）")
    a = ap.parse_args()
    if a.verdict:
        if not a.profile:
            sys.exit("--verdict 必须指定 --profile（见 docs/gate/thresholds.json），不再有默认门槛")
        verdict(a.verdict, a.profile)
    else:
        run(a.agent, not a.no_dict, a.only)
