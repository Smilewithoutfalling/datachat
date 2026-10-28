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
