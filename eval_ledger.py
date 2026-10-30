#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评测台账生成器。

把 outputs/ 下所有报告汇总成 docs/eval/LEDGER.md（人读）+ docs/eval/runs/*.json（可复算）。

为什么要落库：outputs/ 在 .gitignore 里。只把数字抄进 markdown，原始 JSON 一清
（重装 / 换机 / 清理磁盘），那些数字就变成孤证 —— 既不能复算翻转率，也不能证明
"这两次跑的确实是同一批题"。所以台账分两层：

  LEDGER.md          表 + 结论。结论区（NOTES）由人手写，重建时原样保留。
  runs/<stem>.json   精简判定记录（id / correct / match / tokens / 耗时 / attempts）。
                     不含 code / answer（体积大且含模型原文），但够算 pass^k / flip_rate。

用法：
    python eval_ledger.py           # 重建
    python eval_ledger.py --check   # 只报差异，不写盘（退出码 1 = 需要重建）

注意：本文件在仓库根目录，不在 app/**/*.py 里，所以不参与 code_sha12 指纹。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIRS = [os.path.join(ROOT, "outputs"), os.path.join(ROOT, "docs", "eval")]
OUT_MD = os.path.join(ROOT, "docs", "eval", "LEDGER.md")
RUNS_DIR = os.path.join(ROOT, "docs", "eval", "runs")
BASELINES = os.path.join(ROOT, "docs", "eval", "baselines.json")

NOTES_BEGIN = "<!-- NOTES:BEGIN -->"
NOTES_END = "<!-- NOTES:END -->"
DEBUG_N = 10  # 少于这么多题的报告当单题调试，不进趋势表


# ---------------------------------------------------------------- 读报告

def _parse_time(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except (TypeError, ValueError):
            pass
    return None


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect():
    """扫 SRC_DIRS，按内容去重（docs/eval 里归档过的早期报告与 outputs 可能重复）。"""
    seen, out = {}, []
    for d in SRC_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not (name.startswith("eval_") and name.endswith(".json")):
                continue
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            data = _load(path)
            if not data or "cases" not in data:
                continue
            digest = hashlib.sha256(
                json.dumps(data.get("overall"), sort_keys=True).encode()
                + json.dumps([c.get("id") for c in data["cases"]][:5], sort_keys=True).encode()
                + str(len(data["cases"])).encode()
                + str(data.get("time")).encode()
            ).hexdigest()[:16]
            if digest in seen:  # 同一份报告存在两处
                continue
            seen[digest] = path
            out.append((path, data))
    out.sort(key=lambda p: (p[1].get("time") or "", p[0]))
    return out


def normalize(path, data):
    """把一份报告压成台账需要的形状。字段名跨版本不一致的地方在这里兜住。"""
    overall = data.get("overall") or {}
    fps = data.get("fingerprints") or {}
    cases = data.get("cases") or []
    n = overall.get("n") or len(cases)
    sha = (data.get("git_sha") or "unknown").rstrip("?")
    # oracle 与 canary 都不能进趋势批次：
    #   oracle —— 模型输出就是标准答案，那几个数字不代表能力，只证明流水线通；
    #   canary —— 十条探针，读数只用来比"模型权重变没变"，混进全量趋势会污染均值。
    #          特别注意 n=10 刚好卡在 `n < DEBUG_N` 的边界外，不显式判就会溜进批次表。
    if data.get("oracle"):
        kind = "oracle"
    elif data.get("canary"):
        kind = "canary"
    elif n < DEBUG_N:
        kind = "debug"
    else:
        kind = "gated" if fps.get("code_sha12") else "legacy"
    return {
        "file": os.path.basename(path),
        "time": data.get("time"),
        "dt": _parse_time(data.get("time")),
        "git_sha": sha,
        "agent": data.get("agent") or "?",
        "model": data.get("model"),
        "n": n,
        "correct": overall.get("correct"),
        "rate": overall.get("correctness_rate"),
        "exec_rate": overall.get("execution_success_rate"),
        "avg_duration_s": overall.get("avg_duration_s"),
        "avg_tokens": overall.get("avg_tokens"),
        "match_kinds": overall.get("match_kinds") or {},
        "memory_mode": fps.get("memory_mode") or data.get("memory_mode"),
        "code_sha12": fps.get("code_sha12"),
        "code_all_sha12": fps.get("code_all_sha12"),
        "evalset_sha12": fps.get("evalset_sha12") or (data.get("evalset") or {}).get("sha256"),
        "rendered_set_sha12": fps.get("rendered_set_sha12"),
        "canary_sha12": data.get("canary_sha12"),
        "comparable": data.get("comparable"),
        "kind": kind,
        "per_case": [
            {
                "id": c.get("id"),
                "category": c.get("category"),
                "correct": bool(c.get("correct")),
                "match": c.get("match"),
                "tokens": c.get("tokens"),
                "duration_s": c.get("duration_s"),
                "attempts": c.get("attempts"),
            }
            for c in cases
        ],
    }


# ---------------------------------------------------------------- 统计

def flip_stats(records):
    """同批次多次运行的逐题一致性。records 是同一批的 normalize 结果列表。"""
    if len(records) < 2:
        return None
    maps = [{c["id"]: c for c in r["per_case"]} for r in records]
    ids = [i for i in maps[0] if all(i in m for m in maps)]
    if not ids:
        return None
    flipped, all_correct, all_wrong = [], 0, []
    for i in ids:
        vs = [m[i]["correct"] for m in maps]
        if all(vs):
            all_correct += 1
        elif not any(vs):
            all_wrong.append(i)
        elif len(set(vs)) > 1:
            flipped.append(i)
    k = len(records)
    # flip_rate：任取一题、任取两次运行，判定不一致的概率。分母是(题, 二跑组合)。
    # 存小数不存百分数 —— stats.py 与 run_eval 的 stability 块都是小数，
    # 台账再存一份 2.05 就是两套单位，早晚会有某处乘两次 100。
    pairs = k * (k - 1) // 2
    disagree = 0
    for i in ids:
        vs = [m[i]["correct"] for m in maps]
        for a in range(k):
            for b in range(a + 1, k):
                if vs[a] != vs[b]:
                    disagree += 1
    return {
        "runs": k,
        "n": len(ids),
        "flip_rate": (disagree / (len(ids) * pairs)) if pairs else 0.0,
        "flipped": flipped,
        "all_correct": all_correct,
        "all_wrong": all_wrong,
        "pass_pow_k": all_correct / len(ids),
    }


def batch_key(r):
    """分批键 = (agent, 题数, code_sha12, 记忆模式)。

    记忆模式必须进键：`off` 与 `state` 是两种配置，混在一批里算均值会得到一个
    谁也不代表的数（2026-10-29 首测时 off 41% 与 state 82% 被平均成 60%）。
    """
    return (r["agent"], r["n"], r["code_sha12"] or "legacy", r["memory_mode"] or "—")


def load_baselines():
    """tag -> code_sha12。按指纹认基线，不按 commit 认 —— tag 指向的 commit 常常
    与跑报告的那个不同（报告要能对上 outputs 里的 git_sha）。"""
    data = _load(BASELINES) or {}
    return {v["code_sha12"]: (k, v) for k, v in data.items()
            if isinstance(v, dict) and v.get("code_sha12")}


def build_batches(records):
    groups = {}
    for r in records:
        # canary / oracle 各有各的表，不能混进来算均值（见 normalize 里的理由）
        if r["kind"] in ("debug", "oracle", "canary"):
            continue
        groups.setdefault(batch_key(r), []).append(r)
    batches = []
    for (agent, n, code, mode), rs in groups.items():
        rs.sort(key=lambda x: x["time"] or "")
        rates = [x["rate"] for x in rs if x["rate"] is not None]
        # 同批次里 evalset 理论上是同一个；真有多个就全列出来，别挑一个显示。
        evalsets = sorted({x["evalset_sha12"] for x in rs if x["evalset_sha12"]})
        batches.append({
            "agent": agent,
            "n": n,
            "memory_mode": mode,
            "code_sha12": None if code == "legacy" else code,
            "evalset_sha12": ", ".join(evalsets) if evalsets else None,
            "kind": rs[0]["kind"],
            "records": rs,
            "first": rs[0]["time"],
            "last": rs[-1]["time"],
            "mean": sum(rates) / len(rates) if rates else None,
            "min": min(rates) if rates else None,
            "max": max(rates) if rates else None,
            "flip": flip_stats(rs) if rs[0]["kind"] == "gated" else None,
        })
    batches.sort(key=lambda b: (b["first"] or "", b["agent"]))
    return batches


def fmt(v, spec="%.2f", dash="—"):
    return dash if v is None else (spec % v)


# ---------------------------------------------------------------- 渲染

HEADER = """# 评测台账

> 本文件由 `python eval_ledger.py` 生成，**数据区不要手改**（重建会覆盖）。
> 手写结论放在 `## 结论` 下方的标记块里（`NOTES:BEGIN` / `NOTES:END` 两行 HTML 注释之间），
> 重建时原样保留。
>
> 数据来源：`outputs/`、`docs/eval/` 下的 `eval_*.json`。`outputs/` 不入库，
> 逐题判定另存 `docs/eval/runs/*.json`，所以原始 JSON 清掉之后仍然能复算 pass^k / flip_rate。

## 怎么读这张表

- **`code_sha12` 是唯一门禁**。同 `code_sha12` 的报告才能拿来比数字；不同就是换了尺子，
  差异里混着"代码变了"和"模型抖了"，分不开。
- **`legacy`（无指纹）只能看趋势不能当基线**。那是 2026-10 上旬的探索，指纹体系还没建。
- **`n < 10` 是单题调试**，不进表。
- **oracle 与 canary 各自成表**。oracle 拿标准答案冒充模型输出，只证明流水线与判分口径通，
  不代表任何能力；canary 是十道固定探针题，只用来探模型权重漂移。两者的正确率都**不**混进
  全量趋势的均值——十条敏感题的平均值跟 163 题的平均值不是一回事。
- **`flip` 只对同 `code_sha12` 的多次运行有意义**。跨批次算"翻转"等于把代码差异算进噪声。
"""


def render_canary(records):
    """canary 段：十条固定探针看模型权重有没有动。

    单独成表是因为它的读数**不能**和全量趋势混着算：十条是挑出来的敏感题，正确率
    天生和 163 题的平均值不是一回事。它唯一的价值是"同题、同码、同尺子，读数变了"。
    """
    can = [x for x in records if x["kind"] == "canary"]
    if not can:
        return []
    L = ["## canary（固定十条探针，只探模型权重漂移）", ""]
    L.append("判读：`canary_sha12` 与 `code_sha12` 都相同，读数变了才能归到模型侧；"
             "任一指纹不同，只能重立基准，不算漂移。")
    L.append("")
    L.append("| 首次 | 跑数 | agent | 正确率 | 逐题翻转 | canary_sha12 | code_sha12 |")
    L.append("|---|---|---|---|---|---|---|")
    groups = {}
    for r in can:
        groups.setdefault((r["canary_sha12"], r["agent"], r["code_sha12"]), []).append(r)
    for _key, rs in sorted(groups.items(), key=lambda kv: (kv[1][0]["time"] or "")):
        rs.sort(key=lambda x: x["time"] or "")
        rates = [x["rate"] for x in rs if x["rate"] is not None]
        per = {}
        for x in rs:
            for c in x["per_case"]:
                per.setdefault(c["id"], []).append(1 if c["correct"] else 0)
        flipped = sorted(i for i, v in per.items() if len(set(v)) > 1)
        L.append("| %s | %d | %s | %s | %s | `%s` | %s |" % (
            (rs[0]["time"] or "?")[:19].replace("T", " "), len(rs), rs[0]["agent"] or "?",
            fmt(sum(rates) / len(rates), "%.0f%%") if rates else "—",
            ", ".join("`%s`" % i for i in flipped) if flipped else "0（一致）",
            rs[0]["canary_sha12"] or "—",
            ("`%s`" % rs[0]["code_sha12"]) if rs[0]["code_sha12"] else "legacy"))
    L.append("")
    return L


def render_oracle(records):
    """oracle 段：模型输出 = 标准答案，只证明流水线与判分口径通，不代表任何能力。"""
    orc = [x for x in records if x["kind"] == "oracle"]
    if not orc:
        return []
    L = ["## oracle 自检（假模型输出标准答案，不代表准确率）", ""]
    L.append("| 时间 | 文件 | 题数 | 通过率 |")
    L.append("|---|---|---|---|")
    for r in sorted(orc, key=lambda x: x["time"] or ""):
        L.append("| %s | `%s` | %d | %s |" % (
            (r["time"] or "?")[:19].replace("T", " "), r["file"], r["n"], fmt(r["rate"], "%.0f%%")))
    L.append("")
    return L


def render_notes(old_md):
    """把上一版里的手写结论原样搬过来。

    用 rfind 而不是 find：这个函数的失败模式很阴 —— 早先 HEADER 里写过一次标记字面量，
    find 抓到的是说明文字里那一处，于是结论区被截成了 " 与 " 两个字符，且不报错。
    取最后一处、再从它之后找 END，能把这类"文档里出现过同一个标记"的情况挡掉。
    """
    if not old_md:
        return "（首次生成，尚未写结论）"
    a = old_md.rfind(NOTES_BEGIN)
    if a == -1:
        return "（首次生成，尚未写结论）"
    b = old_md.find(NOTES_END, a)
    if b == -1:
        return "（首次生成，尚未写结论）"
    body = old_md[a + len(NOTES_BEGIN):b].strip("\n")
    return body or "（空）"


def render(records, batches, notes, now, baselines=None):
    baselines = baselines or {}
    L = [HEADER, ""]
    L.append("生成时间：%s · 报告 %d 份（其中 %d 份进表）· 逐题记录 %d 份"
             % (now, len(records), sum(len(b["records"]) for b in batches),
                len([r for r in records if r["kind"] == "gated"])))
    L.append("")
    L.append("## 结论")
    L.append("")
    L.append(NOTES_BEGIN)
    L.append(notes)
    L.append(NOTES_END)
    L.append("")

    # --- 批次表
    L.append("## 批次")
    L.append("")
    L.append("| 批次 | 时间 | agent | 题数 | mode | 运行 | 正确率 | 均值 | 逐题翻转 | 翻转题 | code_sha12 | 基线 | evalset |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for b in batches:
        rates = [x["rate"] for x in b["records"] if x["rate"] is not None]
        run_desc = ("单跑" if len(b["records"]) == 1
                    else "%d 跑 %s–%s" % (len(b["records"]),
                                          fmt(b["min"], "%.1f"), fmt(b["max"], "%.1f")))
        f = b["flip"]
        if f:
            flip_cell = "%.2f%%" % (f["flip_rate"] * 100)
            flip_n = "%d 题" % len(f["flipped"]) if f["flipped"] else "0"
        else:
            flip_cell, flip_n = "—", "—"
        label = ("`%s`" % b["code_sha12"]) if b["code_sha12"] else "legacy"
        base = baselines.get(b["code_sha12"])
        L.append("| %s / %d 题 | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            b["agent"], b["n"], (b["first"] or "?")[:10], b["agent"], b["n"],
            b["memory_mode"] or "—", run_desc,
            fmt(rates[-1] if len(rates) == 1 else None, "%.1f") if len(rates) == 1 else "—",
            fmt(b["mean"], "%.1f"), flip_cell, flip_n, label,
            ("**%s**" % base[0]) if base else "—",
            b["evalset_sha12"] or "—"))
    L.append("")
    L.append("> 正确率列：单跑写实际值；多跑的走均值列，避免把最后一跑当成结论。")
    L.append("")

    # --- 逐次明细
    L.append("## 逐次明细")
    L.append("")
    L.append("| 时间 | 文件 | agent | 题数 | 正确 | 正确率 | 执行成功 | 耗时/题 | token/题 | mode | code_sha12 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted([x for x in records if x["kind"] != "debug"], key=lambda x: x["time"] or ""):
        L.append("| %s | `%s` | %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            (r["time"] or "?")[:19].replace("T", " "), r["file"], r["agent"], r["n"],
            r["correct"] if r["correct"] is not None else "—",
            fmt(r["rate"], "%.2f"),
            fmt(r["exec_rate"], "%.1f"),
            fmt(r["avg_duration_s"], "%.2f"),
            fmt(r["avg_tokens"], "%.0f"),
            r["memory_mode"] or "—",
            ("`%s`" % r["code_sha12"]) if r["code_sha12"] else "legacy"))
    L.append("")

    # --- 翻转题清单
    any_flip = [b for b in batches if b["flip"] and b["flip"]["flipped"]]
    if any_flip:
        L.append("## 翻转题")
        L.append("")
        L.append("同一 `code_sha12` 下多次运行判定不一致的题。逐条都要有归因，"
                 "否则 `--repeat` 只是把噪声放大成结论。")
        L.append("")
        for b in any_flip:
            f = b["flip"]
            # agent 与 mode 必须进标题：同指纹、同题数的两批（workflow/react 各 143 题）
            # 会并列出现，只写题数分不清哪行是哪批。
            L.append("- `%s` %s / %d 题 / %s / %d 跑：pass^%d = %.2f%%，翻转 %.2f%%，翻转题 %s"
                     % (b["code_sha12"], b["agent"], f["n"], b["memory_mode"] or "—", f["runs"],
                        f["runs"], f["pass_pow_k"] * 100,
                        f["flip_rate"] * 100, ", ".join("`%s`" % i for i in f["flipped"])))
            if f["all_wrong"]:
                L.append("  - 全程错：%s" % ", ".join("`%s`" % i for i in f["all_wrong"]))
        L.append("")

    # --- canary / oracle：各自成表，不进趋势
    L.extend(render_canary(records))
    L.extend(render_oracle(records))

    # --- 调试 / 单题
    dbg = [x for x in records if x["kind"] == "debug"]
    if dbg:
        L.append("## 单题调试（n < %d，不进趋势）" % DEBUG_N)
        L.append("")
        L.append("| 时间 | 文件 | 题数 | 正确率 | code_sha12 |")
        L.append("|---|---|---|---|---|")
        for r in sorted(dbg, key=lambda x: x["time"] or ""):
            L.append("| %s | `%s` | %d | %s | %s |" % (
                (r["time"] or "?")[:19].replace("T", " "), r["file"], r["n"],
                fmt(r["rate"], "%.0f"),
                ("`%s`" % r["code_sha12"]) if r["code_sha12"] else "legacy"))
        L.append("")

    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- 落盘

def write_runs(records, dry):
    """逐题判定入库。只存 gated（有指纹）的 —— legacy 没指纹，存了也没法归因。"""
    os.makedirs(RUNS_DIR, exist_ok=True) if not dry else None
    written, kept = [], set()
    for r in records:
        if r["kind"] != "gated":
            continue
        name = os.path.splitext(r["file"])[0] + ".json"
        kept.add(name)
        payload = {
            "file": r["file"],
            "time": r["time"],
            "git_sha": r["git_sha"],
            "agent": r["agent"],
            "model": r["model"],
            "n": r["n"],
            "correct": r["correct"],
            "correctness_rate": r["rate"],
            "execution_success_rate": r["exec_rate"],
            "avg_duration_s": r["avg_duration_s"],
            "avg_tokens": r["avg_tokens"],
            "memory_mode": r["memory_mode"],
            "fingerprints": {
                "code_sha12": r["code_sha12"],
                "code_all_sha12": r["code_all_sha12"],
                "evalset_sha12": r["evalset_sha12"],
                "rendered_set_sha12": r["rendered_set_sha12"],
            },
            "per_case": r["per_case"],
        }
        if not dry:
            with open(os.path.join(RUNS_DIR, name), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
                f.write("\n")
        written.append(name)
    return written, kept


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成评测台账")
    ap.add_argument("--check", action="store_true", help="只报差异，不写盘")
    args = ap.parse_args(argv)

    records = [normalize(p, d) for p, d in collect()]
    if not records:
        print("没找到任何报告（看 outputs/ 与 docs/eval/）")
        return 1

    batches = build_batches(records)
    old = None
    if os.path.isfile(OUT_MD):
        with open(OUT_MD, encoding="utf-8") as f:
            old = f.read()
    notes = render_notes(old)
    md = render(records, batches, notes, datetime.now().strftime("%Y-%m-%d %H:%M"),
                load_baselines())

    changed = (old != md)
    if args.check:
        print("台账%s" % ("需要重建" if changed else "已是最新"))
        print("报告 %d 份，进表批次 %d 个" % (len(records), len(batches)))
        return 0 if not changed else 1

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    written, kept = write_runs(records, dry=False)
    # 清掉已不在报告里的旧 run（避免台账与档案对不上）
    if os.path.isdir(RUNS_DIR):
        for name in os.listdir(RUNS_DIR):
            if name.endswith(".json") and name not in kept:
                os.remove(os.path.join(RUNS_DIR, name))
    print("台账：%s" % os.path.relpath(OUT_MD, ROOT))
    print("逐题：docs/eval/runs/ 共 %d 份" % len(written))
    print("报告 %d 份 / 进表批次 %d 个 / 跳过单题调试 %d 份"
          % (len(records), len(batches), len([r for r in records if r["kind"] == "debug"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
