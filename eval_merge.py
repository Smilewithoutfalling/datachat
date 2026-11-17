"""把主报告与若干补跑报告合并成一份可复算的报告（BACKLOG P2）。

为什么需要它：网关熔断 / 超时之后按题号补跑一直是手工的 —— 挑出 `infra_error` 的题、
`--case` 重跑、把数字加回 markdown 表格里。合并结果只活在人脑和文档里，仓库里找不到
任何一份 JSON 能复算出文档上写的数（DEVLOG [182] 的 169 与 181 就是这么来的）。

用法：

    python eval_merge.py outputs/eval_v7_wf_state_run1.json outputs/patch_a.json \
        --out outputs/eval_v7_wf_state_merged.json

规则：
  1. 补跑里出现的 case id **覆盖**主报告同 id 的记录，逐条打印前值/后值
  2. `overall` / `by_category` / `by_dataset` / `multi_turn` / `outcome` / `cost`
     全部按合并后的 cases 重算 —— 直接把结果灌回 `EvalReport`，不另写一套算术，
     否则合并器自己就成了第二个判据来源
  3. 以下三种情况**报错退出**而不是静默：
     - `evalset_sha256` 不一致（两批题不一样，合并没有意义）
     - 补跑里出现主报告不存在的 case id（多半是 --case 打错字）
     - `agent` / `memory_mode` 不一致（跨 agent 合并会造出一条不存在的口径）

`--drop-category memory`：丢掉某分类再重算。给"202 题目录里跑 195 题"那种口径用 ——
`off` 档会跳过 `requires_memory` 的 7 题，直接把 202 题的报告当 195 题读会虚高。
"""
import argparse
import json
import os
import sys

from app.eval.cases import ALL_CASES
from app.eval.report import EvalReport

CASE_BY_ID = {c.id: c for c in ALL_CASES}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _fp(report):
    return (report.get("fingerprints") or {}).get("evalset_sha12") or report.get("evalset", {}).get("sha12")


def to_result(rec):
    """报告里的 case 记录 → EvalReport 认的 result dict。

    报告是 result 的**序列化**（`to_json` 那份），键名基本同名。这里把能对上的都灌回去，
    再补上 `case` 对象；算不回来的（例如原始 `expected` 对象被 dump 过了）保留字符串形态 ——
    合并报告用于读数和复算 correct/by_category，不重跑判分。
    """
    case = CASE_BY_ID.get(rec.get("id"))
    if case is None:
        raise KeyError(rec.get("id"))
    r = dict(rec)
    r["case"] = case
    r.pop("id", None)        # 记录里 r["id"] 是给人看的；判分与统计一律用 r["case"].id
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="合并主报告与补跑报告")
    ap.add_argument("main", help="主报告 JSON")
    ap.add_argument("patches", nargs="*", help="补跑报告 JSON（可多份，按顺序覆盖；可为零，配合 --drop-category 单独重算）")
    ap.add_argument("--out", required=True, help="合并后的输出路径")
    ap.add_argument("--drop-category", action="append", default=[], help="丢掉某分类（可重复）")
    ap.add_argument("--allow-drop", action="store_true", help="允许 --drop-category 把题丢掉")
    args = ap.parse_args(argv)

    base = load(args.main)
    case_fps = {_fp(base)}
    agent = base.get("agent")
    mode = base.get("memory_mode")

    records = list(base.get("cases") or [])
    order = {rec["id"]: i for i, rec in enumerate(records)}
    by_id = {rec["id"]: rec for rec in records}

    overrides = []
    for path in args.patches:
        patch = load(path)
        if _fp(patch) != _fp(base):
            sys.exit(f"ABORT: {path} 的 evalset 指纹 {_fp(patch)} != 主报告 {_fp(base)}；"
                     f"两批题不一样，合并没有意义")
        if patch.get("agent") != agent:
            sys.exit(f"ABORT: {path} 的 agent={patch.get('agent')} != 主报告 {agent}")
        if patch.get("memory_mode") != mode:
            sys.exit(f"ABORT: {path} 的 memory_mode={patch.get('memory_mode')} != 主报告 {mode}")
        for rec in patch.get("cases") or []:
            cid = rec.get("id")
            if cid not in by_id:
                sys.exit(f"ABORT: {path} 里的 {cid} 不在主报告中（--case 打错字？）")
            old = by_id[cid]
            overrides.append((cid, bool(old.get("correct")), bool(rec.get("correct")),
                              os.path.basename(path)))
            by_id[cid] = rec
        case_fps.add(_fp(patch))

    merged = [by_id[rec["id"]] for rec in records]
    dropped = {}
    if args.drop_category:
        keep = []
        for rec in merged:
            cat = CASE_BY_ID[rec["id"]].category
            if cat in args.drop_category:
                dropped[cat] = dropped.get(cat, 0) + 1
            else:
                keep.append(rec)
        merged = keep
    if dropped:
        print(f"丢掉分类：{dropped}（剩 {len(merged)} 题）")

    print(f"合并 {len(args.patches)} 份补跑，覆盖 {len(overrides)} 条记录")
    for cid, before, after, src in overrides:
        mark = "→" if before else "→"   # 两个方向都值得看
        print(f"  {cid}: {before} {mark} {after}   ({src})")

    meta = {k: base.get(k) for k in ("time", "agent", "memory_mode", "git_sha", "git_sha_note")
            if k in base}
    meta["merged_from"] = [os.path.basename(args.main)] + [os.path.basename(p) for p in args.patches]
    meta["merged_dropped"] = dropped
    meta["merged_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")

    report = EvalReport([to_result(rec) for rec in merged], meta=meta,
                        baseline=base.get("fingerprints"))
    report.print_summary()
    report.to_json(args.out)
    s = report.summary()
    print(f"合并后：{s['overall']['correct']}/{s['overall']['n']}"
          f" = {s['overall']['correctness_rate']:.2f}%  →  {args.out}")
    mt = s.get("multi_turn")
    if mt:
        print(f"多轮：{mt['checked']} 轮被断言、{mt['failed']} 轮失败、rate {mt['rate']:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
