"""阶段 6.6 M3 回合快照 + M5 失败轮：历史渲染成数据块（全部由代码生成）。"""
from datetime import timedelta, timezone

import pandas as pd

from app.memory.snapshots import (BLOCK_HEAD, BLOCK_TAIL, MAX_TURNS, TurnSnapshot, brief, chart_ref, coerce,
                                  digest, from_row, render_block)


def test_snapshot_brief_max_300_chars():
    assert len(brief("很长" * 400)) == 300 and brief("很长" * 400).endswith("…")
    assert brief("华北最高，为 540 件。") == "华北最高，为 540 件。"             # 没有空行：整段就是首段
    b = brief("华北最高。\n\n其次华东 525 件，华南 620 件，占比 38%，另有 9 单退货。")
    assert b == "华北最高。（关键数字：525 件、620 件、38%）"
    assert brief("") == ""


def test_result_digest_has_no_values():
    s = pd.Series([540, 525], index=pd.Index(["华北", "华东"], name="region"))
    assert digest(s) == "Series(2) 索引=region"
    d = pd.DataFrame({"a": [1, 2, 3], "b": ["秘密值", "x", "y"]})
    assert digest(d) == "DataFrame(3x2) 列=a,b"
    for obj in (s, d, 123456.789, "华北", {"华北": 1}):
        assert "540" not in digest(obj) and "秘密值" not in digest(obj) and "123456" not in digest(obj)


def test_chart_ref_from_option_and_png():
    opt = {"series": [{"type": "bar"}], "title": {"text": "各地区销售额"}}
    assert chart_ref([{"png": None, "option": opt}]) == "bar「各地区销售额」"
    assert chart_ref(["/x/charts/chart_1_abc.png"]) == "PNG chart_1_abc.png"   # [26] 之前的记录是字符串
    assert chart_ref([{"png": "C:\\Users\\me\\charts\\chart_1_abc.png", "option": None}]) == "PNG chart_1_abc.png"


def test_render_block_format():
    # 时区显式传进去，不靠 TZ 环境变量 + time.tzset()：Windows 没有 time.tzset()，
    # 那种写法在 CI 的 windows-latest 上直接 AttributeError（#90 就红在这里）。
    tz = timezone(timedelta(hours=8))
    snaps = [TurnSnapshot(q="各地区销售额？", a_brief="华北最高。", result_digest="Series(5) 索引=地区",
                          chart_ref="bar「各地区销售额」", ts="2026-10-20T06:03:00.123+00:00"),
             TurnSnapshot(q="改成堆叠", status="cancelled", ts="2026-10-20T06:05:00.000+00:00")]
    block, dropped = render_block(snaps, 6000, tz=tz)
    assert dropped == 0
    assert block == (BLOCK_HEAD + "\n"
                     "[第1轮 · 2026-10-20 14:03]\n问：各地区销售额？\n答：华北最高。\n结果：Series(5) 索引=地区\n"
                     "图：bar「各地区销售额」\n\n"
                     "[第2轮 · 2026-10-20 14:05 · 未完成]\n问：改成堆叠\n状态：已取消\n" + BLOCK_TAIL)


def test_render_block_empty_returns_empty():
    assert render_block([], 6000) == ("", 0)


def test_render_block_keeps_last_12_turns_with_real_numbers():
    snaps = [TurnSnapshot(q=f"问题{i}") for i in range(1, 16)]
    block, dropped = render_block(snaps, 10 ** 6)
    assert dropped == 15 - MAX_TURNS and "问题3\n" not in block and "[第4轮 · " in block and "[第15轮 · " in block


def test_render_block_drops_oldest_when_over_budget():
    snaps = [TurnSnapshot(q="长" * 3000, a_brief="一"), TurnSnapshot(q="短问题", a_brief="二")]
    block, dropped = render_block(snaps, 1000)
    assert dropped == 1 and "短问题" in block and "长长长" not in block
    one, d2 = render_block([TurnSnapshot(q="长" * 3000)], 500)    # 只剩一轮还超：截问题原文
    assert -(-len(one) // 2) <= 500 and one.startswith(BLOCK_HEAD) and one.endswith(BLOCK_TAIL)


def test_coerce_accepts_tuples_dicts_and_snapshots():
    s = coerce([("q1", "a1"), ("q2", "a2", "result = 1"), {"q": "q3", "a": "a3"}, TurnSnapshot(q="q4")])
    assert [x.q for x in s] == ["q1", "q2", "q3", "q4"] and s[1].code == "result = 1" and s[2].a_brief == "a3"


# ------------------------------------------------------------------ M5 失败轮
def test_cancelled_turn_keeps_question_only():
    s = from_row("各地区利润", "2026-10-20T06:03:00+00:00", "cancelled", "已停止", None)
    block, _ = render_block([s], 6000)
    assert "问：各地区利润\n状态：已取消" in block and "答：" not in block and "· 未完成]" in block


def test_error_turn_does_not_leak_error_text():
    s = from_row("算一下", "", "error", "执行出错：FileNotFoundError /home/me/secret.csv",
                 {"error_kind": "execution", "error": "Traceback /home/me/secret.csv", "code": "result = 1"})
    block, _ = render_block([s], 6000)
    assert "状态：失败（代码执行）" in block
    assert "secret" not in block and "Traceback" not in block and s.code == ""   # 失败轮的代码也不进状态
    i = from_row("再来", "", "interrupted", "连接已断开", None)
    assert "状态：连接中断" in render_block([i], 6000)[0]


def test_ok_turn_from_row_uses_result_json_fields():
    r = {"answer": "华北最高。", "code": "result = df.groupby('region').size()", "result_digest": "Series(3) 索引=region",
         "charts": [{"png": None, "option": {"series": [{"type": "pie"}], "title": {"text": "占比"}}}],
         "usage": {"calls": 4}}
    s = from_row("哪个地区多", "2026-10-20T06:03:00+00:00", "ok", "华北最高。", r)
    assert (s.a_brief, s.result_digest, s.chart_ref, s.calls) == ("华北最高。", "Series(3) 索引=region", "pie「占比」", 4)
    assert "result = df" not in render_block([s], 6000)[0]                 # 代码不进渲染出来的块
