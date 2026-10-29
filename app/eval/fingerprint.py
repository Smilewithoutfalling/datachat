"""评测可比性指纹（EV-A3）。

两批报告的分数差，只有在"模型实际看到的输入"和"打分规则"都一致时才有意义。现有
`report.evalset_fingerprint()` 只覆盖题面代码 + 数据文件 + 数据字典（report.py:125），
评分器 `app/eval/comparator.py` 不在其中——改一个容差就能让分数变化，而 `evalset.sha256`
一个字符都不动。所以这里补两层，分工明确：

1. `code_fingerprint()` —— `app/` 下全部 Python 源码，分两组：
   - A 组（影响模型输入或评分）：进 comparable 门禁
   - B 组（只产出报告 / 只做 HTTP）：只在报告里记录，不参与门禁
   分组穷尽由 `_assert_partition()` 强制：新增文件没归类就直接抛错，不会静默漏掉。
   取舍原则：**宁可误判"不可比"（代价是重跑一遍 baseline），不可误判"可比"（代价是
   拿两把不同的尺子算出的分数当趋势）。** 手写白名单漏文件是这个仓库已经犯过的错
   （`EVALSET_FILES` 漏了 comparator.py），所以用"必须归类"而不用"列了才算"。

2. `rendered_fingerprints()` —— 每题真正送进模型的 system prompt 的 sha256 前 12 位。
   取的是 `build_react_agent(out_system=...)` 吐出的**实际字符串**，不是复刻拼接逻辑：
   复刻会漂移，而漂移的指纹比没有指纹更坏（它替你撒谎）。

用途：诊断与稳定性证据，**不是豁免凭据**。eval-v0 的第一次重跑就证明了它不能当凭据：
判分器改了中文月份的认法，130 题渲染串逐字未变，分数 125→126。如果允许"渲染串相同即
可比"，那次重跑会被标成"等价可比"，+1 就成了"什么都没改却涨了"。
渲染哈希只覆盖 system prompt，模型在循环里看到的工具回传、评分规则、循环控制都不在里面——
它的证明力不足以支撑"输入等价"这个结论。所以门禁项一律不豁免，渲染串只用来解释差异、
以及验证同一 commit 两次重跑的稳定性。

workflow 路径不提供渲染指纹：codegen / reviewer 的 prompt 含上一步模型输出，不是事前可算的。
`rendered_fingerprints(agent="workflow")` 显式返回 `supported=False`，不假装有。
"""
import hashlib
import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_APP = os.path.join(_REPO, "app")

# A 组：影响"模型看到什么"或"怎么判对错"。进 comparable 门禁。
# 按前缀匹配，命中即算 A——目录级的粗粒度是故意的：漏一个模块的代价远大于多算一个。
_AFFECTS_RESULTS = (
    "app/react_agent.py",      # system prompt 内联在函数体里；工具描述、NUDGE 也在这
    "app/graph.py",            # workflow 的节点编排 = 跑什么
    "app/state.py",            # 节点间传的字段
    "app/llm.py",              # 模型构建
    "app/config.py",           # 目录 / 环境解析
    "app/core/",               # service 编排、result 格式化、llm 预算与错误分类
    "app/tools/",              # schema/dataset/dictionary/plotting = prompt 的全部来源；sandbox = 模型看到的结果
    "app/nodes/",              # workflow 的 4 个模板
    # 记忆（阶段 6.6）：context 拼出 memory_block 直接插进 system，working_state / snapshots 决定块内容，
    # budget 决定裁不裁、裁多少，config 决定开不开。四者任一改动都改模型输入。
    # 整目录吞掉，连 __init__.py 也算 A——它做 re-export，且这里宁可误判不可比。
    "app/memory/",
    # app/eval/cases*.py 由下面的前缀规则接管（题面变 = 换了卷子）
    "app/eval/case_model.py",  # 用例字段（ordered / percent_equiv / expect_refusal）
    "app/eval/comparator.py",  # 打分规则：容差、match_kind、拒答判定
    "app/eval/validate.py",    # 校验规则决定哪些用例能进评测；放宽一条等于换了题集
    "app/eval/stats.py",       # 报告里的区间与稳定性数字（pass^k / flip_rate）由它算，改它就是改读数
    # 执行器：决定"把什么当作历史喂给下一轮"。原来记在 B（理由写"不属于被测系统"），
    # 2026-10-29 被两次实测证伪：
    #   ① chat_model 建在轮次循环外 → 第 2 轮起不执行代码 → 13 条多轮题全部 executed=False；
    #   ② history 只传 (q, a) 不传 code → fold() 提不出筛选条件 → state_block 恒为空，
    #      评测里跑 state 只跑了一半，mul_013 因此把「研发部」丢成「全公司」。
    # 它改的是模型输入本身，不是读数方式，必须进 A。
    "app/eval/runner.py",
)

# 用例模块按前缀吞掉：新加 cases_memory.py 时不必回来改这张表。
# 漏一个用例文件的代价是"加了题但指纹不变"，比多认一个文件严重得多。
_AFFECTS_RESULTS_PREFIXES = ("app/eval/cases",)

# B 组：明确不影响分数。必须逐项写清理由，新增项请先想清楚再往里加。
_EXEMPT = {
    "app/__init__.py": "包标记，无逻辑",
    "app/eval/__init__.py": "包标记，无逻辑",
    "app/eval/report.py": "只产出报告 JSON，不回灌模型",
    "app/eval/rescore.py": "离线重打分工具",
    "app/eval/chart_smoke.py": "图表统计，只看已产出的图",
    "app/eval/fingerprint.py": "本文件",
    "app/sidecar.py": "桌面端 sidecar 入口",
}
_EXEMPT_PREFIXES = {
    "app/server/": "HTTP / 会话存储层，评测不经它",
}


def _group(rel: str) -> str | None:
    """返回 'A' / 'B' / None（未归类）。A 优先：一个文件同时命中两组时算 A。"""
    for p in _AFFECTS_RESULTS:
        if rel == p or (p.endswith("/") and rel.startswith(p)):
            return "A"
    for p in _AFFECTS_RESULTS_PREFIXES:
        if rel.startswith(p) and rel.endswith(".py"):
            return "A"
    if rel in _EXEMPT:
        return "B"
    for p in _EXEMPT_PREFIXES:
        if rel.startswith(p):
            return "B"
    return None


def _app_sources() -> list[str]:
    """app/ 下全部 .py 的相对路径（正斜杠），排序后返回。"""
    out = []
    for root, _dirs, files in os.walk(_APP):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                full = os.path.join(root, f)
                out.append(os.path.relpath(full, _REPO).replace(os.sep, "/"))
    return sorted(out)


def _assert_partition(files: list[str]) -> None:
    """每个源文件都必须归到 A 或 B。新增文件没归类 → 抛错，逼作者想清楚它影响不影响分数。"""
    unknown = [f for f in files if _group(f) is None]
    if unknown:
        raise AssertionError(
            "app/eval/fingerprint.py 的分区缺了新文件，请归到 _AFFECTS_RESULTS（影响分数）"
            "或 _EXEMPT（不影响），并写清理由：\n  " + "\n  ".join(unknown)
        )


def _sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def code_fingerprint() -> dict:
    """代码指纹。

    affects_results_sha256 —— 只算 A 组，进 comparable 门禁
    sha256                —— 全量，仅记录（看 B 组有没有动，用于排查报告差异）
    files                 —— 每个文件的 sha12 与分组
    """
    files = _app_sources()
    _assert_partition(files)
    h_all, h_a, parts = hashlib.sha256(), hashlib.sha256(), {}
    for rel in files:
        with open(os.path.join(_REPO, rel), "rb") as fh:
            data = fh.read().replace(b"\r\n", b"\n")   # 与 evalset_fingerprint 一致：Windows/Linux 同值
        g = _group(rel)
        parts[rel] = {"sha12": _sha12(data), "group": g}
        h_all.update(rel.encode() + b"\0" + data + b"\0")
        if g == "A":
            h_a.update(rel.encode() + b"\0" + data + b"\0")
    return {"sha256": h_all.hexdigest()[:12], "affects_results_sha256": h_a.hexdigest()[:12],
            "files": parts}


# ------------------------------------------------------------------ 运行时配置

def _env_flag(name: str, default: str = "off") -> str:
    """环境变量开关归一成 on/off；认不出的值原样保留（原样才能被比较，而不是被抹平成 off）。"""
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    if v in ("1", "true", "yes", "on"):
        return "on"
    if v in ("0", "false", "no", "off"):
        return "off"
    return v


def memory_mode() -> str:
    """本轮实际生效的记忆模式。

    记忆系统落地后由 app/memory/config.py 的 resolve_memory_mode() 给（env → settings → off，
    见 memory-system-spec.md §3.7）；现在还没有这个模块，行为等价于 off。
    两者都取不到时返回 "unknown"——comparable 遇到 unknown 一律判不可比，不猜。
    """
    try:
        from app.memory.config import resolve_memory_mode
    except ImportError:
        return "off"
    try:
        return resolve_memory_mode() or "unknown"
    except Exception:  # noqa: BLE001  读 settings 失败（没有库、库坏了）不该让评测崩
        return "unknown"


def runtime_config() -> dict:
    """影响输入或评分的运行时开关。报告必须记这里的值，不能记环境变量原值。"""
    return {"memory_mode": memory_mode(), "rewrite": _env_flag("DATACHAT_REWRITE")}


# ------------------------------------------------------------------ 渲染后的 prompt

class _NoModel:
    """只让 build_react_agent 走完构造流程，不会被调用。"""

    def bind_tools(self, tools):
        return self


def render_system(case, datasets: dict, frame_cache: dict | None = None,
                  use_dictionary: bool = True) -> str:
    """渲染一条用例的 system prompt（react 路径），返回原字符串。

    走 build_react_agent 的真实拼接，field_notes 走 service.analyze 同一条检索链路
    （retrieve_notes + format_notes），只是把"读数据 + 检索 + 拼接"三步搬到这里，
    参数与 service.py:181-193 一一对应。use_dictionary=False 时和 --no-dict 一样不带字典块，
    否则指纹会描述一个实际没发生的输入。
    """
    from app.react_agent import build_react_agent
    from app.tools.dataset import load_data
    from app.tools.dictionary import format_notes, load_retriever, retrieve_notes

    cache = frame_cache if frame_cache is not None else {}
    name = getattr(case, "dataset", "sales")
    path = datasets[name]
    if name not in cache:
        data, _desc = load_data(path)
        retr = load_retriever(path)
        cache[name] = (data, retr)
    data, retr = cache[name]

    notes = retrieve_notes(case.question, retr) if use_dictionary else []
    notes_text = format_notes(notes) if notes else ""
    cap: dict = {}
    build_react_agent(path, model=_NoModel(), df=data, field_notes=notes_text, out_system=cap)
    return cap["system"]


def rendered_fingerprints(cases=None, datasets=None, agent: str = "react",
                          use_dictionary: bool = True) -> dict:
    """每题渲染后的 system prompt 指纹。

    返回 {"supported": True, "per_case": {id: {"sha12","len"}}, "set_sha12": ...}
    set_sha12 是"逐题 sha12 排序后"的汇总——一个字段判断整批是否完全等价。
    非 react 路径返回 {"supported": False, "reason": ...}，不掺假。
    """
    if agent != "react":
        return {"supported": False,
                "reason": f"agent={agent!r} 的 prompt 含上一步模型输出，不是事前可算的；该路径只走代码门禁"}
    from app.eval.cases import ALL_CASES, DATASETS
    cases = cases if cases is not None else ALL_CASES
    datasets = datasets if datasets is not None else DATASETS

    cache: dict = {}
    per_case, h = {}, hashlib.sha256()
    for c in cases:
        system = render_system(c, datasets, cache, use_dictionary=use_dictionary)
        b = system.encode("utf-8")
        per_case[c.id] = {"sha12": _sha12(b), "len": len(b)}
        h.update(c.id.encode() + b"\0" + b + b"\0")
    return {"supported": True, "per_case": per_case, "set_sha12": h.hexdigest()[:12]}


# ------------------------------------------------------------------ 可比性判定

GATE_KEYS = ("agent", "memory_mode", "rewrite", "use_dictionary", "evalset_sha12", "code_sha12")

# 曾经有过一条"渲染串相同就豁免 code_sha12"的通道，eval-v0 的第一次重跑证明它是错的：
# 判分器认了中文月份（comparator.py 改了），130 题的渲染串逐字未变，分数从 125 变 126。
# 若允许豁免，这次重跑会被判成"等价可比"，那 +1 就会被当成"什么都没改却涨了"。
# 根因是渲染哈希的证明力被高估了：它只覆盖 system prompt，而模型在循环里看到的工具回传、
# 评分规则、循环控制都不在它里面。所以门禁项一个都不豁免——宁可误判不可比（重跑一次），
# 不可误判可比（拿两把尺子算趋势）。渲染串保留为诊断与稳定性证据，不再当豁免凭据。


def _is_unknown(v) -> bool:
    """取不到的值记 unknown（如 memory_mode 在没有 settings 也没有 env 时）。
    unknown 与任何值都不可比——包括另一个 unknown：两个"不知道"不代表配置相同。"""
    return v is None or v == "unknown"


def comparable(now: dict, before: dict) -> dict:
    """比较两批的指纹，返回判定结果。

    now / before: {"agent","memory_mode","rewrite","use_dictionary","evalset_sha12",
                   "code_sha12","rendered_set_sha12"（可选，只用于诊断）}

    判定：
    - 有取不到的项（None / "unknown"）→ 不可比（basis=unknown）
    - 门禁字段全等 → 可比（basis=gate）
    - 任一门禁字段不等 → 不可比（basis=gate），列出差异项

    rendered_set_sha12 不参与判定，只在结论里带上 `rendered_equal`：
    它相同而门禁不同，恰恰是最危险的情况——看着"输入没变"，其实尺子或循环变了。
    """
    missing = [k for k in GATE_KEYS if _is_unknown(now.get(k)) or _is_unknown(before.get(k))]
    diffs = [k for k in GATE_KEYS if now.get(k) != before.get(k)]
    if missing:
        return {"comparable": False, "basis": "unknown",
                "diffs": sorted(set(diffs) | set(missing)),
                "note": "有门禁项取不到值，无法判定可比"}
    if not diffs:
        return {"comparable": True, "basis": "gate", "diffs": []}
    r_now, r_before = now.get("rendered_set_sha12"), before.get("rendered_set_sha12")
    out = {"comparable": False, "basis": "gate", "diffs": diffs,
           "rendered_equal": bool(r_now and r_before and r_now == r_before)}
    if out["rendered_equal"]:
        out["note"] = ("逐题渲染串相同但代码不同，仍判不可比：渲染串只覆盖 system prompt，"
                       "评分器、循环、工具回传都可能变了")
    return out
