"""把两种报告格式归一成同一种行，供 replay / render / compare 共用。

这个仓库同时存在两套逐题报告（规格 §1.1）：

- **评测报告**（`run_eval.py`）：单题判定字段是 `correct`，没有 `group` / `failure_class`。
- **闸门报告**（`scripts/gate/run_gate.py`）：判定字段是 `auto_correct` + `human_correct`
  （人工签，可为 null），**没有 `correct` 键**，没有 `actual_obj`。

还包括两种不是逐题报告的文件：

- `*_summary.json`：只有 `runs[]`，每个 run 的 `file` 是带盘符的绝对路径，
  指向 `outputs/`（在 `.gitignore` 里）。新克隆的仓库里这些文件不存在 ——
  那是**正常**的，记 `missing_runs` 继续，不算解析失败。
- `baselines.json`：基线登记表，不是报告。归 `not_a_report`，同样不算失败，
  但它必须被**认出来**，不能当成"零行报告"混进统计。

## 判定取哪个字段

规格 §EV-D1：`human_correct` 非 null → 用它；否则 `auto_correct`；否则 `correct`。

实测两套格式从不并存这两个字段（闸门报告 `correct` 全为 null，评测报告连
`auto_correct` 这个键都没有），所以顺序对现有数据无影响。但 `inspect()` 会显式
检 `conflicting_verdict_fields`：将来真并存且冲突时，宁可报出来，也不能悄悄挑一个。

## 为什么单独成模块

`compare.py` 已经实现过一遍同样的取值逻辑（`_verdict`），`render.py` 还要再要一遍。
第三次抄就是三份实现一定漂移。判定字段的单一真相在这里，别处只 import。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Iterator

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 取值优先级。改动它等于改所有报告的读数，别随手动。
VERDICT_FIELDS = ("human_correct", "auto_correct", "correct")

KIND_GATE = "gate"
KIND_EVAL = "eval"
KIND_SUMMARY = "summary"
KIND_NOT_A_REPORT = "not_a_report"

# 单题行缺了就说明报告结构坏了（不是"这个格式本来就没有"）。
HARD_FIELDS = ("id", "category", "question")

# `runs[].file` 是绝对路径且带盘符，按 basename 回退到这两个目录。
FALLBACK_DIRS = (("outputs",), ("docs", "eval"))


class ReportError(ValueError):
    """报告读不了、或不是逐题报告（比如 `*_summary.json` 当成单份传进来）。"""


@dataclass(frozen=True)
class Row:
    """一行 = 一道题的判定 + 渲染需要的字段。"""

    report: str           # 报告文件名；summary 展开时是 `xxx_summary.json#run1`
    id: str
    group: str            # 缺 → ""（评测报告没有这个字段，不是"缺失"）
    category: str
    dataset: str | None
    question: str
    executed: bool
    correct: bool | None  # None = 待判（闸门报告人工字段没填、也没有 auto）
    match: str | None     # 只在判对时有意义；判错的行一律 None
    tokens: int | None    # None ≠ 0，算均值时要跳过
    duration_s: float | None
    failure_class: str | None
    chart: dict | None
    correct_field: str    # 实际取值的字段名，或 "pending"
    error: str | None = None
    unverified: int = 0   # 单题 `unverified_numbers` 的条数
    guessing: bool = False
    # 成本块用（规格 §EV-C5）：估算值与真数必须分得开。
    # 老报告没有这两个键 → False / None，此时"按真数算"而不是把行丢掉。
    tokens_estimated: bool = False
    tokens_reported: bool | None = None
    # 负向题三分类（EV-B7）。老报告没有这个键 → ""（等价于普通题）。
    # 只有 "clarify" 有特殊含义：正确行为是**不执行代码**，所以"没执行"在它身上
    # 不是失败。判定本身仍看 correct，这里只供渲染与档位校验区分。
    expect_kind: str = ""


def load(path: str) -> dict:
    """读 JSON。失败抛 `ReportError`，绝不返回空 dict 让上层当"零行报告"。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise ReportError(f"{path}: 文件不存在") from e
    except IsADirectoryError as e:
        raise ReportError(f"{path}: 是目录不是文件") from e
    except OSError as e:
        # shell 没展开的 glob（`docs/eval/*.nope`）会走到这里：Windows 抛
        # `OSError(22, Invalid argument)`，POSIX 抛 ENOENT。两者都得是 ReportError，
        # 否则 replay 会以崩栈而不是"这一份解析失败"的形式退出去。
        raise ReportError(f"{path}: 打不开（{e.strerror or e}）") from e
    except json.JSONDecodeError as e:
        raise ReportError(f"{path}: 不是合法 JSON（{e.lineno}:{e.colno}）") from e
    if not isinstance(data, dict):
        raise ReportError(f"{path}: 顶层是 {type(data).__name__}，不是对象")
    return data


def kind_of(data: dict) -> str:
    """识别文件种类。判定顺序要紧：先看 cases，再看 runs。"""
    cases = data.get("cases")
    if isinstance(cases, list):
        # 闸门报告的标记字段。`questions_sha256` 是早期 gate 报告唯一可用的判据。
        if "auto_correct" in data or "questions_sha256" in data:
            return KIND_GATE
        return KIND_EVAL
    if isinstance(data.get("runs"), list):
        return KIND_SUMMARY
    return KIND_NOT_A_REPORT


def verdict_of(case: dict) -> tuple[bool | None, str]:
    """单题判定与来源字段名。`(None, "pending")` = 三个字段都空。"""
    for name in VERDICT_FIELDS:
        v = case.get(name)
        if v is not None:
            return bool(v), name
    return None, "pending"


def resolve_run_file(raw: str) -> str | None:
    """把 `runs[].file` 解析成真实路径；解析不出来返回 None（调用方记 missing_runs）。

    先试原路径 —— 在本机跑过的报告里它确实存在。再按 basename 回退：
    新克隆的仓库里 `outputs/` 是空的，但同名文件常常也在 `docs/eval/` 里归档了一份。
    """
    if not raw:
        return None
    if os.path.exists(raw):
        return raw
    # 报告可能来自 Windows 机器，反斜杠在 POSIX 上不是分隔符。
    base = os.path.basename(raw.replace("\\", "/"))
    if not base:
        return None
    for parts in FALLBACK_DIRS:
        p = os.path.join(ROOT, *parts, base)
        if os.path.exists(p):
            return p
    return None


def _as_int(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return None


def _as_float(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _count_unverified(v) -> int:
    if isinstance(v, list):
        return len(v)
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    return 0


def _row(report: str, case: dict) -> Row:
    ok, field = verdict_of(case)
    return Row(
        report=report,
        id=str(case.get("id") or ""),
        group=case.get("group") or "",
        category=case.get("category") or "",
        dataset=case.get("dataset") or None,
        question=case.get("question") or "",
        executed=bool(case.get("executed")),
        correct=ok,
        # 判错的行不该有层级 —— 它压根没判对。残留的 match 会把 strict_rate 抬高。
        match=(case.get("match") if ok else None),
        tokens=_as_int(case.get("tokens")),
        duration_s=_as_float(case.get("duration_s")),
        failure_class=case.get("failure_class") or None,
        chart=case.get("chart") if isinstance(case.get("chart"), dict) else None,
        correct_field=field,
        error=case.get("error") or None,
        unverified=_count_unverified(case.get("unverified_numbers")),
        guessing=bool(case.get("guessing")),
        tokens_estimated=bool(case.get("tokens_estimated")),
        tokens_reported=case.get("tokens_reported"),
        expect_kind=case.get("expect_kind") or "",
    )


def iter_rows(path: str) -> Iterator[Row]:
    """逐题产出。summary 会被展开，`Row.report` 带 `#runN` 后缀。

    summary 里解析不到的 run **静默跳过** —— 由 `inspect()` 记 `missing_runs`。
    这里抛异常会让"新克隆的仓库跑 replay"直接失败，而那批文件本来就不在版本控制里。
    """
    data = load(path)
    kind = kind_of(data)
    name = os.path.basename(path)

    if kind == KIND_SUMMARY:
        for r in data.get("runs") or []:
            if not isinstance(r, dict):
                continue
            sub_path = resolve_run_file(str(r.get("file") or ""))
            if not sub_path:
                continue
            label = f"{name}#run{r.get('run')}"
            for row in iter_rows(sub_path):
                yield replace(row, report=label)
        return

    if kind == KIND_NOT_A_REPORT:
        raise ReportError(
            f"{path}: 不是逐题报告（顶层键 {', '.join(sorted(data)[:8])}）"
        )

    cases = data.get("cases") or []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise ReportError(f"{path}: cases[{i}] 是 {type(c).__name__}，不是对象")
        row = _row(name, c)
        if not row.id:
            raise ReportError(f"{path}: cases[{i}] 没有 id，无法配对")
        yield row


def iter_reports(paths: list[str]) -> Iterator[Row]:
    for p in paths:
        yield from iter_rows(p)


def inspect(path: str) -> dict:
    """回放用：这份文件能不能被解析、行数多少、结构有没有洞。

    不看内容对不对，只看结构。返回的 dict 直接给 `replay.py` 打印。
    """
    info = {
        "path": path,
        "report": os.path.basename(path),
        "kind": None,
        "schema_version": None,
        "n": 0,
        "runs": 0,
        "missing_runs": [],
        "missing_fields": {},
        "pending": 0,
        "no_match_when_correct": 0,
        "conflicts": [],
        "note": None,
    }

    data = load(path)
    kind = kind_of(data)
    info["kind"] = kind
    info["schema_version"] = data.get("schema_version", 1)

    if kind == KIND_NOT_A_REPORT:
        info["note"] = "不是报告，" + "顶层键 " + ", ".join(sorted(data)[:8])
        return info

    if kind == KIND_SUMMARY:
        runs = [r for r in (data.get("runs") or []) if isinstance(r, dict)]
        info["runs"] = len(runs)
        for r in runs:
            raw = str(r.get("file") or "")
            sub_path = resolve_run_file(raw)
            if not sub_path:
                info["missing_runs"].append(os.path.basename(raw.replace("\\", "/")) or "(空)")
                continue
            sub = inspect(sub_path)
            info["n"] += sub["n"]
            info["pending"] += sub["pending"]
            info["no_match_when_correct"] += sub["no_match_when_correct"]
            for k, v in sub["missing_fields"].items():
                info["missing_fields"][k] = info["missing_fields"].get(k, 0) + v
        return info

    rows = list(iter_rows(path))
    info["n"] = len(rows)
    for row in rows:
        for f in HARD_FIELDS:
            if not getattr(row, f):
                info["missing_fields"][f] = info["missing_fields"].get(f, 0) + 1
        if row.correct is None:
            info["pending"] += 1
        elif row.correct and row.match is None:
            # strict_rate 算不出来的根因 —— 评测报告那一批就是这里全是 0 之外的数。
            info["no_match_when_correct"] += 1

    # 三个判定字段并存且不一致：不是"哪个优先"的问题，是这份报告本身有问题。
    for c in data.get("cases") or []:
        if not isinstance(c, dict):
            continue
        seen = {k: c[k] for k in VERDICT_FIELDS if c.get(k) is not None}
        if len(seen) > 1 and len({bool(v) for v in seen.values()}) > 1:
            info["conflicts"].append({"id": c.get("id"), **seen})
    return info


def summarize(rows: list[Row]) -> dict:
    """给渲染用的汇总。`correct is None` 的行不进分母 —— 待判不是判错。"""
    judged = [r for r in rows if r.correct is not None]
    n = len(judged)
    ok = sum(1 for r in judged if r.correct)
    tiers: dict[str, int] = {}
    for r in judged:
        if r.correct:
            tiers[r.match or "unknown"] = tiers.get(r.match or "unknown", 0) + 1
    tokens = [r.tokens for r in judged if r.tokens is not None]
    durs = [r.duration_s for r in judged if r.duration_s is not None]
    return {
        "n": n,
        "correct": ok,
        "pending": len(rows) - n,
        "accuracy": round(100.0 * ok / n, 1) if n else None,
        "tiers": tiers,
        "executed": sum(1 for r in judged if r.executed),
        "errors": [r for r in judged if r.error],
        "tokens_missing": sum(1 for r in judged if r.tokens is None),
        "avg_tokens": round(sum(tokens) / len(tokens), 1) if tokens else None,
        "avg_duration_s": round(sum(durs) / len(durs), 2) if durs else None,
    }
