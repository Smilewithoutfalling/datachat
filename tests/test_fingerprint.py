"""可比性指纹（EV-A3）的测试。

核心回归：`evalset_fingerprint()` 覆盖不到 `app/eval/comparator.py`——改一个容差就能让分数
变化而"评测集指纹"毫无反应。`code_fingerprint()` 必须抓住它。
"""
import pytest

from app.eval import fingerprint as fp


def _make_repo(tmp_path, files: dict):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _point_at(monkeypatch, root):
    monkeypatch.setattr(fp, "_REPO", str(root))
    monkeypatch.setattr(fp, "_APP", str(root / "app"))


@pytest.fixture(autouse=True)
def _clear_code_snapshot():
    """快照是模块级全局，测试之间必须清干净。

    一个测试建立的快照会漏到下一个测试（pytest 同进程），下一个测试改了自己的假仓库
    却读到上一个的指纹 —— 那种失败看起来像逻辑错，实际是测试隔离没做。
    """
    fp.reset_code_snapshot()
    yield
    fp.reset_code_snapshot()


# ---------------------------------------------------------------- 分区

def test_real_repo_partition_covers_every_file():
    f = fp.code_fingerprint()
    assert all(v["group"] in ("A", "B") for v in f["files"].values())
    assert f["files"]["app/eval/comparator.py"]["group"] == "A"   # 评分器：本轮的修复对象
    assert f["files"]["app/react_agent.py"]["group"] == "A"       # 内联 system prompt
    assert f["files"]["app/tools/schema.py"]["group"] == "A"
    assert f["files"]["app/eval/report.py"]["group"] == "B"
    assert f["files"]["app/server/app.py"]["group"] == "B"
    assert f["affects_results_sha256"] != f["sha256"]              # 两组哈希不是同一个值


def test_unclassified_file_raises(tmp_path, monkeypatch):
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "x=1\n", "app/brand_new.py": "y=1\n"})
    _point_at(monkeypatch, root)
    with pytest.raises(AssertionError, match="brand_new.py"):
        fp.code_fingerprint()


def test_memory_dir_is_gated_before_it_lands(tmp_path, monkeypatch):
    """记忆模块（阶段 6.6）在落地前就登记成 A 组。

    它决定 `memory_block` 的内容——context 拼块、working_state / snapshots 决定块里写什么、
    budget 决定裁不裁、config 决定开不开。改任一文件都改模型输入，必须动门禁。

    这条测试故意不依赖 `app/memory/` 真的存在（批 1 之前分支上没有这个目录）：
    等目录出现再想起来登记，`_assert_partition` 会在 rebase 中途抛错，那时修的成本比现在高。
    """
    for rel in ("app/memory/__init__.py", "app/memory/config.py", "app/memory/context.py",
                "app/memory/budget.py", "app/memory/working_state.py",
                "app/memory/snapshots.py"):
        assert fp._group(rel) == "A", rel

    # 真的放进仓库时不能再被判成未归类
    root = _make_repo(tmp_path, {"app/memory/config.py": "MODE = 'off'\n",
                                 "app/eval/comparator.py": "x = 1\n"})
    _point_at(monkeypatch, root)
    f = fp.code_fingerprint()
    assert f["files"]["app/memory/config.py"]["group"] == "A"


def test_memory_adjacent_server_files_stay_b():
    """`app/server/retention.py`（#90 新增）是落库与定期清理，评测不经它，前缀已覆盖成 B。

    记忆写的话题容易让人顺手把它也拉进 A；它不影响任何一次 analyze() 的输入，别加例外。
    """
    assert fp._group("app/server/retention.py") == "B"


def test_eval_runner_is_gated():
    """执行器在 A 组。它决定「把什么当作历史喂给下一轮」，改它就是改模型输入。

    原来记在 B，理由写「评测执行器，不属于被测系统」。2026-10-29 被两次实测证伪：
    ① `chat_model` 建在轮次循环外 → 第 2 轮起不执行代码 → 13 条多轮题全部 executed=False；
    ② `history` 只传 (q, a) 不传 code → `fold()` 提不出筛选条件 → `state_block` 恒为空，
       评测里跑 state 只跑了一半，mul_013 因此把「研发部」丢成「全公司」。
    两次改动都只动 runner.py 一行，都直接改了读数。
    """
    assert fp._group("app/eval/runner.py") == "A"


def test_runner_change_moves_gate(tmp_path, monkeypatch):
    """runner.py 改一个字符就要动门禁哈希——这是上一条的落地验证。"""
    base = {"app/eval/runner.py": "X = 1\n", "app/eval/report.py": "r = 1\n"}
    root = _make_repo(tmp_path, base)
    _point_at(monkeypatch, root)
    before = fp.code_fingerprint()["affects_results_sha256"]
    _make_repo(tmp_path, {**base, "app/eval/runner.py": "X = 2\n"})
    _point_at(monkeypatch, root)
    assert fp.code_fingerprint()["affects_results_sha256"] != before


# ---------------------------------------------------------------- 敏感度

def test_scorer_change_moves_gate(tmp_path, monkeypatch):
    """改 comparator 的容差必须让门禁哈希变——evalset 指纹做不到这件事。"""
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "TOL = 1e-4\n",
                                 "app/eval/report.py": "x = 1\n"})
    _point_at(monkeypatch, root)
    before = fp.code_fingerprint()["affects_results_sha256"]
    (root / "app/eval" / "comparator.py").write_text("TOL = 1e-2\n", encoding="utf-8")
    assert fp.code_fingerprint()["affects_results_sha256"] != before


def test_b_group_change_does_not_move_gate(tmp_path, monkeypatch):
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "x=1\n", "app/eval/report.py": "b=1\n"})
    _point_at(monkeypatch, root)
    base = fp.code_fingerprint()
    (root / "app/eval" / "report.py").write_text("b = 2\n", encoding="utf-8")
    after = fp.code_fingerprint()
    assert after["affects_results_sha256"] == base["affects_results_sha256"]   # 只出报告，不影响分数
    assert after["sha256"] != base["sha256"]                                   # 但全量哈希记录到了


def test_crlf_and_lf_same_fingerprint(tmp_path, monkeypatch):
    # 必须用 write_bytes：write_text 在 Windows 会把 \n 再转一次，造不出真正的 CRLF 文件
    p = tmp_path / "app" / "eval" / "comparator.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a = 1\r\nb = 2\r\n")
    _point_at(monkeypatch, tmp_path)
    crlf = fp.code_fingerprint()
    p.write_bytes(b"a = 1\nb = 2\n")
    assert fp.code_fingerprint()["affects_results_sha256"] == crlf["affects_results_sha256"]


# ---------------------------------------------------------------- 渲染指纹

def test_render_system_is_stable_and_nonempty():
    from app.eval.cases import ALL_CASES, DATASETS
    case = ALL_CASES[0]
    a = fp.render_system(case, DATASETS, {})
    b = fp.render_system(case, DATASETS, {})
    assert a == b
    assert "数据表结构" in a and "run_python_on_data" in a


def test_rendered_fingerprint_set_is_deterministic():
    from app.eval.cases import ALL_CASES, DATASETS
    cases = ALL_CASES[:5]
    a = fp.rendered_fingerprints(cases, DATASETS)
    b = fp.rendered_fingerprints(cases, DATASETS)
    assert a["supported"] is True
    assert a["set_sha12"] == b["set_sha12"]
    assert set(a["per_case"]) == {c.id for c in cases}


def test_render_without_dictionary_says_none():
    """--no-dict 的跑批必须算出"不带字典"的指纹，否则指纹描述的是一个没发生过的输入。"""
    from app.eval.cases import ALL_CASES, DATASETS
    case = ALL_CASES[0]
    with_dict = fp.render_system(case, DATASETS, {}, use_dictionary=True)
    without = fp.render_system(case, DATASETS, {}, use_dictionary=False)
    assert with_dict != without
    assert "字段说明（来自数据字典）：\n（无）" in without


def test_workflow_render_not_supported():
    r = fp.rendered_fingerprints(agent="workflow")
    assert r["supported"] is False and "workflow" in r["reason"]


# ---------------------------------------------------------------- 运行时配置

def test_runtime_config_defaults(monkeypatch):
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)
    cfg = fp.runtime_config()
    assert cfg["rewrite"] == "off"
    assert cfg["memory_mode"] in ("off", "unknown")   # 记忆系统未落地时是 off


def test_env_flag_normalizes(monkeypatch):
    monkeypatch.setenv("DATACHAT_REWRITE", " TRUE ")
    assert fp.runtime_config()["rewrite"] == "on"
    monkeypatch.setenv("DATACHAT_REWRITE", "weird-value")
    assert fp.runtime_config()["rewrite"] == "weird-value"   # 认不出的值原样保留，不抹平成 off


def test_memory_mode_uses_resolver_when_present(monkeypatch):
    """记忆系统给出 resolve_memory_mode() 后，报告记的是它解析出来的生效值。"""
    import sys
    import types

    pkg = types.ModuleType("app.memory")
    mod = types.ModuleType("app.memory.config")
    pkg.config = mod
    monkeypatch.setitem(sys.modules, "app.memory", pkg)
    monkeypatch.setitem(sys.modules, "app.memory.config", mod)

    mod.resolve_memory_mode = lambda: "state"
    assert fp.memory_mode() == "state"

    def boom():
        raise RuntimeError("no db")
    mod.resolve_memory_mode = boom
    assert fp.memory_mode() == "unknown"    # 读不到就 unknown，不猜 off


# ---------------------------------------------------------------- 可比性判定

BASE = {"agent": "react", "memory_mode": "off", "rewrite": "0", "use_dictionary": True,
        "evalset_sha12": "bbb", "code_sha12": "aaa", "rendered_set_sha12": "ccc"}


def test_comparable_when_gate_equal():
    r = fp.comparable(dict(BASE), dict(BASE))
    assert r == {"comparable": True, "basis": "gate", "diffs": []}


def test_rendered_equal_does_not_rescue_code_change():
    """渲染串相同不能豁免 code_sha12 的差异。

    反例是 eval-v0 第一次重跑：comparator.py 补了中文月份的认法，130 题渲染串
    （6b23655c28a6）逐字未变，分数 125→126。若按"渲染相同即可比"判，那 +1 会被
    读成"代码变了但什么都没影响"，而实际是尺子修了一条。
    """
    now = dict(BASE, code_sha12="zzz")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is False and r["basis"] == "gate"
    assert r["diffs"] == ["code_sha12"]
    assert r["rendered_equal"] is True          # 差异原因要写清，但不改变判定
    assert "渲染串只覆盖 system prompt" in r["note"]


def test_not_comparable_when_rendered_differs():
    now = dict(BASE, code_sha12="zzz", rendered_set_sha12="ddd")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is False
    assert "code_sha12" in r["diffs"]


def test_not_comparable_without_fingerprint():
    """老报告（31 份历史报告）没有任何指纹字段，不能被当成可比。"""
    assert fp.comparable(dict(BASE), {"agent": "react"})["comparable"] is False


def test_memory_mode_change_blocks_comparison():
    """记忆系统落地后 memory_mode 从 off 变 state，必须判不可比——渲染串可能没变，
    但上下文组装变了，分数不再和旧 baseline 同一把尺子。"""
    now = dict(BASE, memory_mode="state")
    assert fp.comparable(now, dict(BASE))["comparable"] is False


def test_unknown_mode_blocks_even_against_unknown():
    """取不到 memory_mode 时两个 unknown 也不能判可比：两个"不知道"不等于配置相同。"""
    a = dict(BASE, memory_mode="unknown")
    r = fp.comparable(dict(a), a)
    assert r["comparable"] is False and r["basis"] == "unknown"


def test_evalset_change_not_exempted_by_rendered():
    """期望值改了但题面和数据没变时，渲染串一样；这不能算可比——尺子的刻度变了。"""
    now = dict(BASE, evalset_sha12="zzz")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is False and r["diffs"] == ["evalset_sha12"]


def test_report_emits_fingerprints_and_null_comparable():
    from app.eval.cases import ALL_CASES
    from app.eval.report import EvalReport

    case = ALL_CASES[0]
    results = [{"case": case, "agent": "react", "correct": True, "executed": True}]
    rep = EvalReport(results, meta={"use_dictionary": True, "memory_mode": "off", "rewrite": "0"})
    s = rep.summary()
    f = s["fingerprints"]
    assert set(f) >= {"agent", "memory_mode", "rewrite", "use_dictionary",
                      "evalset_sha12", "code_sha12", "rendered_set_sha12", "rendered"}
    assert f["agent"] == "react" and f["memory_mode"] == "off"
    assert f["evalset_sha12"] == s["evalset"]["sha256"]
    assert f["rendered_set_sha12"] and f["rendered"]["supported"] is True
    assert s["comparable"] is None            # 没给 --baseline

    # 给一个空基准：必须判不可比，而不是当成可比（复用已算好的指纹，不再渲一遍 130 题）
    rep.baseline = {}
    assert rep.summary()["comparable"]["comparable"] is False


# ---------------------------------------------------------------- 启动快照（缺口 15）

def test_snapshot_freezes_against_later_file_changes(tmp_path, monkeypatch):
    """快照之后改 A 组文件，报告取的仍是快照值 —— 缺口 15 的核心断言。

    不修的话：`EvalReport.fingerprint()` 惰性求值且缓存挂在实例上，`--repeat 3`
    每轮新建一个实例就各自重算。第 2、3 轮会把"跑完之后"的代码标成"跑的时候用的代码"，
    报告等于谎称自己是用那把尺子量的。2026-10-30 的 state 三跑就是这样：
    三份报告记 `db1b660e8afc`，实际执行的是 `d617102729fa`。
    """
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "TOL = 1e-4\n"})
    _point_at(monkeypatch, root)
    snap = fp.snapshot_code_fingerprint()

    (root / "app" / "eval" / "comparator.py").write_text("TOL = 1e-2\n", encoding="utf-8")

    # 实时算能看见改动，报告用的快照看不见 —— 两者必须分开，不然修了等于没修
    assert fp.code_fingerprint()["affects_results_sha256"] != snap["affects_results_sha256"]
    assert fp.report_code_fingerprint()["affects_results_sha256"] == snap["affects_results_sha256"]


def test_snapshot_is_idempotent(tmp_path, monkeypatch):
    """重复调用返回同一份，不刷新 —— 快照一旦建立就代表"这批跑在哪份代码上"。"""
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "A = 1\n"})
    _point_at(monkeypatch, root)
    first = fp.snapshot_code_fingerprint()
    (root / "app" / "eval" / "comparator.py").write_text("A = 2\n", encoding="utf-8")
    assert fp.snapshot_code_fingerprint() == first


def test_reset_lets_next_snapshot_see_new_code(tmp_path, monkeypatch):
    """reset 之后重新快照能读到新代码。reset 只给测试用，但语义必须对。"""
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "A = 1\n"})
    _point_at(monkeypatch, root)
    before = fp.snapshot_code_fingerprint()["affects_results_sha256"]
    fp.reset_code_snapshot()
    (root / "app" / "eval" / "comparator.py").write_text("A = 2\n", encoding="utf-8")
    assert fp.snapshot_code_fingerprint()["affects_results_sha256"] != before


def test_no_snapshot_falls_back_to_live(tmp_path, monkeypatch):
    """没有快照时现算 —— 单测/REPL 里直接构造 EvalReport 本来就没有"跑批起点"。"""
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "A = 1\n"})
    _point_at(monkeypatch, root)
    assert fp.report_code_fingerprint() == fp.code_fingerprint()


# ---------------------------------------------------------------- 入口脚本（缺口 4）

def test_entry_fingerprint_tracks_run_eval(tmp_path, monkeypatch):
    """`run_eval.py` 在仓库根目录，`code_fingerprint()` 扫不到，靠它单独记。

    它决定选题（--filter/--case 的解析与顺序）、`--repeat` 的逐题收集（pass^k /
    flip_rate 全从这里来）、`--oracle` 走哪条假模型路径。改它同样改读数。
    """
    root = _make_repo(tmp_path, {"run_eval.py": "x = 1\n", "app/eval/comparator.py": "A = 1\n"})
    _point_at(monkeypatch, root)
    before = fp.entry_fingerprint()
    assert before["files"]["run_eval.py"] and before["sha12"]

    (root / "run_eval.py").write_text("x = 2\n", encoding="utf-8")
    assert fp.entry_fingerprint()["sha12"] != before["sha12"]

    # 两者互不干扰：改入口不动 app/ 的门禁哈希
    gate_before = fp.code_fingerprint()["affects_results_sha256"]
    (root / "run_eval.py").write_text("x = 3\n", encoding="utf-8")
    assert fp.code_fingerprint()["affects_results_sha256"] == gate_before


def test_entry_missing_file_is_none_not_fake(tmp_path, monkeypatch):
    """扫不到就记 None，不假装有 —— 假指纹比没有指纹更坏，它会替你撒谎。"""
    root = _make_repo(tmp_path, {"app/eval/comparator.py": "A = 1\n"})
    _point_at(monkeypatch, root)
    assert fp.entry_fingerprint()["files"]["run_eval.py"] is None


def test_entry_not_a_gate_key():
    """缺口 4 这次只做到"记录"。

    进门禁需要先给 `baselines.json` 每个基线补上对应 commit 的入口哈希，否则所有历史
    报告一夜之间判不可比（它们的 `fingerprints` 里没有这个键 → comparable 判 unknown）。
    在那之前它必须留在 GATE_KEYS 外面 —— 这条断言是防盗门，别顺手加进去。
    """
    assert "entry_sha12" not in fp.GATE_KEYS


def test_report_fingerprints_expose_entry_sha12(monkeypatch):
    """报告的 fingerprints 块里能看到入口哈希（缺口 4 的落地）。"""
    from app.eval import report as rp
    from app.eval.cases import ALL_CASES

    # 只测指纹块的拼装，不做真实渲染与评测集哈希（那要跑 130 题）
    monkeypatch.setattr(rp, "evalset_fingerprint", lambda: {"sha256": "abc123def456"})
    monkeypatch.setattr(fp, "rendered_fingerprints",
                        lambda **kw: {"supported": False, "set_sha12": None})
    rep = rp.EvalReport(
        [{"case": ALL_CASES[0], "agent": "react", "correct": True, "executed": True}],
        meta={"use_dictionary": True, "memory_mode": "off", "rewrite": "0"})
    f = rep.summary()["fingerprints"]
    assert f["entry_sha12"] == fp.entry_fingerprint()["sha12"]
    assert f["code_sha12"] == fp.code_fingerprint()["affects_results_sha256"]
