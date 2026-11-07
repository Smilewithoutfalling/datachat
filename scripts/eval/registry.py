"""题集生命周期的检查 / 提议 / 确认（EV-D3）。

三个入口，**写操作只有 `--set`**：

    --check              校验状态机、幽灵条目、文档同步；非法非 0 退出
    --propose R...       读若干份报告（按时间顺序），提议谁该毕业/退役；只打印，不写
    --flip R...          读同一配置的 k 次重复跑，按 flip_rate > 0.4 提议退役；只打印，不写
    --set ID=STATE       人工确认一次迁移（必须带 --reason），写 registry.json

为什么毕业/退役要分两个"提议"入口：`--propose` 回答的是"跨 release 一直对/一直错"，
`--flip` 回答的是"同一份配置重复跑，判定自己会翻"。两者都需要，但混在一份报告里读会
把"模型不稳"和"题不稳"搞混——那份报告只有一次运行，k=1，谈不了翻转。

规则与理由见 `docs/eval/registry.md`；状态机的实现与校验在 `app/eval/registry.py`。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval import registry as R  # noqa: E402
from app.eval.report_adapter import iter_rows  # noqa: E402


def _case_ids() -> list[str]:
    from app.eval.cases import ALL_CASES
    return [c.id for c in ALL_CASES]


def _report_time(path: str) -> str:
    """报告的生成时间（顶层 `time`）。没有就退回文件 mtime，只用于"按时间排序"的可读提示。"""
    try:
        with open(path, encoding="utf-8") as f:
            t = json.load(f).get("time")
        if t:
            return str(t)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        return _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "?"


def _read_seq(paths: list[str], known: set[str]) -> tuple[dict[str, list], list[str]]:
    """按给定顺序读报告 → {case_id: [correct, ...]}，长度恒等于报告数。

    缺行补 None（不是跳过）：跳过会让后面几份报告的索引整体前移，"第 3 个 release 对不对"
    就错位了——这类错位不会报错，只会让提议看起来很有道理。

    只收题库里有的题：扰动 harness 构造的 `pf_*` 不在 ALL_CASES 里，它们不该被提议
    毕业（下次重跑是新生成的临时题），也不该被 --set 拒掉后污染输出。
    """
    seq: dict[str, list] = {}
    times = [_report_time(p) for p in paths]
    for i, p in enumerate(paths):
        for row in iter_rows(p):
            if row.id not in known:
                continue
            seq.setdefault(row.id, [None] * len(paths))[i] = row.correct
    return seq, times


def _release_key(path: str) -> tuple:
    """一份报告属于哪个 release = 它的 A 组配置指纹（agent / 记忆档 / 改写 / 词典 / 代码 / 题集）。

    取这六项而不是文件路径或日期：同配置跑十次还是一个 release，换一版代码才算下一个。

    没有 `code_sha12` 的老报告直接报错：那种报告分不清"同一配置重复跑"和"换了代码"，
    折错方向就会把噪声当连续性（2026-10-09 那批老报告连 fingerprints 块都没有）。
    """
    with open(path, encoding="utf-8") as f:
        fp = json.load(f).get("fingerprints") or {}
    if not fp.get("code_sha12"):
        raise ValueError(f"{os.path.basename(path)} 没有 fingerprints.code_sha12，"
                         f"分不清 release，不出提议")
    return (fp.get("agent"), fp.get("memory_mode"), fp.get("rewrite"), fp.get("use_dictionary"),
            fp.get("code_sha12"), fp.get("evalset_sha12"))


def cmd_check(args) -> int:
    ids = _case_ids()
    reg = R.load_registry(args.registry)
    problems = reg.problems(ids, doc_text=R.read_doc(args.doc))
    counts = reg.counts(ids)
    print(f"题库 {len(ids)} 题    registry {reg.path or '(未找到，按全 active 处理)'}")
    print("  状态计数：" + "  ".join(f"{s}={counts[s]}" for s in R.STATES))
    print(f"  registry_sha12={reg.sha12}    uniform={reg.uniform(ids)}")
    if counts["graduated"] or counts["retired"]:
        print("  ⚠ 能力集分母与全量题库不同：lifecycle.capability 才是能力口径，"
              "overall 不能与历史读数直接比")
    if problems:
        print(f"\n❌ {len(problems)} 个问题：")
        for p in problems:
            print(f"   - {p}")
        return 1
    print("\n✅ 状态机、幽灵条目、文档同步均无问题")
    return 0


def cmd_propose(args) -> int:
    ids = _case_ids()
    known = set(ids)
    reg = R.load_registry(args.registry)
    paths = list(args.propose)
    try:
        seq, times = _read_seq(paths, known)
    except Exception as e:                      # noqa: BLE001 —— 读不了报告就给一条可读的错
        print(f"✗ 读不了报告：{e}")
        return 1
    if len(paths) < R.RETIRE_STREAK:
        print(f"⚠ 只给了 {len(paths)} 份报告：毕业要 {R.GRADUATE_STREAK} 个 release、"
              f"退役要 {R.RETIRE_STREAK} 个，读数不够，不出提议")
        return 0
    try:
        keys = [_release_key(p) for p in paths]
    except (OSError, ValueError) as e:
        print(f"✗ {e}")
        return 1
    seq, sizes = R.group_releases(seq, keys)
    print(f"读入 {len(paths)} 份报告：{times[0]} → {times[-1]}")
    print(f"  折成 {len(sizes)} 个 release（连续同配置只算一个；每 release 跑数 {sizes}）")
    if len({k[:2] for k in keys}) > 1:
        # 只警告是不够的：实测把 off/state/full 三份消融报告喂进来，会吐出 17 条毕业提议，
        # 而警告浮在 17 条提议上面没人看。跨档位的"连续全对"不是 release 连续性。
        print("✗ 这几份报告的 agent/记忆档不同：那是消融实验，不是 release 序列。\n"
              "  跨档位的「连续全对」不构成毕业证据。要么按 release 分开喂，"
              "要么用 --flip 看单批稳定性")
        return 1
    if len(sizes) < R.RETIRE_STREAK:
        print("⚠ release 不够：同配置的重复跑不是多个 release（那种稳定性用 --flip 看）")
        return 0
    grad, retire = R.propose_transitions(seq, reg.state_of, len(sizes))
    skipped = [c for c in seq if reg.state_of(c) in ("graduated", "retired")]
    for title, items in (("毕业提议（能力集 → 回归集）", grad),
                         ("退役提议（不再计入任何口径）", retire)):
        print(f"\n{title}：{len(items)} 题")
        for p in items[:40]:
            print(f"  {p.case_id}   ← {p.why}")
            print(f"      python scripts/eval/registry.py --set {p.case_id}={p.target} "
                  f"--reason \"{p.why}\"")
        if len(items) > 40:
            print(f"  …另有 {len(items) - 40} 题")
    if not grad and not retire:
        print("\n没有提议：全部维持原状")
    if skipped:
        print(f"\n已毕业/已退役、跳过：{len(skipped)} 题（{' '.join(skipped[:10])}"
              + ("…" if len(skipped) > 10 else "") + "）")
    print("\n（只提议，不写文件。确认后自己跑 --set，并在 docs/eval/registry.md 补理由）")
    return 0


def cmd_flip(args) -> int:
    ids = _case_ids()
    known = set(ids)
    reg = R.load_registry(args.registry)
    paths = list(args.flip)
    try:
        seq, times = _read_seq(paths, known)
    except Exception as e:                      # noqa: BLE001
        print(f"✗ 读不了报告：{e}")
        return 1
    k = len(paths)
    if k < 2:
        print("✗ --flip 至少要 2 份报告（k<2 谈不了翻转）")
        return 1
    try:
        if len({_release_key(p) for p in paths}) > 1:
            print("⚠ 这几份报告的配置指纹不同（agent/记忆档/代码/题集…）：跨配置的 flip_rate "
                  "把「换了代码」和「判定不稳」混在一起，读数不可用")
    except (OSError, ValueError):
        # --flip 不折 release，只测这一批内部的翻转；老报告没有指纹时按"你给的就是同一配置"
        # 处理，只提示不拦——但 --propose 里必须拦，那里折错方向会把噪声当连续性。
        print("ℹ 报告缺 fingerprints，无法确认是不是同一配置：按你给的就是同一配置处理")
    print(f"读入 {k} 份报告（应当是同一配置的重复跑）：{times[0]} → {times[-1]}")
    rows = R.flip_candidates(seq, k, reg.state_of)
    bad = [(f, c, p) for f, c, p in rows if f > R.FLIP_MAX]
    print(f"可算 {len(rows)} 题；flip_rate > {R.FLIP_MAX} 的 {len(bad)} 题")
    for fr, cid, passes in bad[:40]:
        print(f"  {cid}  flip_rate={fr:.2f}  passes={passes}/{k}  当前状态={reg.state_of(cid)}")
        print(f"      python scripts/eval/registry.py --set {cid}=retired "
              f"--reason \"flip_rate {fr:.2f} > {R.FLIP_MAX}（{k} 跑 {passes} 对）\"")
    if not bad:
        print("  没有不稳定的题")
    steady = [c for f, c, p in rows if f == 0 and p == k]
    if steady:
        print(f"\n{k} 跑全对（稳定正确，可作为毕业的辅助证据）：{len(steady)} 题  "
              f"{' '.join(steady[:12])}" + ("…" if len(steady) > 12 else ""))
    print("\n（只提议，不写文件）")
    return 0


def cmd_set(args) -> int:
    spec = args.set or ""
    cid, sep, state = spec.partition("=")
    cid, state = cid.strip(), state.strip()
    if not sep or not cid or not state:
        print(f"✗ --set 要写成 ID=STATE，收到 {spec!r}")
        return 1
    if not (args.reason or "").strip():
        print("✗ --set 必须带 --reason：状态迁移没有理由，半年后没人知道为什么")
        return 1
    ids = _case_ids()
    if cid not in set(ids):
        print(f"✗ {cid} 不在题库里（幽灵条目）。改名/删题请先清理 registry.json")
        return 1
    reg = R.load_registry(args.registry)
    cur = reg.state_of(cid)
    err = R.check_transition(cur, state)
    if err:
        print(f"✗ {cid}: {err}")
        return 1
    at = args.at or _dt.date.today().isoformat()
    if len(at) != 10:
        print(f"✗ --at 要 YYYY-MM-DD，收到 {at!r}")
        return 1
    reg.apply(cid, state, args.reason, at)
    path = args.registry or R.REGISTRY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(reg.to_json(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✅ {cid}: {cur} → {state}（{at}）")
    print(f"   已写 {path}")
    print(f"   还要做：在 docs/eval/registry.md 补一行理由（--check 会校验 id 出现在文档里），"
          f"并在 DEVLOG 记一笔")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="题集生命周期：检查 / 提议 / 确认（EV-D3）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="校验状态机与文档同步；非法非 0 退出")
    g.add_argument("--propose", nargs="+", metavar="REPORT",
                   help="按时间顺序读报告，提议毕业/退役（只打印）")
    g.add_argument("--flip", nargs="+", metavar="REPORT",
                   help="同一配置的 k 次重复跑，按 flip_rate 提议退役（只打印）")
    g.add_argument("--set", metavar="ID=STATE", help="人工确认一次迁移（必须带 --reason）")
    ap.add_argument("--reason", default="", help="迁移理由（--set 必填）")
    ap.add_argument("--at", default="", help="迁移日期 YYYY-MM-DD（默认今天；补记历史用）")
    ap.add_argument("--registry", default=None, help="注册表路径（默认 docs/eval/registry.json）")
    ap.add_argument("--doc", default=None, help="文档路径（默认 docs/eval/registry.md）")
    args = ap.parse_args(argv)

    if args.check:
        return cmd_check(args)
    if args.propose:
        return cmd_propose(args)
    if args.flip:
        return cmd_flip(args)
    return cmd_set(args)


if __name__ == "__main__":
    sys.exit(main())
