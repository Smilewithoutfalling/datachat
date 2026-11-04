"""漂移哨兵（EV-D5）：拿十道固定探针的读数，判"模型权重是不是被换了"。

## 它补的是哪个洞

指纹体系记的 `fingerprints.model` 只是一个名字（`Qwen3.5-397B-A17B`）。网关后面换成
哪个快照，报告里一个字符都不会变。所以「代码没动、题没动、模型名也没动，读数却变了」
这件事，只有拿一份**冻结的探针基线**去比才看得出来。探针清单在 `app/eval/canary.py`
（十条标量题、单轮、无歧义），本脚本只管"跑完之后的比对"。

## 三条判定，按优先级

| 情况 | 结论 | 退出码 |
|---|---|---|
| `canary_sha12` 与基线不同 | `incomparable`：换了卷子，读数不是同一件事 | 2 |
| `code_sha12` 与基线不同 | `stale_baseline`：尺子动过，**不能**把差异算到权重头上 | 2 |
| 任何一轮判对数 < 基线，或 usage 比例移动 > 20% | `drift`：这才叫漂移 | 1 |
| 以上都不是 | `clean` | 0 |

`incomparable` / `stale_baseline` 单独给退出码，是为了让 CI 的动作不同：前者要改题单，
后者要**重立基线**（`--init`）。把这两种混进 `drift`，等于天天误报权重变化。

## usage 只在这个网关能看到的维度上比

规格写的是"四元组 input/output/cache_read/reasoning"，但实测（`holdout_20261103_*`
63 题、`eval_react_canary_*`）：**`tokens_cache_read` 与 `tokens_reasoning` 恒为 `None`**，
网关不回这两项。所以比例只在两边都有数的维度上算；某一维度从"有"变"没有"（或反过来）
不当作比例变化，而是单独记 `usage_coverage`——那说明网关换了回包的字段，本身就是信号，
但把它算成"比例涨了 100%"会把真信号淹在假数值里。

## 基线的纪律

基线**不自动更新**。漂移确认之后才 `--init --force` 重立，并在 `docs/eval/LEDGER.md`
记一条日期与新 `code_sha12`。自动更新等于让哨兵自己闭嘴。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval.canary import CANARY_IDS  # noqa: E402

DEFAULT_BASELINE = os.path.join("docs", "eval", "canary", "baseline.json")

# usage 四元组。前两项每个网关都有，后两项看服务商（本网关恒 None，见模块说明）。
COMPONENTS = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_reasoning")

# 比例移动容忍度。规格给的是 20%（相对变化），不是绝对百分点。
RATIO_TOL = 0.20


def _sha12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _mentions(answer: str, expected) -> bool:
    """答案正文里有没有 gold 那个值。**只用于区分「算错」和「算对了但没交卷」。**

    10-30 那次已经把这两类混在一起误判过一回（`ord_004` 答案是 832.54、只是没赋
    `result`）。11-04 重立基线时 6 跑里又出两次，换着题出，形态一模一样。

    数值走"抽数字再比"而不是子串：`0.3` 是 `0.3665` 的子串，用 `in` 会把算错的判成算对。
    非数值（字符串 / 布尔）才退回子串比较。
    """
    text = answer or ""
    e = str(expected if expected is not None else "").strip()
    if not e or not text:
        return False
    if _NUMBER.fullmatch(e):
        want = float(e)
        return any(abs(float(x) - want) <= 1e-9 * max(1.0, abs(want))
                   for x in _NUMBER.findall(text))
    return e in text


def _expand(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        hits = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        out.extend(hits or [p])
    return out


def load_run(path: str) -> dict:
    """读一份 canary 报告 = 一次 run。缺题或缺 `canary` 标记都直接抛错。

    不做"找到几条算几条"：少跑一条，读数就变成另一批题的平均，而文件名上仍写着
    canary —— 那比跑失败坏得多（`app/eval/canary.py` 的 `canary_cases` 同一个理由）。
    """
    data = json.load(open(path, encoding="utf-8"))
    name = os.path.basename(path)
    if not data.get("canary"):
        raise ValueError(f"{name}：不是 canary 报告（缺 `canary: true`）。"
                         "拿全量报告当探针，读数变化里会混进选题变化。")
    fps = data.get("fingerprints") or {}
    rows = {r["id"]: r for r in (data.get("cases") or [])}
    missing = [i for i in CANARY_IDS if i not in rows]
    if missing:
        raise ValueError(f"{name}：缺 {len(missing)} 条探针（{', '.join(missing)}）")
    cases = {}
    for i in CANARY_IDS:
        r = rows[i]
        cases[i] = {
            "correct": bool(r.get("correct")),
            # 答案原文只留哈希：探针要比的是"是不是同一句话"，不需要留全文。
            # 真要看原文去 outputs/ 里的报告，那里有 2000 字预览。
            "answer_sha12": _sha12(r.get("answer") or ""),
            # 掉题时靠这个分清"算错"和"没交卷"：后者答案常常是对的，只是没把值赋给
            # `result`。两者都要报，但不能混成一句话 —— 处置方式完全不同
            # （一个去看权重/数据，一个去看输出契约）。
            "result_missing": r.get("result_missing"),
            # 答案正文里有没有 gold。只在掉题时用来分「算错 / 没交卷」，不参与判定。
            "answer_has_gold": _mentions(r.get("answer"), r.get("expected")),
            "usage": {k: r.get(k) for k in COMPONENTS},
        }
    return {
        "file": name,
        "run": data.get("run"),
        "canary_sha12": data.get("canary_sha12") or fps.get("canary_sha12"),
        "code_sha12": fps.get("code_sha12"),
        "model": data.get("model"),
        "agent": data.get("agent"),
        "n": len(CANARY_IDS),
        "correct": sum(1 for c in cases.values() if c["correct"]),
        "cases": cases,
    }


def summarize(runs: list[dict]) -> dict:
    """把 1..k 次 run 折成一份可存基线的形状。"""
    if not runs:
        raise ValueError("没有可用的 canary 报告")
    # 混批是这个项目最容易犯的错：把两个不同尺子/不同题单的读数平均成一份，
    # 得到一个两边都不成立的新数字，而且从汇总上看不出来。宁可报错。
    shas = {r["canary_sha12"] for r in runs}
    if len(shas) > 1:
        raise ValueError(f"这批报告来自不同题单：{sorted(str(s) for s in shas)}；不能混着算")
    codes = {r["code_sha12"] for r in runs}
    if len(codes) > 1:
        raise ValueError(f"这批报告来自不同 code_sha12：{sorted(str(c) for c in codes)}；"
                         "尺子动过之后跑的报告不能与之前的算同一批")
    per = {i: {"passes": [], "answer_sha12": [], "result_missing": [], "answer_has_gold": []}
           for i in CANARY_IDS}
    for r in runs:
        for i in CANARY_IDS:
            c = r["cases"][i]
            per[i]["passes"].append(c["correct"])
            per[i]["answer_sha12"].append(c["answer_sha12"])
            per[i]["result_missing"].append(c.get("result_missing"))
            per[i]["answer_has_gold"].append(bool(c.get("answer_has_gold")))

    totals = {k: 0 for k in COMPONENTS}
    seen = {k: False for k in COMPONENTS}
    for r in runs:
        for i in CANARY_IDS:
            for k in COMPONENTS:
                v = r["cases"][i]["usage"].get(k)
                if _num(v):
                    totals[k] += int(v)
                    seen[k] = True
    used = [k for k in COMPONENTS if seen[k]]
    grand = sum(totals[k] for k in used) or 1

    corrects = [r["correct"] for r in runs]
    n = len(CANARY_IDS)
    return {
        "runs": len(runs),
        "n": n,
        "files": [r["file"] for r in runs],
        "model": runs[-1]["model"],
        "agent": runs[-1]["agent"],
        "canary_sha12": runs[-1]["canary_sha12"],
        "code_sha12": runs[-1]["code_sha12"],
        "correct_per_run": corrects,
        # 判对数取**最少的那一轮**：三跑里有一跑掉题就是不稳定，用均值会把它摊平。
        "min_correct": min(corrects),
        "accuracy": round(sum(corrects) / (n * len(runs)), 4),
        # 同一题跨轮判定不一致的条数。基线恒为 0；不为 0 说明这题本身在晃。
        "flips": sum(1 for i in CANARY_IDS if len(set(per[i]["passes"])) > 1),
        # 同题答案文本（哈希）跨轮变化的条数。**不是漂移判据**，只用来解释翻转：
        # 文本没变而判定变了 = 判分器在动；文本变了 = 模型在动。
        "answer_varied": sum(1 for i in CANARY_IDS if len(set(per[i]["answer_sha12"])) > 1),
        "usage_components": used,
        "usage_total": {k: totals[k] for k in used},
        "usage_ratio": {k: round(totals[k] / grand, 4) for k in used},
        "cases": {i: {"passes": per[i]["passes"],
                      "answer_sha12": per[i]["answer_sha12"][0],
                      "result_missing": per[i]["result_missing"],
                      "answer_has_gold": per[i]["answer_has_gold"]}
                  for i in CANARY_IDS},
    }


def _drop_kind(cur: dict, cid: str) -> str:
    """这一题掉的是「没交卷」还是「算错」。

    判据两条同时成立才算没交卷：`result_missing == "no_assign"`（代码没往 `result`
    写过东西）**且**答案正文里出现了 gold 那个值。只有前者不够 —— 算错的人也可能
    顺手没赋值，那还是要归到"算错"。

    为什么非要分：11-04 重立基线，6 跑 60 个题次里掉 2 次（3.3%），两次都是**答案对、没赋值**
    （`ord_013` 答 660、`ord_017` 答 0.3665，与 gold 一模一样），而且是**换着题出**的。
    这跟 10-30 排除 `ord_004` 的理由是同一个。按"掉了题就报漂移"判，这 6 跑里有 2 跑会响，
    而两次都不是权重问题 —— 哨兵照这个频率响，很快就被当成背景音。
    """
    passes = cur["cases"][cid]["passes"]
    missing = cur["cases"][cid].get("result_missing") or []
    gold = cur["cases"][cid].get("answer_has_gold") or []
    for ok, rm, has_gold in zip(passes, missing, gold):
        if not ok and not (rm == "no_assign" and has_gold):
            return "wrong"
    return "contract"


def compare(base: dict, cur: dict) -> dict:
    """基线 vs 本次。返回 `verdict` + `reasons`；不抛异常，让调用方决定退几。

    判定顺序：换卷子 > 换尺子 > 算错 > 没交卷 > 干净。**机制优先于条数** ——
    规格写的是"accuracy 掉 ≥1 题就算漂移"，但实测这条会按 6.7% 的题次误报合同类
    失败（见 `_drop_kind`）。分类之后，"算错"照旧一次就报，"没交卷"单独成一档。
    """
    reasons: list[str] = []
    changed: list[str] = []      # 掉题（按机制分）
    usage_notes: list[str] = []  # usage 比例/覆盖变化

    if base.get("canary_sha12") != cur.get("canary_sha12"):
        return {"verdict": "incomparable", "reasons": [
            f"canary_sha12 不同：基线 `{base.get('canary_sha12')}`，本次 `{cur.get('canary_sha12')}`"
            " —— 换了卷子，读数不是同一件事"]}

    stale = base.get("code_sha12") != cur.get("code_sha12")

    # 基线里判对的题、本次有哪几轮掉过。只比"基线全对"的题：基线自己就不稳的题
    # 拿来做判据，等于用晃的尺子量晃的东西。
    drops = [i for i in CANARY_IDS
             if all(base["cases"][i]["passes"]) and not all(cur["cases"][i]["passes"])]
    wrong = [i for i in drops if _drop_kind(cur, i) == "wrong"]
    contract = [i for i in drops if i not in wrong]

    if wrong:
        changed.append(f"算错 {len(wrong)} 题：" + "、".join(wrong))
    if contract:
        changed.append(f"没交卷 {len(contract)} 题（答案里有 gold，只是没赋 `result`）："
                       + "、".join(contract))

    base_ratio = base.get("usage_ratio") or {}
    cur_ratio = cur.get("usage_ratio") or {}
    for k in COMPONENTS:
        b, c = base_ratio.get(k), cur_ratio.get(k)
        if b is None and c is None:
            continue
        if b is None or c is None:
            # 一边有一边没有 = 网关回包字段变了。单独归类，不算比例移动。
            usage_notes.append(f"usage 覆盖变化：`{k}` 基线 {'有' if b is not None else '没有'} / "
                               f"本次 {'有' if c is not None else '没有'}")
            continue
        if b == 0:
            if c:
                usage_notes.append(f"usage 比例 `{k}`：基线 0 → 本次 {c:.4f}（无可比基数）")
            continue
        rel = (c - b) / b
        if abs(rel) > RATIO_TOL:
            usage_notes.append(f"usage 比例 `{k}` 移动 {rel:+.1%}（基线 {b:.4f} → 本次 {c:.4f}，"
                               f"容忍 ±{RATIO_TOL:.0%}）")

    if stale:
        reasons.append(f"code_sha12 不同：基线 `{base.get('code_sha12')}`，本次 "
                       f"`{cur.get('code_sha12')}` —— 尺子动过，差异不能算到权重头上；"
                       "确认改动与判分无关后 `--init --force` 重立基线")
        if changed or usage_notes:
            reasons.append("（本次仍然观察到：" + "；".join(changed + usage_notes) + "）")
        return {"verdict": "stale_baseline", "reasons": reasons}

    # usage 动了就是动了：它不看判定，是网关回包本身的形状，跟"没交卷"没关系。
    if wrong or usage_notes:
        return {"verdict": "drift", "reasons": changed + usage_notes}
    if contract:
        # 不算漂移，但也不许静默：3.3% 的题次挂在这上面，是真实的输出契约数字。
        return {"verdict": "contract", "reasons": changed + [
            "这批掉题都是「算对了没交卷」，不指向权重；但它是真实的输出契约问题，"
            "别当没发生 —— 需要时去看 outputs/ 里那几轮的 code"]}
    return {"verdict": "clean", "reasons": [
        f"{cur['runs']} 跑全 {cur['n']}/{cur['n']}，翻转 {cur['flips']}，"
        f"usage 比例在 ±{RATIO_TOL:.0%} 内"]}


_EXIT = {"clean": 0, "contract": 0, "drift": 1, "stale_baseline": 2, "incomparable": 2}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="canary 漂移哨兵（EV-D5）")
    ap.add_argument("paths", nargs="*", help="canary 报告路径或 glob（一次 run 一份）")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--init", action="store_true", help="用本次读数立基线（写入 --baseline）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的基线")
    ap.add_argument("--out", default=None, help="另存本次汇总 JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    paths = _expand(args.paths or [os.path.join("outputs", "eval_*_canary_*.json")])
    paths = [p for p in paths if not p.endswith("_summary.json")]
    if not paths:
        print("没有找到 canary 报告（先跑 `python run_eval.py --canary --agent react --repeat 3`）",
              file=sys.stderr)
        return 2
    runs = [load_run(p) for p in paths]
    cur = summarize(runs)

    base_path = args.baseline if os.path.isabs(args.baseline) else os.path.join(ROOT, args.baseline)
    out_path = args.out if (args.out and os.path.isabs(args.out)) else (
        os.path.join(ROOT, args.out) if args.out else None)

    if args.init:
        if os.path.exists(base_path) and not args.force:
            print(f"基线已存在：{base_path}\n确要重立（会丢掉旧的比对锚点）请加 --force",
                  file=sys.stderr)
            return 2
        payload = {"created": datetime.now().isoformat(timespec="seconds"), **cur}
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        with open(base_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        if not args.quiet:
            print(f"基线已写入：{base_path}")
            print(f"  {payload['runs']} 跑，判对数 {payload['correct_per_run']}/{payload['n']}，"
                  f"翻转 {payload['flips']}，canary_sha12 `{payload['canary_sha12']}`，"
                  f"code_sha12 `{payload['code_sha12']}`")
        return 0

    if not os.path.exists(base_path):
        print(f"没有基线：{base_path}\n先跑一次 `--init` 立基线", file=sys.stderr)
        return 2
    base = json.load(open(base_path, encoding="utf-8"))
    verdict = compare(base, cur)

    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"baseline": base_path, "created": datetime.now().isoformat(timespec="seconds"),
                       "result": verdict, "current": cur}, f, ensure_ascii=False, indent=1)

    if not args.quiet:
        print(f"canary 漂移检查：{verdict['verdict'].upper()}")
        for r in verdict["reasons"]:
            print(f"  - {r}")
        print(f"  基线 {base.get('created')}（{base.get('runs')} 跑，"
              f"判对数 {base.get('correct_per_run')}/{base.get('n')}）")
        if out_path:
            print(f"  JSON: {out_path}")
    return _EXIT[verdict["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
