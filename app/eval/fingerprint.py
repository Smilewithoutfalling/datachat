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
    # 负向题判据（EV-B7）：refusal / clarify / impossible 三类的通过条件。
    # 归 A 不是"它读了模型输出"这么简单 —— 放宽一条（比如 clarify 允许已执行代码）
    # 会让同一份回答从判错变判对，那正是 A 组的定义。
    "app/eval/negative.py",
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
    # 把逐题行折成严格率 / 区间 / MDE。和 report.py 同一层：只读 `correct` 与
    # `match`，不产生任何判定。放进 A 会让"加一个汇总模块"就报废全部历史报告的
    # 可比性，而它根本改不动任何一题的判定 —— 那是 comparator 的事。
    "app/eval/outcome.py": "报告汇总，不产生判定",
    # 成本与延迟（tokens / 秒数的 p50、p95、每正确回答 token）。只读逐题行里已有的
    # 数字，既不产生判定也不进模型输入。放进 A 等于"改个分位数算法就报废全部历史报告"。
    "app/eval/cost.py": "成本汇总，不产生判定",
    # 读报告、把两套格式归一成同一种行。**只读不写**：判定字段的取值优先级
    # （human_correct → auto_correct → correct）是对已有字段的解释，不是新判定 ——
    # 它没有能力把一道判错的题变成判对的。改了它，同一份 JSON 读出来的 `correct`
    # 可能变（比如优先级写反），但那也只是"读错了旧报告"，不会改变任何一次
    # 模型运行的结果；而 code_sha12 的用途是"这次跑的和上次跑的是不是同一个东西"。
    "app/eval/report_adapter.py": "报告读取适配，只解释字段不产生判定",
    # 五段式 Markdown 渲染。纯输出层，连报告 JSON 都不产出。
    "app/eval/report_md.py": "报告渲染，纯输出",
    "app/eval/rescore.py": "离线重打分工具",
    "app/eval/chart_smoke.py": "图表统计，只看已产出的图",
    "app/eval/fingerprint.py": "本文件",
    # canary 只是十条题的 id 列表 + 题面哈希，不参与判分、不进模型输入。
    # 它决定"跑哪十条"，与 run_eval.py 的 --case 同级；那类选题目前不在扫描范围内（缺口 4）。
    # 改这个列表 = 换了探针本身，由 canary_fingerprint() 单独记录，不混进 code_sha12。
    "app/eval/canary.py": "探针清单，不改输入也不改判分；自身哈希另记",
    # 缺口 11 / 12 的归因：`result` 是算出来的还是写死的、没交卷的具体原因。
    # **只往报告里写两个字段，不参与 score_detail，也不进模型输入。** 改它不改任何一题的对错，
    # 所以放 B；但读数的人要能看出"这批 literal 变多了"，那由报告里的分布字段自证。
    "app/eval/provenance.py": "答案来源归因，只记录不判分，不进模型输入",
    # E2 过程验证：AST 看代码写法（有没有引用 Unnamed 列名、result 是不是占位符文本）。
    # **只往报告里写 `process_risks`，不进 score_detail、不进模型输入、也不判对错**——
    # 它标的是"值得人看一眼"，标了不等于错（见模块 docstring 的实测数字）。所以放 B。
    "app/eval/process_check.py": "过程结构标记，只记录不判分，不回灌模型",
    # 出境审计（EV-B10）：只把"模型实际收到的 prompt"抓出来做四条合同断言。
    # **只读**——不产生判定、不进模型输入、不写报告字段。改它不会让任何一题从错变对，
    # 也不会改变任何一次运行的输入；它连 analyze 的返回结果都只是拿来看 executed 的。
    "app/eval/egress.py": "出境审计，只读 prompt，不产生判定也不进模型输入",
    # 证据一致性（EV-B4）：对 analyze 的返回结果做三条断言（答案↔结果/图↔结果/时间词↔代码）。
    # **只读 res，不碰执行路径**——runner 在打分之后才调它，failures 只作 warnings 展示、
    # 升级门槛（130 题误报率 <10%）达成前不改 correct。改它不会改变任何一次运行的输入与结果。
    "app/eval/consistency.py": "证据一致性，只读 res 的 warnings 检查，不改判分",
    # 失败归因常量表（EV-D2）：码 → 模块/修复方向的映射，只被离线 triage 脚本读。
    # **不进模型输入、不参与判分、不写报告字段**——改它不会让任何一题从错变对。
    # 但它是"归因口径"的一部分：triage 的结论会变，所以改动要在 DEVLOG 里留痕。
    "app/eval/failure_classes.py": "失败归因常量表，只被离线 triage 读取，不改判分",
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


# ------------------------------------------------------------------ 启动快照（缺口 15）

# `EvalReport.fingerprint()` 是惰性的，且缓存挂在**实例**上。`--repeat 3` 每轮新建一个
# EvalReport，就各自重算一次指纹。于是「跑批期间改了 A 组文件」会让第 2、3 轮的报告标上
# 一个**从没执行过**的指纹——报告声称"我是用这份尺子量的"，其实不是。
#
# 2026-10-30 的 state 三跑撞上了：三份报告都记 `db1b660e8afc`，而实际执行的是
# `d617102729fa`（改动落在第 1 轮跑完之后）。判据是 `result_origins` 全为 None ——
# 那份代码会填这个字段，报告里却没有，说明它没跑过。当时的处置是在台账里按实际值
# 硬改（`eval_ledger._CODE_SHA_OVERRIDE`），根治要先把这个采样时机改掉。
#
# 修法：入口在**开跑之前**快照一次，此后进程内所有报告都用这一份。
# 语义边界：「快照」代表这批跑在哪份代码上，一旦建立就不该刷新。中途改了代码，
# 报告仍然记旧的——那正是事实（这批确实跑在旧代码上）；差异下次跑批自然会暴露。
_CODE_SNAPSHOT: dict | None = None


def snapshot_code_fingerprint() -> dict:
    """在跑批开始前快照一次，返回该快照。幂等：重复调用返回同一份，不会刷新。

    调用点只有一个：`run_eval.py` 的 main，在确定要跑模型之后、第一轮之前。
    """
    global _CODE_SNAPSHOT
    if _CODE_SNAPSHOT is None:
        _CODE_SNAPSHOT = code_fingerprint()
    return _CODE_SNAPSHOT


def reset_code_snapshot() -> None:
    """丢掉快照。只给测试用——生产代码一旦建立快照就不该撤销。"""
    global _CODE_SNAPSHOT
    _CODE_SNAPSHOT = None


def report_code_fingerprint() -> dict:
    """报告写指纹时走这里：有快照用快照，没快照现算。

    没快照不等于出错：单测、REPL、别处直接构造 EvalReport 时本来就没有"跑批起点"。
    那种情况下现算与刚启动是同一份，因为中间没人改代码。
    """
    return _CODE_SNAPSHOT if _CODE_SNAPSHOT is not None else code_fingerprint()


# ------------------------------------------------------------------ 入口脚本（缺口 4）

# `run_eval.py` 在仓库根目录，不在 `app/` 下，所以 `code_fingerprint()` 扫不到它。
# 但它决定三件影响读数的事：①选题（--filter/--case/--canary 的解析与顺序）；
# ②`--repeat` 的逐题收集，pass^k / flip_rate 全从这里来；③`--oracle` 走哪条假模型路径。
# 改它同样改读数，而 `code_sha12` 一个字符都不动。
#
# **2026-11-02 先进报告、不进 GATE_KEYS。** 加门禁会让所有历史报告失配（它们的
# `fingerprints` 里没有这个键 → comparable 判 unknown → 全部不可比），
# 要把 `baselines.json` 每个基线补上对应 commit 的入口哈希才能改，那是单独一步。
# 在那之前先把值记下来：至少能回答"两批分数差是不是因为换了入口脚本"。
_ENTRY_FILES = ("run_eval.py",)


def entry_fingerprint() -> dict:
    """评测入口脚本的指纹。扫不到文件时该项记 None，不假装有。"""
    parts, h = {}, hashlib.sha256()
    for rel in _ENTRY_FILES:
        try:
            with open(os.path.join(_REPO, rel), "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
        except OSError:
            parts[rel] = None
            continue
        parts[rel] = _sha12(data)
        h.update(rel.encode() + b"\0" + data + b"\0")
    return {"sha12": h.hexdigest()[:12], "files": parts}


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
    # 扰动题（EV-B6）的 dataset 是绝对路径，不在 DATASETS 里 —— 直接当路径用
    path = datasets.get(name, name)
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
