"""批 4a M4 压缩：只做遮罩（docs/roadmap/memory-batch4.md §3.3）。"""
import re

from app.memory import budget as B
from app.memory.compact import explain, fit, mask, mask_brief, mask_chart, mask_digest
from app.memory.context import build, state_context
from app.memory.snapshots import BLOCK_HEAD, BLOCK_TAIL, MAX_TURNS, TurnSnapshot, render_block

PASTE = "需求说明：" + "按地区和月份统计销售额，剔除退款订单，" * 210          # ≈4000 字的长粘贴
TIGHT = 20_000        # 小预算：投影闸门把历史上限收紧到 4000 token


def turn(i, q=None, status="ok"):
    body = f"第{i}轮结论：华东销售额最高，为 {1000 + i} 元。" + "其余地区依次为华北、华南、西南，差距不大，" * 14
    return TurnSnapshot(q=q or f"第{i}个问题：各地区销售额怎么样", a_brief=body[:280] + "（关键数字：12%、3 个、45 元）",
                        a_full=body * 3, code=f"result = df.groupby('region')['sales'].sum()  # {i}",
                        result_digest="DataFrame(5x6) 列=region,month,sales,cost,units,refund",
                        chart_ref="bar「各地区销售额对比」", status=status)


def session(n=10, paste_at=0):
    snaps = [turn(i + 1) for i in range(n)]
    if paste_at is not None:
        snaps.insert(paste_at, turn(0, q=PASTE))
    return snaps


def test_mask_unit_rules():
    assert mask_brief("华东最高，为 540 元。其余依次为华北、华南。（关键数字：12%、3 个）") == "华东最高，为 540 元。（关键数字：12%、3 个）"
    assert mask_brief("没有句号的结论" + "很长" * 60) == ("没有句号的结论" + "很长" * 60)[:79] + "…"
    assert mask_brief("") == ""
    assert mask_digest("DataFrame(3x2) 列=a,b") == "DataFrame(3x2)"
    assert mask_digest("Series(3) 索引=region") == "Series(3)"
    assert mask_digest("dict(2) 键=a,b") == "dict(2)" and mask_digest("数值") == "数值"
    assert mask_chart("bar「各地区销售额」") == "bar" and mask_chart("PNG chart_1.png") == "PNG"
    assert mask_chart("图表") == "图表" and mask_chart("") == ""


def test_mask_keeps_last_two_turns_verbatim():
    snaps = session(6, paste_at=None)
    snaps[-1] = turn(6, q=PASTE)                     # 最近一轮的长粘贴也不截
    out = mask(snaps)
    assert out[-2:] == snaps[-2:]
    assert all(a != b for a, b in zip(out[:-2], snaps[:-2]))
    assert out[0].a_brief.startswith("第1轮结论：华东销售额最高，为 1001 元。（关键数字：")
    assert out[0].result_digest == "DataFrame(5x6)" and out[0].chart_ref == "bar"


def test_mask_never_touches_short_questions_or_raw_fields():
    snaps = session(5, paste_at=None)
    out = mask(snaps)
    for a, b in zip(snaps, out):
        assert a.q == b.q and a.a_full == b.a_full and a.code == b.code and a.ts == b.ts
    assert snaps[0].a_brief.endswith("45 元）") and len(snaps[0].a_brief) > 280      # 入参不被修改


def test_mask_long_paste_points_to_get_turn():
    snaps = session(4, paste_at=1)                   # 第 2 轮是长粘贴
    out = mask(snaps)
    assert out[1].q == PASTE[:200] + "…（原文较长已省略，可用 get_turn(2) 取回）"
    failed = [TurnSnapshot(q=PASTE, status="cancelled"), turn(2), turn(3)]
    assert mask(failed)[0].q.endswith("get_turn(1) 取回）") and mask(failed)[0].status == "cancelled"


def test_mask_turn_numbers_unchanged():
    snaps = session(14, paste_at=None)               # 超过 12 轮窗口
    block, dropped, masked = fit(snaps, 1500)
    nums = [int(x) for x in re.findall(r"\[第(\d+)轮", block)]
    assert nums == list(range(dropped + 1, 15)) and nums[-1] == 14
    assert masked == [n for n in nums if n <= 12]


def test_under_budget_no_mask():
    snaps = session(3, paste_at=None)
    s = state_context(snaps, 130_000, "state")
    f = state_context(snaps, 130_000, "full")
    assert s.history_block == f.history_block and s.state_block == f.state_block
    assert f.mode == "full" and f.history_tokens == s.history_tokens and f.trimmed == [] == s.trimmed
    assert explain(snaps, 6000) == {"masked": [], "dropped": []}


def test_mask_only_in_full():
    snaps = session(10, paste_at=0)
    s = build("state", snaps, token_budget=TIGHT, history_messages=None)
    f = build("full", snaps, token_budget=TIGHT, history_messages=None)
    assert "get_turn(1) 取回" in f.history_block and "get_turn(" not in s.history_block
    assert "列=" in s.history_block and "列=" not in f.history_block.split("[第10轮")[0]
    o = build("off", [(x.q, x.a_full) for x in snaps], token_budget=TIGHT,
              history_messages=lambda h: [("user", q) for q, _ in h])
    assert o.history_block == "" and o.mode == "off"


def test_masked_before_dropped():
    """4000 字粘贴 + 10 轮、历史上限 4000：state 从最早一轮开始丢（粘贴那轮先丢），full 遮罩后一轮都不丢。"""
    snaps = session(10, paste_at=0)
    s = state_context(snaps, TIGHT, "state")
    f = state_context(snaps, TIGHT, "full")
    assert "history" in s.trimmed and "[第1轮" not in s.history_block
    assert f.trimmed == [] and f.warnings == []                      # 只遮罩、不丢轮：不算裁剪，不给 warning
    assert re.findall(r"\[第(\d+)轮", f.history_block) == [str(i) for i in range(1, 12)]
    assert f.history_tokens == B.estimate_tokens(f.history_block) <= 4000
    assert f.history_block.startswith(BLOCK_HEAD) and f.history_block.endswith(BLOCK_TAIL)


def test_full_still_drops_when_mask_not_enough():
    snaps = [turn(i + 1, q=PASTE) for i in range(5)]
    f = state_context(snaps, TIGHT, "full")
    # 最近 2 轮的长粘贴逐字保留，两轮就 4000 token：遮罩后仍超，只能丢
    assert "history" in f.trimmed and B.TRIM_WARNING in f.warnings


def test_explain_lists_masked_and_dropped():
    snaps = session(10, paste_at=0)
    assert explain(snaps, 4000) == {"masked": list(range(1, 10)), "dropped": []}
    e = explain(snaps, 600)
    assert e["dropped"] and e["dropped"] == list(range(1, len(e["dropped"]) + 1))
    assert set(e["masked"]).isdisjoint(e["dropped"]) and 11 not in e["masked"]
    many = session(14, paste_at=None)
    assert explain(many, 10 ** 9) == {"masked": [], "dropped": [1, 2]}  # 12 轮窗口外的也列出


def test_acceptance_paste_plus_eleven_turns():
    """规格 M4 验收（batch4 §3.3 改写版）：4000 字粘贴 + 11 轮正常对话，full 下历史 ≤ 6000 token 且不丢轮。"""
    snaps = session(11, paste_at=0)
    assert len(snaps) == MAX_TURNS
    f = state_context(snaps, 130_000, "full")
    assert f.history_tokens <= 6000 and "history" not in f.trimmed
    assert len(re.findall(r"\[第\d+轮", f.history_block)) == 12


def test_get_turn_reads_original_in_full():
    snaps = session(10, paste_at=0)
    f = state_context(snaps, TIGHT, "full")
    tool = f.tools()[0]
    text = tool.invoke({"n": 1})
    assert ("问：" + PASTE[:3000]) in text and "原文较长已省略" not in text      # 原文（get_turn 自己的 4000 字上限另算）
    assert f.snaps[0].q == PASTE


def test_render_block_is_unchanged_for_state():
    """state 仍走 render_block 原逻辑（硬规则 3 的另一半由 test_memory_p8 的哈希钉住）。"""
    snaps = session(10, paste_at=0)
    s = state_context(snaps, TIGHT, "state")
    cap = B.history_cap(TIGHT, None, B.estimate_tokens(render_block(snaps, 10 ** 9)[0]))
    assert s.history_block == render_block(snaps, cap)[0]
