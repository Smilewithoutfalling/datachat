"""生成 golden.json：S3-2 搬家前用旧路径（app/assess/code_refs.py + contracts.scope_of / reviewer_scope）跑 cases.json。

**只在搬家前跑一次**（9c40a97，2026-11-24）。搬家后 tests/test_code_scope_golden.py 用新路径
（app/tools/code_scope.py）对同一批输入重算，要求与本文件冻结的输出逐字节一致。重跑本脚本会用当时的
代码覆盖 golden —— 除非有意重立，否则不要跑。

用法：python tests/fixtures/code_scope/gen_golden.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))


def refs_dict(refs):
    if refs is None:
        return None
    return {"columns": [list(x) for x in refs.columns], "created": sorted(refs.created),
            "bad_tables": list(refs.bad_tables), "imports": [list(x) for x in refs.imports],
            "free_names": sorted(refs.free_names), "assigns_result": refs.assigns_result}


def scope_dict(s):
    if s is None:
        return None
    cols, miss, conds = s
    return {"columns": sorted(cols), "missing": sorted(miss), "filters": sorted(conds)}


def compute(analyze_code, filter_conditions, scope_of, reviewer_scope, Context):
    spec = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
    out = []
    for c in spec["cases"]:
        cx = spec["contexts"][c["ctx"]]
        ctx = Context(columns=cx["columns"], multi=cx["multi"])
        tables = [t for t in cx["columns"] if t]
        rec = {"id": c["id"]}
        for side in ("before", "after"):
            code = c[side]
            rec[side] = {
                "refs": refs_dict(analyze_code(code, multi=cx["multi"], tables=tables)),
                "filters": None if filter_conditions(code) is None else sorted(filter_conditions(code)),
                "scope": scope_dict(scope_of(code, ctx)),
            }
        rec["verdict"] = reviewer_scope({"code": c["before"], **c.get("state", {})}, {"code": c["after"]}, ctx).to_dict()
        out.append(rec)
    return json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    from app.assess.code_refs import analyze_code, filter_conditions
    from app.assess.contracts import Context, reviewer_scope, scope_of
    text = compute(analyze_code, filter_conditions, scope_of, reviewer_scope, Context)
    with open(os.path.join(HERE, "golden.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote golden.json", len(text), "bytes")
