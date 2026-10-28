"""阶段 3.5 闸门：跑 datachat、出待人工判定的报告、按预登记规则出结论。

1) 跑模型（需要 API Key，同 run_eval.py 的 DEEPSEEK_* 环境变量）：
       python scripts/gate/run_gate.py --agent react
   → docs/eval/gate_<日期>_<agent>.json。每题有模型答案、比较器的参考判定（auto_correct / match），
     以及留空的人工字段 human_correct / failure_class / reason / guessing。
2) 人工判定：打开 JSON 逐题填 human_correct（true/false）、判错时 failure_class（1–6，见 questions.py）、
   一句 reason；读代码觉得"它在乱猜"的题把 guessing 设为 true。只问"这个答案我会不会拿去用"。
3) 出结论：python scripts/gate/run_gate.py --verdict docs/eval/gate_<日期>_<agent>.json --profile m13
   加 --profile phase35|m13 → 按 docs/gate/thresholds.json 里该 profile 的门槛写回 verdict 段（含门槛原文与文件哈希）。

4) 错题复跑（A1，只对 profile m13r）：
       python scripts/gate/run_gate.py --rerun docs/eval/gate_<日期>_<agent>.json --profile m13r [--agent workflow]
   主报告人工判完后，名单外错题各复跑 3 次（无效的补 1 次，最多 4 次），结果追加到同一份报告的 reruns，
   直接写回 verdict（此时一般全在 pending_review）。人工在 reruns 行签 human_correct 后再跑 --verdict 结案。
   --only <题号> --reason <理由>：补进比较器漏判的题，或替换某题已有的复跑（旧行进 rerun_history）。

退出码：0 通过 / 1 有回归 / 2 无法判定（待复跑、待签字、有效次数不足）/ 3 前提不满足。
注意 m13 / phase35 的成功路径有意不改：有回归也是 0，只表示"跑完了"，结论看 regression_verdict。

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

# A1：复跑观测是否可用来判这题答得对（显式白名单，tests 断言与 ERROR_KINDS 完整覆盖且互不相交）
RERUN_VALID_KINDS = (None, "execution", "agent")
RERUN_INVALID_KINDS = ("llm", "cancelled", "interrupted", "dataset")
# 复跑前与主报告逐项比对的环境（git_sha 单独处理：带 ? 时按 --require-sha 决定）
RERUN_ENV_KEYS = ("agent", "use_dictionary", "model", "temperature", "base_url_host", "python", "pandas")

EXIT_PASS, EXIT_REGRESSION, EXIT_UNDECIDED, EXIT_PRECONDITION = 0, 1, 2, 3


def _fail(msg: str):
    """前提不满足：打印到 stderr，退出码 3（A1；原来 sys.exit(str) 是 1，会和"1 = 有回归"撞上）。"""
    print(msg, file=sys.stderr)
    sys.exit(EXIT_PRECONDITION)


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
        _fail(f"未知门槛 profile：{name}；可选：{[k for k in profiles if not k.startswith('_')]}")
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


def _analyze():
    """单独一层，测试打桩用。"""
    from app.core import analyze
    return analyze


def _case_row(q: dict, ans: dict, res, duration: float) -> dict:
    """主报告和复跑共用的一行（复跑行与 cases 行同构，A1）。"""
    from app.core.result import format_result
    from app.eval.chart_smoke import chart_row
    match = auto_judge(res.result, q, ans) if res.executed else None
    return {
        "id": q["id"], "group": q["group"], "category": q["category"], "dataset": q["dataset"],
        "question": q["question"], "expect_refusal": bool(q.get("expect_refusal")),
        "gold": ans["gold"], "alts": ans["alts"], "note": ans["note"],
        "executed": res.executed, "error_kind": res.error_kind, "error": res.error,
        "answer": res.answer, "result_text": format_result(res.result, max_chars=1500) if res.executed else None,
        "code": res.code, "attempts": res.attempts, "duration_s": round(duration, 2),
        "tokens": res.usage.total_tokens if res.usage.reported else None,
        "auto_correct": match is not None, "match": match,
        "warnings": res.warnings, "unverified_numbers": res.unverified_numbers,
        "chart": chart_row(res),
        "human_correct": None, "failure_class": None, "reason": "", "guessing": None,
    }


def _run_digest(row: dict) -> dict:
    """repeat 的逐次摘要（EV-A2）。刻意不复制 result_text / code：25 题 × 5 次会把 JSON
    撑到几十 MB，而判断"这一次为什么翻了"只需要 match、错误类型和答案开头。"""
    d = {k: row.get(k) for k in ("executed", "match", "auto_correct", "error_kind",
                                 "attempts", "duration_s", "tokens")}
    d["answer"] = (row.get("answer") or "")[:300]
    return d


def run(agent: str, use_dictionary: bool, only: list[str] | None, repeat: int = 1):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from app.core.llm import LLMConfig
    from app.eval.chart_smoke import summarize as chart_summary
    from app.eval.report import git_sha, git_sha_note, run_metadata
    from questions import QUESTIONS

    answers = json.load(open(ANSWERS, encoding="utf-8"))
    cfg = LLMConfig.from_env()
    repeat = max(1, int(repeat or 1))
    rows = []
    for q in QUESTIONS:
        if only and q["id"] not in only:
            continue
        ans = answers["answers"][q["id"]]
        runs = []
        for k in range(repeat):
            t0 = time.perf_counter()
            res = _analyze()(os.path.join(ROOT, q["dataset"]), q["question"], agent=agent, llm_config=cfg,
                             use_dictionary=use_dictionary)
            runs.append(_case_row(q, ans, res, time.perf_counter() - t0))
            if repeat > 1:
                print(f"  {q['id']} run{k + 1}/{repeat} match={runs[-1]['match']}")
        row = dict(runs[0])          # 主行恒为第 1 次：人工签字与历史报告都对着这一行
        if repeat > 1:
            row["runs"] = [_run_digest(r) for r in runs]
        rows.append(row)
        match = row["match"]
        mark = "✓" if match else ("✗" if row["executed"] else "!")
        print(f"{mark} {q['id']} {q['question'][:30]}  match={match}  {row['error_kind'] or ''}")
    out = {
        "time": datetime.now().isoformat(timespec="seconds"), "git_sha": (sha := git_sha()),
        **({"git_sha_note": git_sha_note()} if sha.endswith("?") or sha == "unknown" else {}),   # B67
        "agent": agent,
        "use_dictionary": use_dictionary, "repeat": repeat, **run_metadata(cfg),
        "questions_sha256": answers["questions_sha256"], "sources": answers["sources"],
        "n": len(rows), "execution_success": sum(r["executed"] for r in rows),
        "auto_correct": sum(r["auto_correct"] for r in rows),
        "unverified_numbers": sum(bool(r["unverified_numbers"]) for r in rows),
        "note": "auto_correct 只是比较器参考；结论以人工 human_correct 为准（--verdict）。"
                + ("repeat>1 时主行是第 1 次，逐次结果见每行 runs。" if repeat > 1 else ""),
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


def _check_labels(rows: list[dict]):
    todo = [r["id"] for r in rows if r.get("human_correct") is None]
    if todo:
        _fail(f"还有 {len(todo)} 题没填 human_correct：{todo}")
    bad_class = [r["id"] for r in rows if not r["human_correct"] and r.get("failure_class") not in range(1, 7)]
    if bad_class:
        _fail(f"判错的题必须填 failure_class（1–6）：{bad_class}")


def _save(path: str, data: dict):
    """写临时文件再原子替换：复跑中途被打断时，报告里只会是完整的若干行（A1）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def verdict(path: str, profile: str) -> dict:
    prof, th_sha = load_profile(profile)
    data = json.load(open(path, encoding="utf-8"))
    rows = data["cases"]
    _check_labels(rows)

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
        if "rerun" in prof:
            out.update(_verdict_rerun(prof, data, path, profile))
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
        _fail(f"报告的 agent={agent!r} 在 profile 里没有门槛")
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


# ------------------------------------------------------------------ A1 错题复跑
def rerun_candidates(prof: dict, agent: str, rows: list[dict]) -> list[str]:
    """名单外的错题（按人工判定）：allowed_fail 里的错题、意外答对的题都不在内。"""
    if agent not in prof["agents"]:
        _fail(f"报告的 agent={agent!r} 在 profile 里没有门槛")
    out = []
    for g, rule in prof["agents"][agent].items():
        allowed = set(rule["allowed_fail"])
        out += [r["id"] for r in rows if r["group"] == g and not r["human_correct"] and r["id"] not in allowed]
    return out


def rerun_valid(row: dict) -> bool:
    """有效观测：error_kind 在白名单里，且不是"跑了但比较器判不了"（executed=True、match=None）。
    executed=False 的行有效，记为答错（和主报告 auto_correct = match is not None 同口径）。"""
    if row.get("error_kind") not in RERUN_VALID_KINDS:
        return False
    return not (row.get("executed") and row.get("match") is None)


def _row_correct(row: dict) -> bool:
    """人工字段优先；没签时用比较器参考（executed=False → 答错）。只用于 observed_pass_rate 和排序。"""
    if row.get("human_correct") is not None:
        return bool(row["human_correct"])
    return bool(row.get("executed")) and row.get("match") is True


def _current_env(agent: str, use_dictionary: bool) -> tuple:
    """复跑时的环境（测试打桩用）：返回 (LLMConfig, 与主报告同名的元数据)。"""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from app.core.llm import LLMConfig
    from app.eval.report import git_sha, run_metadata
    cfg = LLMConfig.from_env()
    return cfg, {"git_sha": git_sha(), "agent": agent, "use_dictionary": use_dictionary, **run_metadata(cfg)}


def _check_rerun_env(data: dict, env: dict, require_sha: bool) -> bool:
    """逐项比对主报告与本次环境，不一致就拒绝。返回 sha_verified。"""
    diff = [f"{k}: 报告 {data.get(k)!r} ≠ 现在 {env.get(k)!r}" for k in RERUN_ENV_KEYS if data.get(k) != env.get(k)]
    rep_sha, cur_sha = str(data.get("git_sha") or "unknown"), str(env.get("git_sha") or "unknown")
    if rep_sha.rstrip("?") != cur_sha.rstrip("?") or "unknown" in (rep_sha, cur_sha):
        diff.insert(0, f"git_sha: 报告 {rep_sha!r} ≠ 现在 {cur_sha!r}")
    if diff:
        _fail("复跑前提不一致，拒绝复跑：\n  " + "\n  ".join(diff))
    verified = not (rep_sha.endswith("?") or cur_sha.endswith("?"))
    if not verified:
        if require_sha:
            _fail(f"git_sha 带 ?（工作区有未提交改动）：报告 {rep_sha!r}，现在 {cur_sha!r}；--require-sha 下拒绝复跑")
        print(f"警告：git_sha 带 ?（报告 {rep_sha!r}，现在 {cur_sha!r}），复跑结果记 sha_verified: false",
              file=sys.stderr)
    return verified


def rerun(path: str, profile: str, agent: str, use_dictionary: bool, only: list[str] | None = None,
          reason: str | None = None, require_sha: bool = False) -> dict:
    """A1：名单外错题逐题复跑，追加写进同一份报告的 reruns，最后直接写回 verdict。"""
    prof, _ = load_profile(profile)
    if "rerun" not in prof:
        _fail(f"profile {profile!r} 不支持复跑（只有带 rerun 段的 profile 可以，例如 m13r）")
    if only and not (reason or "").strip():
        _fail("--only 必须带 --reason：声明过的重跑才允许，理由写进 rerun_history")
    data = json.load(open(path, encoding="utf-8"))
    rows = data["cases"]
    _check_labels(rows)
    cfg, env = _current_env(agent, use_dictionary)
    sha_verified = _check_rerun_env(data, env, require_sha)

    ids_all = {r["id"] for r in rows}
    unknown = [i for i in (only or []) if i not in ids_all]
    if unknown:
        _fail(f"--only 里的题号不在报告里：{unknown}")
    reruns = data.setdefault("reruns", [])
    done = {r["id"] for r in reruns}
    cand = rerun_candidates(prof, data.get("agent"), rows)
    if only:
        selected = [i for i in cand if i not in done] + [i for i in only if i not in cand or i in done]
    else:
        again = [i for i in cand if i in done]
        if again:
            _fail(f"这些题已经复跑过：{again}。不声明的重复抽样不允许；要重跑请用 --only <题号> --reason <理由>")
        selected = cand
    selected = list(dict.fromkeys(selected))

    from app.eval.report import git_sha_note
    from questions import QUESTIONS
    qs = {q["id"]: q for q in QUESTIONS}
    answers = json.load(open(ANSWERS, encoding="utf-8"))["answers"]
    data["rerun_meta"] = {"time": datetime.now().isoformat(timespec="seconds"), "profile": profile,
                          "git_sha": env["git_sha"], "sha_verified": sha_verified,
                          **({"git_sha_note": git_sha_note()} if not sha_verified else {})}
    times, makeup = prof["rerun"]["times"], prof["rerun"]["max_makeup"]
    for qid in selected:
        old = [r for r in reruns if r["id"] == qid]
        if old:
            data.setdefault("rerun_history", []).append({
                "time": datetime.now().isoformat(timespec="seconds"), "git_sha": env["git_sha"], "id": qid,
                "replaced_attempts": old, "reason": reason})
            reruns[:] = [r for r in reruns if r["id"] != qid]
        _save(path, data)
        q, ans = qs[qid], answers[qid]
        n_valid = n_total = 0
        while n_valid < times and n_total < times + makeup:
            t0 = time.perf_counter()
            res = _analyze()(os.path.join(ROOT, q["dataset"]), q["question"], agent=agent, llm_config=cfg,
                             use_dictionary=use_dictionary)
            n_total += 1
            row = {**_case_row(q, ans, res, time.perf_counter() - t0), "attempt": n_total}
            row["valid"] = rerun_valid(row)
            n_valid += row["valid"]
            reruns.append(row)
            _save(path, data)                       # 每行落盘一次
            print(f"  {qid} #{n_total} valid={row['valid']} match={row['match']} {row['error_kind'] or ''}")
    return verdict(path, profile)


def _verdict_rerun(prof: dict, data: dict, path: str, profile: str) -> dict:
    """m13r：名单外错题按复跑 + 人工签字结案。比较器在两个方向上都没有定论权（S 第三轮 二）。"""
    rows = data["cases"]
    agent = data.get("agent")
    times = prof["rerun"]["times"]
    reruns = data.get("reruns") or []
    main = {r["id"]: r for r in rows}
    cand = set(rerun_candidates(prof, agent, rows))
    tracked = cand | {r["id"] for r in reruns}
    out = {"rerun_rule": (f"名单外错题复跑 {times} 次（无效的补跑，最多 {times + prof['rerun']['max_makeup']} 次），"
                          f"有效复跑人工全签 true 记波动，有一次 false 记回归"),
           "rerun_false_negative": {f"p={p}": f"{p ** times:.1%}" for p in (0.5, 0.7)},
           "rerun_false_negative_note": f"真实单次答对率为 p 的回归题，{times} 次全对被误记为波动的概率 p^{times}"}
    if not reruns:
        for g in prof["agents"][agent]:
            out[f"{g}_regressions"] = []
            out[f"{g}_rerun_candidates"] = sorted(i for i in cand if main[i]["group"] == g)
        if cand:
            try:
                rel = os.path.relpath(path, ROOT)
            except ValueError:                          # Windows 跨盘
                rel = path
            out["regression_verdict"] = (f"待复跑：python scripts/gate/run_gate.py --rerun {rel} --profile {profile}"
                                         f"{'' if agent == 'react' else ' --agent ' + str(agent)}")
            out["exit_code"] = EXIT_UNDECIDED
        else:
            out["regression_verdict"] = "无回归（没有名单外错题，不需要复跑）"
            out["exit_code"] = EXIT_PASS
        return out

    bad_class = [f"{r['id']}#{r.get('attempt')}" for r in reruns
                 if r.get("valid") and r.get("human_correct") is False and r.get("failure_class") not in range(1, 7)]
    if bad_class:
        _fail(f"复跑行判错必须填 failure_class（1–6）：{bad_class}")

    n_regress = n_open = n_flaky = 0
    for g in prof["agents"][agent]:
        regress, flaky, pending, invalid, not_run = [], [], [], [], []
        for qid in sorted(i for i in tracked if main[i]["group"] == g):
            rs = [r for r in reruns if r["id"] == qid]
            valid = [r for r in rs if r.get("valid")]
            m = main[qid]
            obs = [m] + valid
            rate = f"{sum(_row_correct(r) for r in obs)}/{len(obs)}"
            if not rs:
                not_run.append(qid)
            elif len(valid) < times:
                invalid.append({"id": qid, "valid": len(valid), "total": len(rs), "observed_pass_rate": rate})
            elif any(r.get("human_correct") is None for r in valid):
                prio = any(r.get("match") is not True or not r.get("executed") for r in valid)
                pending.append({"id": qid, "priority": prio, "observed_pass_rate": rate,
                                "unsigned": [r["attempt"] for r in valid if r.get("human_correct") is None]})
            elif all(r["human_correct"] for r in valid):
                flaky.append({"id": qid, "observed_pass_rate": rate,
                              "flaky_cause": "env" if m.get("error_kind") in RERUN_INVALID_KINDS else "model"})
            else:
                regress.append(qid)
        pending.sort(key=lambda x: (not x["priority"], x["id"]))
        out[f"{g}_rerun_candidates"] = sorted(i for i in cand if main[i]["group"] == g)
        out[f"{g}_regressions"] = regress
        out[f"{g}_flaky"] = flaky
        out[f"{g}_pending_review"] = pending
        out[f"{g}_rerun_invalid"] = invalid
        if not_run:
            out[f"{g}_not_rerun"] = not_run
        n_regress += len(regress)
        n_flaky += len(flaky)
        n_open += len(pending) + len(invalid) + len(not_run)
    if n_regress:
        out["regression_verdict"] = "有回归：复跑后人工确认，先看是否与本次改动有关"
        out["exit_code"] = EXIT_REGRESSION
    elif n_open:
        out["regression_verdict"] = "无法判定：有题待签字、待复跑或有效复跑次数不足（见 *_pending_review / *_rerun_invalid）"
        out["exit_code"] = EXIT_UNDECIDED
    else:
        out["regression_verdict"] = f"已复跑的 {n_flaky} 题里没有回归（全部为波动，见 *_flaky）"
        out["exit_code"] = EXIT_PASS
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="阶段 3.5 外部验证闸门")
    ap.add_argument("--agent", choices=["workflow", "react"], default="react")
    ap.add_argument("--no-dict", action="store_true", help="闸门数据没有字典，此开关只为对齐 run_eval 的用法")
    ap.add_argument("--only", nargs="*", help="只跑这些题号（调试用；正式结论必须全跑）")
    ap.add_argument("--verdict", metavar="REPORT", help="对已人工判定的报告出结论（必须同时给 --profile）")
    ap.add_argument("--rerun", metavar="REPORT", help="A1：名单外错题复跑并写回 verdict（必须同时给 --profile，如 m13r）")
    ap.add_argument("--reason", help="与 --rerun --only 一起用：本次声明重跑的理由，写进 rerun_history")
    ap.add_argument("--require-sha", action="store_true", help="--rerun 时 git_sha 带 ? 就拒绝")
    ap.add_argument("--profile", help="docs/gate/thresholds.json 里的门槛：phase35（阶段 3.5 原判）/ m13（阶段 5 回归）"
                                      " / m13r（m13 + 错题复跑）")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="每题跑 N 次，逐次结果写进 runs；主行恒为第 1 次（人工签字对着它）")
    a = ap.parse_args()
    if a.verdict or a.rerun:
        if not a.profile:
            _fail("--verdict / --rerun 必须指定 --profile（见 docs/gate/thresholds.json），不再有默认门槛")
        if a.rerun:
            v = rerun(a.rerun, a.profile, a.agent, not a.no_dict, a.only, a.reason, a.require_sha)
        else:
            v = verdict(a.verdict, a.profile)
        sys.exit(v.get("exit_code", EXIT_PASS))     # m13 / phase35 没有 exit_code：有意保持 0
    else:
        run(a.agent, not a.no_dict, a.only, a.repeat)
