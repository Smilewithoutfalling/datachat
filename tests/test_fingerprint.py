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


# ---------------------------------------------------------------- 可比性判定

BASE = {"agent": "react", "memory_mode": "off", "rewrite": "0", "use_dictionary": True,
        "affects_results_sha256": "aaa", "evalset_sha256": "bbb", "rendered_set_sha12": "ccc"}


def test_comparable_when_gate_equal():
    r = fp.comparable(dict(BASE), dict(BASE))
    assert r == {"comparable": True, "basis": "gate", "diffs": []}


def test_comparable_exempt_when_rendered_equal():
    now = dict(BASE, affects_results_sha256="zzz")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is True and r["basis"] == "rendered-equal"
    assert r["diffs"] == ["affects_results_sha256"]


def test_not_comparable_when_rendered_differs():
    now = dict(BASE, affects_results_sha256="zzz", rendered_set_sha12="ddd")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is False
    assert "affects_results_sha256" in r["diffs"]


def test_not_comparable_without_fingerprint():
    """老报告（31 份历史报告）没有任何指纹字段，不能被当成可比。"""
    assert fp.comparable(dict(BASE), {"agent": "react"})["comparable"] is False


def test_memory_mode_change_blocks_comparison():
    """记忆系统落地后 memory_mode 从 off 变 state，必须判不可比——渲染串可能没变，
    但上下文组装变了，分数不再和旧 baseline 同一把尺子。"""
    now = dict(BASE, memory_mode="state")
    assert fp.comparable(now, dict(BASE))["comparable"] is False


def test_evalset_change_not_exempted_by_rendered():
    """期望值改了但题面和数据没变时，渲染串一样；这不能算可比——尺子的刻度变了。"""
    now = dict(BASE, evalset_sha256="zzz")
    r = fp.comparable(now, dict(BASE))
    assert r["comparable"] is False and r["diffs"] == ["evalset_sha256"]
