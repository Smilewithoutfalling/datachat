"""F3：前端图表夹具（ui/web/src/generated/chart_fixtures.json）的后端期望。生成与比对由 gen_ui_types --check 负责，
这里只钉住语义：全是成功例、每种 kind 都有、5001 是"截断成功"（产出 5000 点、truncated=true、通过 validate_spec）。"""
import json
import os

from app.tools.charts import KINDS, MAX_POINTS, validate_spec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "ui", "web", "src", "generated", "chart_fixtures.json")


def _fixtures():
    with open(FIX, encoding="utf-8") as f:
        return {x["id"]: x["spec"] for x in json.load(f)["fixtures"]}


def test_all_fixtures_pass_validate_spec_and_cover_every_kind():
    fx = _fixtures()
    assert all(validate_spec(s) == [] for s in fx.values())
    assert {s["kind"] for s in fx.values()} == set(KINDS)


def test_point_boundaries():
    fx = _fixtures()
    for kind in ("bar", "scatter"):
        at, over = fx[f"{kind}-{MAX_POINTS}"], fx[f"{kind}-{MAX_POINTS + 1}"]
        assert at["truncated"] is False and len(at["option"]["series"][0]["data"]) == MAX_POINTS
        assert over["truncated"] is True and len(over["option"]["series"][0]["data"]) == MAX_POINTS


def test_no_fixture_contains_contain_label():
    """F3 第三步：前端摘掉 LegacyGridContainLabel 的依据——全部夹具产物里都没有 containLabel。"""
    text = json.dumps(_fixtures(), ensure_ascii=False)
    assert "containLabel" not in text and "outerBoundsMode" in text
