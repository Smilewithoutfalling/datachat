"""nightly 回归门禁：把一次 workflow+state 全量跑批与基线（v8 起，DEFAULT_BASELINE 指向 baseline_v8.json；旧基线文件仍可直接 --baseline 传入）比。

## 它回答什么

「master 上的代码改动，有没有把已经答对的题弄错」。**判红只看一条**（2026-11-20 B5 起）：

1. **配对净退步**：同题 before/after。三跑全对的题（`pass3_ids`）里变错的记
   **退步**，三跑全错的题（`failed_ids`）里变对的记**进步**；噪声带
   （`unstable_ids`，1/3~2/3）两边都不算；**净退步 ≥6 题才判红**。
   同题配对把单跑抖动抵掉大半：退步/进步都只在高置信池里数，
   数出来的净差才是真信号。

**规则 1 降级为只列不拦**（2026-11-20 B5）：通过数比基线低 6 题及以上照样
逐条列进简报，但**不影响退出码**。降级依据：门禁分辨率 = 噪声宽度（n=202、
p≈0.95 时 95% 区间 ±3.0pp ≈ ±6 题）—— 总数差是含噪最重的统计量，原来的判红线
就画在噪声带里（N7 实测：同一 master 连续两跑 193（翻 2）/195（翻 0），结论相反，
且判红那跑通过数还**高于**基线；根因是网关 temp 0 并不确定，canary 基线
`answer_varied=10`）。要看总数，简报里列着；要判红，只看配对。详见 BACKLOG N7。

**规则 2 只提示，不拦**（2026-11-18 定）：v7 里三跑全对的题本次变错时，
照样逐题列进简报（id/分类/题面/gold/本次答案），但**不影响退出码**。
另：三跑全错的题本次答对算「进步」，同样只列 —— 配对判读的两条腿都在简报里。
`pass^3` 只是三次抽样，证不了「这题永远对」，188 道三跑全对里每跑翻 1–2
道属于正常抖动。

## 它不回答什么

- 不判"有没有变强"：没有基线能证明 +2 题是改善而不是抖动。
- 不判模型漂移：那是 canary 的活（同题多跑、管权重与 judge）。
- 不修任何东西：红了只写简报，修由改产品的一侧做。

## 三条"不可比"（退出码 2，不是漂移）

- `agent` / `memory_mode` 与基线不同：换了被测对象，读数不是同一件事。
- `n` 与基线不同：没跑完，或题集被改过。
- `evalset_sha12` / `judge_sha12` 与基线不同：**尺子动过，先断代**。
  题库、gold、判分的改动一律先进 BACKLOG「下一轮」，攒够了一次性断代；
  断代 = 新基线 + 文档说明，不是把这次读数当回归。

另有一条：报告里出现 `infra_error` 的题（网关熔断/超时）时也退 2 —— 那不是能力读数，
重跑一次。把它算成"变错"会让 nightly 在网关打嗝时误报代码退化。

## 退出码

| 码 | 含义 | 动作 |
|---|---|---|
| 0 | 绿（配对净退步没过阈） | 不用管；总数差/翻转/进步都在简报里备查 |
| 1 | 红（高置信池同题配对，净退步 ≥6 题） | 看简报：哪些题翻了、这段区间有哪些提交 |
| 2 | 不可比 / 跑不完整 | 先修流水线；尺子变了就断代 |
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

DEFAULT_BASELINE = os.path.join("docs", "eval", "baseline_v8.json")
DEFAULT_REPORT = os.path.join("outputs", "nightly_v7.json")

# 判红阈值。**写死在代码里，不从环境变量读** —— 能随手改的门槛等于没有门槛。
# 改这个数 = 改判定口径，要同时改 baseline 的 `rules` 与 docs/eval/README.md。
# `MAX_PAIRED_NET_DROP` 是 B5 起的**唯一判红条件**：高置信池（pass3/failed）同题
# 配对，退步 − 进步 ≥6 才红。配对把噪声带宽从 ±6 题压到 1–2 题，6 保守但语义
# 干净：净退 6 = 真把一批稳定对的题做坏了，进步抵不完。
# `MAX_DROP` / `MAX_PASS3_FLIPS` 降级为只列不拦（2026-11-20 B5 / 2026-11-18 N7），
# 只进简报不进退出码。
MAX_DROP = 6
MAX_PASS3_FLIPS = 2
MAX_PAIRED_NET_DROP = 6


def _case_map(report: dict) -> dict[str, dict]:
    return {c["id"]: c for c in (report.get("cases") or [])}


def _clip(text, n: int) -> str:
    s = " ".join(str(text if text is not None else "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _delta(drop: int) -> str:
    """`drop` = 基线 − 本次。正数=退步，负数=进步，0=持平。"""
    if drop > 0:
        return f"低 {drop}"
    if drop < 0:
        return f"高 {-drop}"
    return "持平"


def evaluate(report: dict, baseline: dict) -> dict:
    """纯函数：两份 JSON 进，判定出。不读文件、不抛异常（缺字段归到 config）。"""
    fp = report.get("fingerprints") or {}
    base_fp = baseline.get("fingerprints") or {}
    reasons: list[str] = []

    # ---- 可比性：被测对象、题数、尺子 -------------------------------------
    if report.get("agent") != baseline.get("agent"):
        reasons.append(f"agent 不同：基线 `{baseline.get('agent')}`，本次 `{report.get('agent')}`")
    if report.get("memory_mode") != baseline.get("memory_mode"):
        reasons.append(f"memory_mode 不同：基线 `{baseline.get('memory_mode')}`，"
                       f"本次 `{report.get('memory_mode')}`")
    # 模型也是"被测对象"的一部分：基线的三跑是在其记录的模型上量的，
    # 换模型（哪怕名字只差一个快照）读出来的差不能算到代码头上。
    if report.get("model") != baseline.get("model"):
        reasons.append(f"模型不同：基线 `{baseline.get('model')}`，本次 `{report.get('model')}`"
                       " —— 读数不可比；nightly 必须跑基线用的那个模型")
    cases = _case_map(report)
    n = len(cases)
    if n != baseline.get("n"):
        reasons.append(f"题数 {n} ≠ 基线 {baseline.get('n')}：没跑完，或题集改过")
    for key, label in (("evalset_sha12", "题库"), ("judge_sha12", "判分口径")):
        b, c = base_fp.get(key), fp.get(key)
        if not b:
            reasons.append(f"基线缺 `{key}` 字段 —— 重立基线")
        elif b != c:
            reasons.append(f"{label}变了（`{key}`：基线 `{b}`，本次 `{c}`）—— 先断代，"
                           "别把这次差异当回归")
    missing = [i for i in (baseline.get("pass3_ids") or []) if i not in cases]
    if missing:
        reasons.append(f"报告缺 {len(missing)} 道基线里的题（{'、'.join(missing[:5])}…）："
                       "题集与基线不是同一批")
    if reasons:
        return {"verdict": "config", "reasons": reasons, "flips": [], "metrics": {}}

    # ---- 跑批完整性：infra_error 不是能力读数 -----------------------------
    infra = sorted(i for i, c in cases.items() if c.get("infra_error"))
    if infra:
        return {"verdict": "config",
                "reasons": [f"{len(infra)} 道题是 infra_error（网关/执行器失败），"
                            f"本次读数不作数，重跑：{'、'.join(infra[:8])}"
                            + ("…" if len(infra) > 8 else "")],
                "flips": [], "metrics": {}}

    # ---- 判红只看配对净退步；规则 1/2 只提示（B5，2026-11-20） ----------
    correct = sum(1 for c in cases.values() if c.get("correct"))
    overall = (report.get("overall") or {}).get("correct")
    if isinstance(overall, int) and overall != correct:
        return {"verdict": "config",
                "reasons": [f"报告自相矛盾：`overall.correct`={overall}，逐题数出来 {correct}"],
                "flips": [], "metrics": {}}

    base_correct = int(baseline.get("correct") or 0)
    drop = base_correct - correct
    max_drop = int((baseline.get("rules") or {}).get("max_drop", MAX_DROP))
    max_flips = int((baseline.get("rules") or {}).get("max_pass3_flips", MAX_PASS3_FLIPS))
    max_net = int((baseline.get("rules") or {}).get("max_paired_net_drop", MAX_PAIRED_NET_DROP))

    # 配对的两条腿：只在高置信池里数，噪声带（unstable_ids）两边都不算。
    pass3 = list(baseline.get("pass3_ids") or [])
    flips = [i for i in pass3 if not cases[i].get("correct")]        # 退步：三跑全对 → 本次错
    failed = list(baseline.get("failed_ids") or [])
    gains = [i for i in failed if cases.get(i, {}).get("correct")]   # 进步：三跑全错 → 本次对
    net = len(flips) - len(gains)

    fired: list[str] = []
    if net >= max_net:
        fired.append(f"配对翻转：三跑全对的题里 {len(flips)} 题变错、三跑全错的题里 "
                     f"{len(gains)} 题变对，净退步 {net} 题（阈值 {max_net}）—— "
                     "同题配对抵得掉单跑抖动，净退步过阈才判红")

    # 提示不拦：列出来备查，不进退出码、也不进 `fired`。B5：规则 1 也降级到这里。
    label = str(baseline.get("version") or "v7")  # 基线版本从基线文件读，v8 起必填
    notes: list[str] = []
    if drop >= max_drop:
        notes.append(f"规则 1（已降级为只列不拦，B5）：通过数 {correct}/{n}，比基线 "
                     f"{base_correct} 低 {drop} 题（原阈值 {max_drop}）—— 总数差分辨不出"
                     "噪声带（±6 题），判红改看上面的配对翻转")
    if flips:
        notes.append(f"退步（不拦）：{label} 三跑全对的题里有 {len(flips)} 题变错 —— "
                     + "、".join(flips[:8]) + ("…" if len(flips) > 8 else ""))

    if gains:
        notes.append(f"进步（不拦）：{label} 三跑全错的题里有 {len(gains)} 题本次答对 —— "
                      + "、".join(gains))

    metrics = {
        "n": n,
        "correct": correct,
        "baseline_correct": base_correct,
        "drop": drop,
        "pass3_total": len(pass3),
        "pass3_flips": len(flips),
        "paired_gains": len(gains),
        "paired_net": net,
        "max_drop": max_drop,
        "max_pass3_flips": max_flips,
        "max_paired_net_drop": max_net,
    }
    if fired:
        return {"verdict": "red", "reasons": fired + notes, "flips": flips,
                "gains": gains, "metrics": metrics}
    return {"verdict": "green",
            "reasons": [f"通过 {correct}/{n}（基线 {base_correct}，{_delta(drop)}）；"
                        f"配对净退步 {net}（退步 {len(flips)}，进步 {len(gains)}），"
                        f"未过阈值 {max_net}"] + notes,
            "flips": flips, "gains": gains, "metrics": metrics}


def render_brief(result: dict, baseline: dict, report: dict, report_path: str,
                 commits: list[str], commits_note: str = "") -> str:
    m = result.get("metrics") or {}
    label = str(baseline.get("version") or "v7")
    head = {"green": "🟢 GREEN", "red": "🔴 RED", "config": "⚪ 不可比"}[result["verdict"]]
    lines = [f"# nightly 回归简报 —— {head}", ""]
    lines.append(f"- 跑批：`agent={report.get('agent')}` `memory_mode={report.get('memory_mode')}` "
                 f"`n={m.get('n', len(report.get('cases') or []))}`")
    lines.append(f"- 报告：`{report_path}`")
    lines.append(f"- 基线：{label}（{baseline.get('runs')} 三跑，取中位 {baseline.get('correct')}/"
                 f"{baseline.get('n')}；pass^3 {baseline.get('pass3')}）")
    lines.append("")
    lines.append("## 判定")
    for r in result["reasons"]:
        lines.append(f"- {r}")
    if result["verdict"] == "config":
        lines.append("")
        lines.append("> 这不是回归：读数与基线不可比，或本次没跑完整。先修流水线；"
                     "尺子（题库/gold/判分）动过就先断代。")
        return "\n".join(lines) + "\n"

    if m:
        lines += ["", "## 读数", "",
                  f"| 项 | 本次 | 基线 {label} | 差 |", "|---|---|---|---|",
                  f"| 通过数 | {m['correct']}/{m['n']} | {m['baseline_correct']}/{m['n']} | "
                  f"{_delta(m['drop'])}（只列，不拦） |",
                  f"| 三跑全对的题变错（退步） | {m['pass3_flips']} | 0 | +{m['pass3_flips']}"
                  "（只列，不拦） |",
                  f"| 三跑全错的题变对（进步） | {m.get('paired_gains', 0)} | 0 | "
                  "+0（只列，不拦） |",
                  f"| 配对净退步 | {m.get('paired_net', 0)} | 0 | "
                  f"阈值 {m.get('max_paired_net_drop', 6)}，过阈才红 |"]

    gains = result.get("gains") or []
    if gains:
        lines += ["", f"## 进步的题（{len(gains)} 道，{label} 三跑全错 → 本次对；"
                  "**只列不拦**）", "",
                  "、".join(f"`{i}`" for i in gains)]

    cases = _case_map(report)
    if result["flips"]:
        lines += ["", f"## 翻了的题（{len(result['flips'])} 道，{label} 三跑全对 → 本次错；"
                  "**只列不拦**）", "",
                  "| id | 分类 | 题面 | gold | 本次答案 |", "|---|---|---|---|---|"]
        for cid in result["flips"]:
            c = cases[cid]
            lines.append(f"| `{cid}` | {c.get('category') or ''} | {_clip(c.get('question'), 46)} | "
                         f"{_clip(c.get('expected'), 28)} | {_clip(c.get('actual'), 28)} |")
    else:
        lines += ["", "## 翻了的题", "", "无：三跑全对的题本次全对。"]

    old = [i for i, c in cases.items() if not c.get("correct") and i in set(baseline.get("unstable_ids") or [])]
    if old:
        lines += ["", f"另有 {len(old)} 道错题是 {label} 里本来就晃的（1/3~2/3），不影响判定："
                  + "、".join(f"`{i}`" for i in sorted(old))]

    lines += ["", "## 提交区间（上次绿 → 本次；是嫌疑范围，不是归因）", ""]
    if commits_note:
        lines.append(commits_note)
    if commits:
        for c in commits:
            lines.append(f"- {c}")
    elif not commits_note:
        lines.append("（无提交记录：同一提交重跑，或没取到上次绿的 sha）")

    lines += ["", "## 怎么处置", "",
              "- **不自动修，也不改尺子。** 修由改产品的一侧做：先看上面翻的题对应哪类能力，"
              "再回到提交区间里找改动。",
              "- 修完重跑同一条命令；绿了就不用管。翻转题一直会列在这儿，它不参与判定。",
              "- 只有在**题库/gold/判分**动过时才断代（新基线 + 文档），那是另一件事。"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="nightly 回归门禁（对基线比，默认 v8）")
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--commits-file", default=None,
                    help="提交清单文本（一行一条，由 workflow 用 git log 生成）")
    ap.add_argument("--out", default=os.path.join("outputs", "nightly_brief.md"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    def _abs(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(ROOT, p)

    report_path, baseline_path = _abs(args.report), _abs(args.baseline)
    try:
        report = json.load(open(report_path, encoding="utf-8"))
        baseline = json.load(open(baseline_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"读不了报告或基线：{e}", file=sys.stderr)
        return 2

    commits, note = [], ""
    if args.commits_file:
        p = _abs(args.commits_file)
        if os.path.exists(p):
            commits = [ln.strip() for ln in open(p, encoding="utf-8") if ln.strip()]
        else:
            note = f"（没找到提交清单 `{args.commits_file}`）"
    if not commits and not note:
        note = "（同一提交重跑，或没取到上次绿的 sha）"

    result = evaluate(report, baseline)
    brief = render_brief(result, baseline, report, args.report, commits, note)
    out = _abs(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(brief)

    if not args.quiet:
        print(brief)
    print(f"[nightly] verdict={result['verdict']} brief={args.out}", file=sys.stderr)
    return {"green": 0, "red": 1, "config": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
