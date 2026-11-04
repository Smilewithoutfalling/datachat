"""五段式 Markdown 报告（规格 §EV-D1）。

一份 MD 让三种角色都能读：

1. 结论 —— 一行，过 / 不过 / 无基准
2. 关键数字 —— 准确率、严格率、区间、MDE、成本
3. 分类 / 分数据集 —— 表
4. 异常题 —— 执行失败、待判、靠放宽判对、图表异常、证据不一致、猜测
5. 环境与指纹 —— model、prompt_sha、evalset_sha、git_sha

## 两条硬约束

**不重跑 gold。** 渲染只读报告里已有的字段。重跑要几秒到几分钟，还可能因为数据
不在本机而失败 —— 报告是历史的凭证，渲染器没有资格改变它。

**严格率算不出来就说算不出来。** 18 份评测报告的单题行里没有 `match`，把缺失
当 `strict` 会让严格率凭空变高，当 `relaxed` 会凭空变低。两种都是编数，
`outcome.build` 因此把 `strict_rate` 置 None 并记 `unknown_tier`，这里照抄这个结论。

零第三方依赖（P5）：中文对齐用 `unicodedata.east_asian_width` 自己算显示宽度。
"""
from __future__ import annotations

import unicodedata

from app.eval import report_adapter as adapter
from app.eval.cost import build as build_cost
from app.eval.outcome import STRICT_TIER, build as build_outcome

# 判对但不算严的层级：比较器在这几层放行过，应人工抽审。
RELAXED_TIERS = ("rounded", "scaled", "extras", "relaxed")


def _dw(s: str) -> int:
    """显示宽度：中日韩全角字符占两格。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def _pad(s: str, width: int) -> str:
    return str(s) + " " * max(0, width - _dw(s))


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [_dw(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], _dw(c))
    fmt = lambda vals: "| " + " | ".join(_pad(v, widths[i]) for i, v in enumerate(vals)) + " |"
    out = [fmt(headers), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [fmt(r) for r in rows]
    return out


def _fmt_ids(ids: list[str], limit: int = 12) -> str:
    shown = "、".join(ids[:limit])
    return shown + (f" …等 {len(ids)} 题" if len(ids) > limit else "")


def _rows_as_dicts(rows: list[adapter.Row]) -> list[dict]:
    return [
        {
            "id": r.id,
            "correct": r.correct,
            "match": r.match,
            "category": r.category,
            "dataset": r.dataset,
        }
        for r in rows
    ]


# ---------------------------------------------------------------- 第 1 段


def _sec_conclusion(path: str, data: dict, kind: str, summ: dict) -> list[str]:
    n, ok, acc = summ["n"], summ["correct"], summ["accuracy"]

    if kind == adapter.KIND_SUMMARY:
        return [
            "## 1 结论",
            "",
            f"`{path}` 是**汇总报告**：逐题判定不在这个文件里，而在它 `runs[].file` 引用的"
            f"各 run 报告中。下面按 run 分列 —— **不合并**，见第 2 段。",
        ]

    if kind == adapter.KIND_GATE and isinstance(data.get("verdict"), dict):
        v = data["verdict"]
        prof = v.get("profile")
        fails = v.get("failures")
        parts = [f"单组 {v['single']}" if v.get("single") else "",
                 f"多轮 {v['multi']}" if v.get("multi") else ""]
        detail = "，".join(p for p in parts if p)
        tail = f"（profile {prof}" + (f"；{detail}" if detail else "") + "）"
        if fails == 0:
            return ["## 1 结论", "", f"**过** —— 回归 0 题" + tail + f"，判定 {ok}/{n}。"]
        return ["## 1 结论", "",
                f"**不过** —— 回归 {fails} 题" + tail + f"，判定 {ok}/{n}。"]

    if kind == adapter.KIND_GATE:
        return ["## 1 结论", "",
                f"**无基准** —— 闸门报告 {ok}/{n}，本份没跑过 `--verdict`，"
                f"没有阈值就谈不上过不过。"]

    return ["## 1 结论", "",
            f"**无基准** —— 评测报告 {ok}/{n}（{acc}%）。单份报告只能说明这一份，"
            f"要和谁比请用 `scripts/eval/compare.py`。"]


# ---------------------------------------------------------------- 第 2 段


def _sec_numbers(data: dict, rows: list[adapter.Row], summ: dict) -> list[str]:
    o = build_outcome(_rows_as_dicts(rows))
    out = ["## 2 关键数字", ""]

    rows_tbl = [["判定", f"{summ['correct']}/{summ['n']}"],
                ["准确率", f"{summ['accuracy']}%"]]

    lo, hi = o["wilson95"]
    rows_tbl.append(["95% Wilson 区间", f"[{lo}, {hi}]（±{o['wilson_halfwidth_pp']}pp）"])

    if o["strict_rate"] is None:
        why = (f"{o['unknown_tier']} 题判对但报告没记 `match`" if o.get("unknown_tier")
               else "没有判对的题，分母为 0")
        rows_tbl.append(["严格率", f"算不出（{why}）"])
    else:
        rows_tbl.append(["严格率", f"{o['strict_rate']}%（strict {o['strict']}/{o['correct']}）"])

    mix = "　".join(f"{k} {v}" for k, v in o["tier_mix"].items() if v) or "（无）"
    rows_tbl.append(["判对层级", mix])

    mde = f"{o['mcnemar_mde_flips']} 个单向翻转 ≈ {o['mde_equiv_pp']}pp"
    rows_tbl.append(["MDE", mde + ("" if o["mde_reachable"]
                                   else f"（多于 {o['n']} 题，不可达 —— 这批题测不出显著）")])

    rows_tbl.append(["执行成功", f"{summ['executed']}/{summ['n']}"])
    if summ["avg_tokens"] is None:
        rows_tbl.append(["平均 token", "算不出（全部缺）"])
    else:
        miss = f"，{summ['tokens_missing']} 题缺" if summ["tokens_missing"] else ""
        rows_tbl.append(["平均 token", f"{summ['avg_tokens']}{miss}"])
    rows_tbl.append(["平均耗时", f"{summ['avg_duration_s']}s" if summ["avg_duration_s"] is not None else "算不出"])
    # 成本与延迟（规格 §EV-C5）。平均数藏得住长尾，p95 才看得出"最慢那一档要等多久"。
    co = build_cost(rows)
    if co["n_tokens"]:
        est = f"，其中 {co['n_estimated']} 题是估算值" if co["n_estimated"] else ""
        rows_tbl.append(["token p50 / p95",
                         f"{co['tokens_per_case_p50']} / {co['tokens_per_case_p95']}"
                         f"（{co['n_tokens']} 题{est}）"])
    perc = co["per_correct_tokens"]
    rows_tbl.append(["每正确回答 token",
                     f"{int(perc)}" if perc is not None else "算不出（没有判对的题）"])
    if co["n_duration"]:
        rows_tbl.append(["耗时 p50 / p95",
                         f"{co['duration_p50_s']}s / {co['duration_p95_s']}s（{co['n_duration']} 题）"])
    if summ["pending"]:
        rows_tbl.append(["待判", f"{summ['pending']} 题（不计入分母）"])

    out += _table(["项", "值"], rows_tbl)
    return out


# ---------------------------------------------------------------- 第 3 段


def _sec_breakdown(rows: list[adapter.Row]) -> list[str]:
    o = build_outcome(_rows_as_dicts(rows))
    out = ["## 3 分类与数据集", ""]

    if o["by_category"]:
        tbl = [[g, f"{v['correct']}/{v['n']}",
                f"{round(100.0 * v['correct'] / v['n'], 1)}%" if v["n"] else "-"]
               for g, v in o["by_category"].items()]
        out += ["**按类别**", ""] + _table(["类别", "判对/总数", "准确率"], tbl) + [""]
    else:
        out += ["**按类别**：本份报告的单题行没有 `category`。", ""]

    if o["by_dataset"]:
        tbl = [[g, f"{v['correct']}/{v['n']}",
                f"{round(100.0 * v['correct'] / v['n'], 1)}%" if v["n"] else "-"]
               for g, v in o["by_dataset"].items()]
        out += ["**按数据集**", ""] + _table(["数据集", "判对/总数", "准确率"], tbl) + [""]
    else:
        out += ["**按数据集**：本份报告的单题行没有 `dataset`（评测报告不记这个字段）。", ""]
    return out


# ---------------------------------------------------------------- 第 4 段


def _chart_broken(ch: dict | None) -> str | None:
    """图表异常的原因；正常返回 None。"""
    if not ch:
        return None
    errs = (ch.get("chart_errors") or []) + (ch.get("chart_internal_errors") or [])
    if errs:
        return f"{len(errs)} 条错误"
    if ch.get("charts_discarded"):
        return f"丢弃 {ch['charts_discarded']} 张"
    # 有 option 却没画出来 —— 这是"该画没画"，和本来就不需要画（options=0）不同。
    if ch.get("options") and not ch.get("drew"):
        return "有 option 但没出图"
    return None


def _sec_anomalies(data: dict, rows: list[adapter.Row]) -> list[str]:
    out = ["## 4 异常题", ""]
    items: list[tuple[str, str]] = []

    errors = [r.id for r in rows if r.error]
    if errors:
        items.append(("执行失败", _fmt_ids(errors)))

    pending = [r.id for r in rows if r.correct is None]
    if pending:
        items.append(("待判（三个判定字段全空）", _fmt_ids(pending)))

    relaxed = [r for r in rows if r.correct and r.match in RELAXED_TIERS]
    if relaxed:
        items.append(("判对但靠放宽（应人工抽审）",
                      "、".join(f"{r.id}({r.match})" for r in relaxed[:12])
                      + (f" …等 {len(relaxed)} 题" if len(relaxed) > 12 else "")))
    elif any(r.correct and r.match == STRICT_TIER for r in rows):
        items.append(("判对但靠放宽", "无 —— 判对的全部是 strict"))

    broken = [(r.id, why) for r in rows if (why := _chart_broken(r.chart))]
    if broken:
        items.append(("图表异常", "、".join(f"{i}({w})" for i, w in broken[:10])
                      + (f" …等 {len(broken)} 题" if len(broken) > 10 else "")))

    unver = [r.id for r in rows if r.unverified]
    if unver:
        items.append(("证据不一致（答案里的数字没被代码产出）", _fmt_ids(unver)))

    guess = [r.id for r in rows if r.guessing]
    if guess:
        items.append(("疑似猜测", _fmt_ids(guess)))

    fc: dict[str, list[str]] = {}
    for r in rows:
        if r.failure_class:
            fc.setdefault(r.failure_class, []).append(r.id)
    if fc:
        items.append(("failure_class",
                      "；".join(f"{k} → {_fmt_ids(v, 6)}" for k, v in sorted(fc.items()))))

    if not items:
        out += ["本份没有可列的异常（执行失败 / 待判 / 靠放宽判对 / 图表 / 证据 / 猜测 全为 0）。"]
    else:
        out += _table(["类型", "题号"], [[k, v] for k, v in items])

    w = data.get("warnings")
    if isinstance(w, list) and w:
        out += ["", f"**报告自带的 warnings**（{len(w)} 条）：", ""]
        out += [f"- {str(x)[:200]}" for x in w[:10]]
    return out


# ---------------------------------------------------------------- 第 5 段


def _fp(data: dict, key: str):
    fp = data.get("fingerprints")
    return fp.get(key) if isinstance(fp, dict) else None


def _sec_env(path: str, data: dict, kind: str, no: int = 5) -> list[str]:
    ev = data.get("evalset") if isinstance(data.get("evalset"), dict) else {}
    hold = data.get("holdout") if isinstance(data.get("holdout"), dict) else {}

    evalset_sha = _fp(data, "evalset_sha12") or (ev.get("sha256") or "")[:12] or None
    prompt_sha = _fp(data, "prompt_sha12")

    tbl = [
        ["文件", f"`{path}`"],
        ["种类 / schema", f"{kind} / {data.get('schema_version', 1)}"],
        ["时间", data.get("time")],
        ["model", data.get("model")],
        ["agent", data.get("agent")],
        ["temperature", data.get("temperature")],
        ["git_sha", data.get("git_sha")],
        ["prompt_sha12", prompt_sha or "未记录"],
        ["evalset_sha12", evalset_sha or "未记录"],
        ["code_sha12（现在的尺子）", _fp(data, "code_sha12")],
        ["run_code_sha12（跑模型时的尺子）", data.get("run_code_sha12")],
    ]
    if hold:
        tbl.append(["留出集", f"{hold.get('version')} / n={hold.get('n')} / "
                              f"sha={(hold.get('questions_sha256') or '')[:12]}"])
    if data.get("python") or data.get("pandas"):
        tbl.append(["python / pandas", f"{data.get('python')} / {data.get('pandas')}"])
    if data.get("base_url_host"):
        tbl.append(["base_url_host", data.get("base_url_host")])

    out = [f"## {no} 环境与指纹", ""]
    out += _table(["项", "值"], [[k, "—" if v is None else str(v)] for k, v in tbl])

    if prompt_sha is None:
        out += ["", "> `prompt_sha12` 未记录：这份报告早于提示词指纹（规格 §EV-A3）。"
                    "它对新指纹体系永远是 legacy，不能声称「同提示词下可比」。"]
    if not evalset_sha:
        out += ["", "> `evalset_sha12` 未记录：题库改过之后无法确认这份报告跑的是哪一版题目。"]
    return out


# ---------------------------------------------------------------- 汇总报告


def _sec_summary_runs(rows: list[adapter.Row]) -> list[str]:
    """汇总报告按 run 分列。

    **不能合并。** 这几个 run 跑的是同一批题：3 个 run × 50 题 = 150 个题次，
    但只有 50 道不同的题。把它们当一个 150 题的大样本算 Wilson 区间，
    同一道题被数了三遍，区间会假性变窄 —— 那不是"样本更大"，是重复计数。
    逐 run 给数，再单算一个跨 run 稳定性，这两个才是这批数据支持的结论。
    """
    groups: dict[str, list[adapter.Row]] = {}
    for r in rows:
        groups.setdefault(r.report, []).append(r)

    out = ["## 2 逐 run", ""]
    if not groups:
        out += [
            "**一个 run 文件都没解析到。** `runs[].file` 指向 `outputs/`（被 `.gitignore` 排除），"
            "本机没有、`docs/eval/` 里也没有同名归档。这份文件能提供的只有第 3 段的环境信息。",
        ]
        return out

    tbl = []
    for label in sorted(groups):
        s = adapter.summarize(groups[label])
        o = build_outcome(_rows_as_dicts(groups[label]))
        tbl.append([
            label.split("#")[-1],
            f"{s['correct']}/{s['n']}",
            f"{s['accuracy']}%" if s["accuracy"] is not None else "-",
            "算不出" if o["strict_rate"] is None else f"{o['strict_rate']}%",
            "—" if s["avg_tokens"] is None else str(s["avg_tokens"]),
        ])
    out += _table(["run", "判定", "准确率", "严格率", "平均token"], tbl)

    by_id: dict[str, list[bool]] = {}
    for r in rows:
        if r.correct is not None:
            by_id.setdefault(r.id, []).append(r.correct)
    k = len(groups)
    full = {i: v for i, v in by_id.items() if len(v) == k}
    if full and k > 1:
        allok = sum(1 for v in full.values() if all(v))
        ever = sum(1 for v in full.values() if any(v))
        flaky = sorted(i for i, v in full.items() if any(v) and not all(v))
        out += ["", f"跨 {k} 个 run：{len(full)} 题有完整覆盖，"
                    f"**{allok} 题全对（pass^{k} = {round(100.0 * allok / len(full), 1)}%）**，"
                    f"{ever} 题至少对过一次，{len(flaky)} 题有波动。"]
        if flaky:
            out += [f"　波动题：{_fmt_ids(flaky)}"]
        out += ["", "> 别把上表加总：这几个 run 跑的是同一批题，"
                    "加总后的分母是题次的个数，不是题数。"]
    return out


# ---------------------------------------------------------------- 入口


def render(path: str) -> str:
    """渲染一份报告成五段 MD。解析失败抛 `adapter.ReportError`。"""
    data = adapter.load(path)
    kind = adapter.kind_of(data)
    if kind == adapter.KIND_NOT_A_REPORT:
        raise adapter.ReportError(
            f"{path}: 不是报告（顶层键 {', '.join(sorted(data)[:8])}）"
        )

    rows = list(adapter.iter_rows(path))
    summ = adapter.summarize(rows)

    if kind == adapter.KIND_SUMMARY:
        lines = [f"# 报告 {path}", ""]
        lines += _sec_conclusion(path, data, kind, summ)
        lines += [""] + _sec_summary_runs(rows)
        lines += [""] + _sec_env(path, data, kind, no=3)
        return "\n".join(lines) + "\n"

    lines = [f"# 报告 {path}", ""]
    lines += _sec_conclusion(path, data, kind, summ)
    lines += [""] + _sec_numbers(data, rows, summ)
    lines += [""] + _sec_breakdown(rows)
    lines += [""] + _sec_anomalies(data, rows)
    lines += [""] + _sec_env(path, data, kind)
    return "\n".join(lines) + "\n"
