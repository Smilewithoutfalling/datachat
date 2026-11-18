"""nightly 回归门禁：把一次 workflow+state 全量跑批与 v7 基线比。

## 它回答什么

「master 上的代码改动，有没有把已经答对的题弄错」。**只判这两件事**：

1. **通过数比基线低 6 题及以上**（`max_drop`）。v7 三跑是 194/192/192，
   单跑自然抖动实测 2 题（8 道题在 1/3~2/3 之间晃），6 题是 3 倍抖动。
2. **v7 里三跑全对的 188 道题，本次有 2 题及以上变错**（`max_pass3_flips`）。
   这条抓的是"幅度小但集中"的退化 —— 掉 2 道稳定题而总数只少 2 题时，规则 1 不会响。

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
| 0 | 绿 | 不用管 |
| 1 | 红（规则 1 或 2） | 看简报：哪些题翻了、这段区间有哪些提交 |
| 2 | 不可比 / 跑不完整 | 先修流水线；尺子变了就断代 |
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

DEFAULT_BASELINE = os.path.join("docs", "eval", "baseline_v7.json")
DEFAULT_REPORT = os.path.join("outputs", "nightly_v7.json")

# 两条红灯的默认值。**写死在代码里，不从环境变量读** —— 能随手改的门槛等于没有门槛。
# 改这两个数 = 改判定口径，要同时改 baseline 的 `rules` 与 docs/eval/README.md。
MAX_DROP = 6
MAX_PASS3_FLIPS = 2


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
    # 模型也是"被测对象"的一部分：v7 的三跑是在 Qwen3.5-397B-A17B 上量的，
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

    # ---- 两条红灯 ---------------------------------------------------------
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

    pass3 = list(baseline.get("pass3_ids") or [])
    flips = [i for i in pass3 if not cases[i].get("correct")]

    fired: list[str] = []
    if drop >= max_drop:
        fired.append(f"规则 1：通过数 {correct}/{n}，比基线 {base_correct} 低 {drop} 题"
                     f"（阈值 {max_drop}）")
    if len(flips) >= max_flips:
        fired.append(f"规则 2：v7 三跑全对的题里有 {len(flips)} 题变错"
                     f"（阈值 {max_flips}）：{'、'.join(flips[:8])}"
                     + ("…" if len(flips) > 8 else ""))

    metrics = {
        "n": n,
        "correct": correct,
        "baseline_correct": base_correct,
        "drop": drop,
        "pass3_total": len(pass3),
        "pass3_flips": len(flips),
        "max_drop": max_drop,
        "max_pass3_flips": max_flips,
    }
    if fired:
        return {"verdict": "red", "reasons": fired, "flips": flips, "metrics": metrics}
    return {"verdict": "green",
            "reasons": [f"通过 {correct}/{n}（基线 {base_correct}，{_delta(drop)}），"
                        f"三跑全对的题掉 {len(flips)} 道（阈值 {max_flips}）"],
            "flips": flips, "metrics": metrics}


def render_brief(result: dict, baseline: dict, report: dict, report_path: str,
                 commits: list[str], commits_note: str = "") -> str:
    m = result.get("metrics") or {}
    head = {"green": "🟢 GREEN", "red": "🔴 RED", "config": "⚪ 不可比"}[result["verdict"]]
    lines = [f"# nightly 回归简报 —— {head}", ""]
    lines.append(f"- 跑批：`agent={report.get('agent')}` `memory_mode={report.get('memory_mode')}` "
                 f"`n={m.get('n', len(report.get('cases') or []))}`")
    lines.append(f"- 报告：`{report_path}`")
    lines.append(f"- 基线：v7（{baseline.get('runs')} 三跑，取中位 {baseline.get('correct')}/"
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
                  "| 项 | 本次 | 基线 v7 | 差 |", "|---|---|---|---|",
                  f"| 通过数 | {m['correct']}/{m['n']} | {m['baseline_correct']}/{m['n']} | "
                  f"{_delta(m['drop'])} |",
                  f"| 三跑全对的题变错 | {m['pass3_flips']} | 0 | +{m['pass3_flips']} |",
                  f"| 阈值 | 掉 {m['max_drop']} 题 / 翻 {m['max_pass3_flips']} 题 | — | — |"]

    cases = _case_map(report)
    if result["flips"]:
        lines += ["", f"## 翻了的题（{len(result['flips'])} 道，v7 三跑全对 → 本次错）", "",
                  "| id | 分类 | 题面 | gold | 本次答案 |", "|---|---|---|---|---|"]
        for cid in result["flips"]:
            c = cases[cid]
            lines.append(f"| `{cid}` | {c.get('category') or ''} | {_clip(c.get('question'), 46)} | "
                         f"{_clip(c.get('expected'), 28)} | {_clip(c.get('actual'), 28)} |")
    else:
        lines += ["", "## 翻了的题", "", "无：三跑全对的题本次全对。"]

    old = [i for i, c in cases.items() if not c.get("correct") and i in set(baseline.get("unstable_ids") or [])]
    if old:
        lines += ["", f"另有 {len(old)} 道错题是 v7 里本来就晃的（1/3~2/3），不计入规则 2："
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
              "- 修完推 master，nightly 自动重跑；绿了就不用管。",
              "- 只有在**题库/gold/判分**动过时才断代（新基线 + 文档），那是另一件事。"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="nightly 回归门禁（对 v7 基线）")
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
