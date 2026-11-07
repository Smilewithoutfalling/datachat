"""题集生命周期（EV-D3）：candidate → active → graduated / retired。

状态存在 `docs/eval/registry.json`（唯一真源），本模块只读 + 校验；写只有
`scripts/eval/registry.py --set` 一条路——**脚本只提议，人工确认**。自动毕业听起来
省事，但一次误判就把题从能力集里永久摘掉，而准确率分母变了没人看得出。

为什么不把状态塞进 `EvalCase`：201 条用例里绝大多数永远是 active，塞进去等于给每条加
一个恒等默认值；而且 diff 会散在 7 个 cases 文件里，"某题状态变过"这件事在 git history
里反而看不清。**未登记的题一律 active** —— 状态文件只记"偏离默认"的题。

状态机（对不上就报错，不猜）：

    candidate ──→ active ──→ graduated
        │            │            │
        └────────────┴────────────┴──→ retired
                                      └──→ active（误退的可恢复，必须写理由）

- candidate 不能直接毕业：没当过 active 就没有"连续 3 次 release"的读数。
- graduated 可以退回 active（例如题面被改过，历史读数作废）。
- retired 可以恢复 active（误退、或数据源修复后重新启用）。

三条硬约束：
  1. 只能沿 `LEGAL` 里的边移动；
  2. 每次移动必须有 reason，日期不早于上一次；
  3. 登记了不在题库里的 id = 幽灵条目——改名/删题时最容易漏，必须报错。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

STATES = ("candidate", "active", "graduated", "retired")
DEFAULT_STATE = "active"

# 图的边。别在这里加"捷径"：candidate → graduated 就是没读数就毕业。
LEGAL = {
    "candidate": ("active", "retired"),
    "active": ("graduated", "retired"),
    "graduated": ("active", "retired"),
    "retired": ("active",),
}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_PATH = os.path.join(ROOT, "docs", "eval", "registry.json")
DOC_PATH = os.path.join(ROOT, "docs", "eval", "registry.md")

# 规格给的门槛。改这里等于改"什么算稳定"，必须同步 docs/eval/registry.md。
GRADUATE_STREAK = 3     # 连续 3 个 release 全对 → 提议毕业
RETIRE_STREAK = 2       # 连续 2 个 release 都错 → 提议退役
FLIP_MAX = 0.4          # flip_rate > 0.4 → 提议退役（同一配置重复跑出来的不稳定）


def _sha12(obj) -> str:
    """状态文件内容的稳定哈希：按 key 排序、无空白，改格式不算改内容。"""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Registry:
    """一份解析好的注册表。`entries` 只含偏离默认状态的题。"""

    entries: dict = field(default_factory=dict)
    path: str = ""

    # ---------------------------------------------------------------- 读
    @property
    def sha12(self) -> str:
        return _sha12({k: v for k, v in self.entries.items()})

    def state_of(self, case_id: str) -> str:
        """未登记 = active。这是刻意的默认值，别改成 candidate——那会让 201 条题全部"未毕业"。"""
        e = self.entries.get(case_id)
        if not e:
            return DEFAULT_STATE
        hist = e.get("history") or []
        return hist[-1]["state"] if hist else DEFAULT_STATE

    def counts(self, case_ids) -> dict:
        out = {s: 0 for s in STATES}
        for cid in case_ids:
            out[self.state_of(cid)] += 1
        return out

    def split(self, case_ids) -> dict:
        """按生命周期切三组。

        capability = active + candidate（能力集，准确率的主口径）
        regression = graduated（仍跑，但只当回归，不计能力准确率）
        retired    = 退役（仍跑，历史可比；两份准确率都不算它）
        """
        out = {"capability": [], "regression": [], "retired": []}
        for cid in case_ids:
            s = self.state_of(cid)
            if s == "graduated":
                out["regression"].append(cid)
            elif s == "retired":
                out["retired"].append(cid)
            else:
                out["capability"].append(cid)
        return out

    def uniform(self, case_ids) -> bool:
        """全是 active = 分母与"全量题库"一致，历史读数可直接比。"""
        return all(self.state_of(c) == "active" for c in case_ids)

    # ---------------------------------------------------------------- 校验
    def problems(self, case_ids, doc_text: str | None = None) -> list[str]:
        """返回问题列表（空 = 合法）。case_ids 必须是当前题库的全部 id。"""
        known = set(case_ids)
        bad: list[str] = []
        for cid in sorted(self.entries):
            e = self.entries[cid]
            if cid not in known:
                bad.append(f"{cid}: 幽灵条目——题库里没有这道题（改名/删题后没清理？）")
                continue
            hist = e.get("history")
            if not isinstance(hist, list) or not hist:
                bad.append(f"{cid}: 没有 history（状态只能从历史推出来）")
                continue
            prev_state = prev_at = None
            for i, h in enumerate(hist):
                s = h.get("state")
                at = str(h.get("at") or "")
                why = str(h.get("reason") or "").strip()
                if s not in STATES:
                    bad.append(f"{cid}: history[{i}].state={s!r} 不是合法状态")
                    continue
                if len(at) != 10 or at[4] != "-" or at[7] != "-":
                    bad.append(f"{cid}: history[{i}].at={at!r} 不是 YYYY-MM-DD")
                if not why:
                    bad.append(f"{cid}: history[{i}] 缺 reason（每次移动都要写理由）")
                if prev_state is not None:
                    if s not in LEGAL[prev_state]:
                        bad.append(f"{cid}: 非法移动 {prev_state} → {s}")
                    if prev_at and at and at < prev_at:
                        bad.append(f"{cid}: history[{i}] 日期 {at} 早于上一次 {prev_at}")
                prev_state, prev_at = s, at or prev_at
            state = hist[-1].get("state")
            if state not in (None, "active") and doc_text is not None:
                # 规格要求"每次移动必须写 DEVLOG 与 registry.md 的理由"。
                # DEVLOG 没法机器校验（太自由），registry.md 能：id 必须出现。
                if cid not in doc_text:
                    bad.append(f"{cid}: 已 {state}，但 docs/eval/registry.md 里没写理由")
        return bad

    # ---------------------------------------------------------------- 写
    def apply(self, case_id: str, state: str, reason: str, at: str) -> None:
        """追加一次状态迁移。调用方负责先校验（见 `check_transition`）。"""
        e = self.entries.setdefault(case_id, {"history": []})
        e.setdefault("history", []).append({"state": state, "at": at, "reason": reason.strip()})

    def to_json(self) -> dict:
        return {
            "schema": 1,
            "_note": ("题集生命周期（EV-D3）。未登记的题一律 active，这里只记偏离默认的题。"
                      "用 scripts/eval/registry.py --set 修改，不要手改 history 的顺序。"),
            "cases": self.entries,
        }


def check_transition(cur: str, new: str) -> str | None:
    """能不能从 cur 走到 new。返回错误文案或 None。"""
    if new not in STATES:
        return f"{new!r} 不是合法状态（可选：{', '.join(STATES)}）"
    if cur == new:
        return f"已经是 {new}，没有移动可记"
    if new not in LEGAL[cur]:
        return f"非法移动 {cur} → {new}（{cur} 只能到 {'/'.join(LEGAL[cur])}）"
    return None


_CACHE: dict[tuple[str, float], Registry] = {}


def load_registry(path: str | None = None) -> Registry:
    """读注册表。文件不存在 = 全 active（新 clone 不该因为缺这个文件就跑不了）。

    按 (路径, mtime) 缓存：报告会在 summary() / fingerprint() 里各取一次，同一进程内
    重复读一个几十行的 JSON 不值得，但改了文件必须能看见。
    """
    p = path or REGISTRY_PATH
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        return Registry({}, p)
    if key in _CACHE:
        return _CACHE[key]
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 读坏了不能静默当"全 active"——那会让退役的题悄悄回到能力集里。
        # 解析失败原样抛出，由 --check / 报告入口报错。
        raise
    reg = Registry(data.get("cases") or {}, p)
    _CACHE[key] = reg
    return reg


def group_releases(seq: dict, keys: list) -> tuple[dict, list]:
    """把**连续且同配置**的报告折成一个 release。返回 ({case: [每 release 的判定]}, 每个 release 的跑数)。

    为什么要折：同一天、同一份代码重复跑 3 次，那是 3 次**重复测量**，不是 3 个 release。
    不折的话，"连续 3 个 release 全对"退化成"同一版代码跑 3 次都过"——21 题当天就能毕业，
    而它们一题都没跨过版本。重复跑的稳定性归 `--flip`，跨版本的连续性归这里。

    一个 release 内跑多次时，**必须全对才算这轮对**（"release 全对"的字面意思）；
    有错就是错；只有没判定（None）才算没读数。
    """
    groups: list[tuple] = []
    for i, k in enumerate(keys):
        if groups and groups[-1][0] == k:
            groups[-1][1].append(i)
        else:
            groups.append((k, [i]))
    out = {}
    for cid, vals in seq.items():
        per = []
        for _k, idx in groups:
            vs = [vals[i] for i in idx if i < len(vals)]
            if not vs or all(v is None for v in vs):
                per.append(None)
            elif any(v is False for v in vs):
                per.append(False)
            elif all(v is True for v in vs):
                per.append(True)
            else:                     # True 与 None 混着：这轮没跑全，不算读数
                per.append(None)
        out[cid] = per
    return out, [len(idx) for _k, idx in groups]


def read_doc(path: str | None = None) -> str:
    try:
        with open(path or DOC_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- 提议（纯函数，不写盘）

@dataclass
class Proposal:
    case_id: str
    target: str          # "graduated" | "retired"
    why: str


def _tail_all(seq: list, n: int) -> bool:
    """最近 n 个 release 全是 True。含 None 的窗口一律不算——"没判"不是"对了"。"""
    tail = seq[-n:]
    return len(tail) == n and all(x is True for x in tail)


def _tail_all_false(seq: list, n: int) -> bool:
    """最近 n 个 release 全是 False（明确判错）。"""
    tail = seq[-n:]
    return len(tail) == n and all(x is False for x in tail)


def propose_transitions(seq: dict, current_state, n_reports: int) -> tuple[list, list]:
    """按"跨 release 的连续性"提议迁移。返回 (毕业提议, 退役提议)，都不写盘。

    seq: {case_id: [correct_or_None, ...]}，按报告的时间顺序。
    规则（与 docs/eval/registry.md 一致）：连续 3 个 release 全对 → 毕业；
    连续 2 个 release 都错 → 退役；**退役优先**——[T,T,T,F,F] 这种"先对后错"是回归，
    不是该毕业的题。已毕业/已退役的题跳过（要改状态得显式 --set）。
    """
    grad, retire = [], []
    for cid in sorted(seq):
        cur = current_state(cid)
        if cur in ("graduated", "retired"):
            continue
        s = seq[cid]
        if _tail_all_false(s, RETIRE_STREAK):
            retire.append(Proposal(cid, "retired",
                                   f"连续 {RETIRE_STREAK} 个 release 都错（共 {len(s)} 个 release 有读数）"))
        elif _tail_all(s, GRADUATE_STREAK):
            grad.append(Proposal(cid, "graduated", f"连续 {GRADUATE_STREAK} 个 release 全对"))
    return grad, retire


def flip_candidates(seq: dict, k: int, current_state) -> list[tuple]:
    """同一配置重复跑的稳定性：返回 [(flip_rate, case_id, passes), ...]，按 flip 降序。

    只收 k 份报告里都出现过的题——有报告没跑它，k 对不齐，算出来是错的。
    flip_rate 的语义见 stats.flip_rate：任取两跑判定不一致的概率。
    """
    from app.eval.stats import flip_rate
    out = []
    for cid in sorted(seq):
        s = seq[cid]
        if len(s) != k or current_state(cid) == "retired":
            continue
        passes = sum(1 for x in s if x is True)
        out.append((flip_rate(passes, k), cid, passes))
    out.sort(reverse=True)
    return out
