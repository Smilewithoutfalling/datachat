"""失败归因表的一致性（EV-D2）：文档表格的码集合必须等于代码里的码集合。"""
import json
import re
import subprocess
import sys
from pathlib import Path

from app.eval import failure_classes as FC

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "eval" / "failure-map.md"


def _doc_codes() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return re.findall(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|", text, re.MULTILINE)


def test_doc_and_code_have_same_codes():
    """只改一边就红——这是本卡唯一的硬约束。"""
    doc = _doc_codes()
    assert len(doc) == len(set(doc)), f"文档表格里有重复码：{doc}"
    assert set(doc) == FC.codes(), (
        f"码集合不一致\n文档多：{sorted(set(doc) - FC.codes())}\n代码多：{sorted(FC.codes() - set(doc))}")


def test_gate_six_covered_and_unique():
    """闸门 1–6 必须一一对应，且编号不重不漏（人工标注全靠它）。"""
    ids = [c.gate_id for c in FC.GATE_CLASSES]
    assert ids == [1, 2, 3, 4, 5, 6], ids
    assert len(FC.GATE_CLASSES) == 6


def test_every_code_has_module_and_fix():
    for c in FC.ALL_CLASSES:
        assert c.module.startswith("app/"), f"{c.code} 的落点不是具体模块：{c.module}"
        assert (REPO / c.module).exists(), f"{c.code} 的落点文件不存在：{c.module}"
        assert c.fix.strip() and c.keywords, f"{c.code} 缺修复方向或关键词"


def test_match_int_and_free_text():
    assert FC.match(1).code == "F01_PARSE"
    assert FC.match("6").code == "F06_REFUSAL"
    assert FC.match("schema 理解错").code == "F02_SCHEMA"
    assert FC.match("口径没写清").code == "F03_CALIBER"
    assert FC.match("ANSWER_RESULT_MISMATCH").code == "A01_ANSWER_RESULT_MISMATCH"
    # 认出多个关键词时取最长命中（更具体者优先）
    assert FC.match("合计行被当成明细").code == "A04_TOTAL_ROW_COUNTED"


def test_match_returns_none_for_unknown():
    """认不出必须返回 None —— 调用方据此打印并以非 0 退出，不许静默归类。"""
    assert FC.match("玄学问题") is None
    assert FC.match(None) is None
    assert FC.match("") is None


# ---------------------------------------------------------------- triage 端到端

def _run_triage(tmp_path, reports: dict[str, dict]) -> tuple[int, dict]:
    paths = []
    for name, payload in reports.items():
        p = tmp_path / name
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        paths.append(str(p))
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "eval" / "triage.py"),
                        *paths, "--json"], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout)


def test_triage_groups_gate_and_eval_reports(tmp_path):
    gate = {"cases": [
        {"id": "s01", "human_correct": False, "failure_class": 2},
        {"id": "s02", "human_correct": True, "failure_class": None},
        {"id": "s03", "human_correct": None, "failure_class": None},
        {"id": "s04", "human_correct": False, "failure_class": None},          # 归因缺口
        {"id": "s05", "human_correct": False, "failure_class": 4,
         "error": "llm timeout"},                                              # infra 优先
    ]}
    ev = {"cases": [
        {"id": "mul_001", "correct": False, "evidence": {"failures": ["ANSWER_RESULT_MISMATCH"]}},
        {"id": "mul_002", "correct": True, "evidence": {"failures": []}},
    ]}
    code, out = _run_triage(tmp_path, {"gate.json": gate, "eval.json": ev})
    assert code == 0
    assert set(out["buckets"]) == {"F02_SCHEMA", "A01_ANSWER_RESULT_MISMATCH"}
    assert [i["id"] for i in out["buckets"]["F02_SCHEMA"]] == ["s01"]
    assert [i["id"] for i in out["unlabeled"]] == ["s04"]
    assert [i["id"] for i in out["infra"]] == ["s05"]
    assert out["unmapped"] == []


def test_triage_exits_nonzero_on_unmapped(tmp_path):
    gate = {"cases": [{"id": "s09", "human_correct": False, "failure_class": "玄学问题"}]}
    code, out = _run_triage(tmp_path, {"gate.json": gate})
    assert code == 1, "未映射必须非 0 退出，否则 nightly 会把归因缺口当通过"
    assert out["unmapped"][0]["raw"] == "玄学问题"


def test_triage_attributes_perturb_failures_by_variant(tmp_path):
    """扰动报告不写 evidence，但 variant_kind 是确定性归因信号，不该落进"归因缺口"。"""
    rep = {"cases": [
        {"id": "pf_emp_001.total_row", "correct": False, "variant_kind": "total_row"},
        {"id": "pf_ord_001.thousand_sep", "correct": False, "variant_kind": "thousand_sep"},
        {"id": "pf_x.weird_kind", "correct": False, "variant_kind": "weird_kind"},   # 未知变体仍要暴露
    ]}
    code, out = _run_triage(tmp_path, {"perturb.json": rep})
    assert code == 0
    assert [i["id"] for i in out["buckets"]["A04_TOTAL_ROW_COUNTED"]] == ["pf_emp_001.total_row"]
    assert [i["id"] for i in out["buckets"]["F01_PARSE"]] == ["pf_ord_001.thousand_sep"]
    assert [i["id"] for i in out["unlabeled"]] == ["pf_x.weird_kind"]


def test_triage_says_nothing_to_do_when_report_has_no_failures(tmp_path):
    """报告里没有任何失败字段时，输出必须是"没带失败信息"，不能是"0 未映射"式的假通过。"""
    empty = {"cases": [{"id": "x1", "correct": True, "evidence": {"failures": []}}]}
    paths = []
    p = tmp_path / "empty.json"
    p.write_text(json.dumps(empty), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "eval" / "triage.py"), str(p)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0
    assert "没有带失败信息" in r.stdout
