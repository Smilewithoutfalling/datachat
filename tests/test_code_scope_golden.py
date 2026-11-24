"""阶段 7.5 第 3 步 S3-2：口径判定从 app/assess/code_refs.py 搬到 app/tools/code_scope.py，输出逐字节不变。

golden.json 是搬家**之前**用旧路径（9c40a97 的 app/assess/code_refs.py + contracts.scope_of / reviewer_scope）
对 cases.json 跑出来冻结的（tests/fixtures/code_scope/gen_golden.py，单独一个 commit 落盘）。这里用新路径重算，
要求与 golden 逐字节相同：抽取结果（refs）、过滤条件、scope_of、reviewer_scope 的 verdict。
"""
import importlib.util
import os

from app.assess import contracts as C
from app.tools import code_scope as S

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "code_scope")


def _gen():
    spec = importlib.util.spec_from_file_location("gen_golden", os.path.join(HERE, "gen_golden.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _golden() -> str:
    with open(os.path.join(HERE, "golden.json"), encoding="utf-8", newline="") as fh:
        return fh.read()


def test_new_path_matches_golden_byte_for_byte():
    """新路径：抽取直接用 app.tools.code_scope；scope_of / reviewer_scope 经 contracts（已改为调 code_scope）。"""
    def scope_new(code, ctx):
        return S.scope_of(code, ctx.columns, ctx.multi)
    got = _gen().compute(S.analyze_code, S.filter_conditions, scope_new, C.reviewer_scope, C.Context)
    assert got == _golden()


def test_contracts_wrappers_match_golden():
    got = _gen().compute(S.analyze_code, S.filter_conditions, C.scope_of, C.reviewer_scope, C.Context)
    assert got == _golden()


def test_assess_code_refs_is_reexport_only():
    from app.assess import code_refs
    assert code_refs.analyze_code is S.analyze_code and code_refs.filter_conditions is S.filter_conditions
    assert C.code_refs is S


def test_golden_covers_required_shapes():
    """方案 §3 验收要求覆盖：列增删、过滤变化、拼错列名、多表、解析失败。"""
    import json
    ids = {c["id"] for c in json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))["cases"]}
    assert len(ids) >= 12
    for need in ("column_added", "column_removed", "filter_value_changed", "filter_removed", "typo_fixed",
                 "multi_merge_add_city", "multi_bad_table_fixed", "parse_fail_before", "parse_fail_after"):
        assert need in ids


def test_tools_code_scope_does_not_import_assess():
    import ast
    tree = ast.parse(open(S.__file__, encoding="utf-8").read())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any((m or "").startswith("app.assess") for m in mods)
