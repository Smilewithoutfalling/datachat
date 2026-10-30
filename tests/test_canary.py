"""canary 十条的门槛：题不能抖，也不能是可绕开的。

存在的理由很具体：第一版按"台账里翻过转的 id"选题，10 条里 5 条 gold 返回 Series，
3 跑下来翻 3 题，逐条查过原始输出**没有一条是算错**——全是索引写法、`result` 没赋值、
题面允许别的解释。探针一旦这么选，读到的变化就分不清是模型变了还是它自己抖。

所以下面这几条断言不是形式检查，每一条都对应一次踩过的坑：

1. 必须单轮 —— 多轮一拍上记忆模式，翻转就分不清是权重还是编排；
2. 必须非 ambiguity —— 那类靠多答案容错，判定边界本身在晃；
3. **gold 必须返回标量** —— Series/DataFrame 的比对躲不开索引写法与行列顺序；
4. 类别要摊开 —— 十条全堆在聚合上，别的能力面就没人盯。
"""
import numpy as np

import app.eval.canary as C
from app.eval.cases import ALL_CASES
from app.eval.runner import EvalRunner


def _by_id():
    return {c.id: c for c in ALL_CASES}


def test_canary_has_exactly_ten_unique_ids():
    assert len(C.CANARY_IDS) == 10
    assert len(set(C.CANARY_IDS)) == 10, "canary 清单里有重复 id"


def test_every_canary_id_exists_and_is_single_turn():
    m = _by_id()
    missing = [i for i in C.CANARY_IDS if i not in m]
    assert not missing, f"canary 引用了不存在的用例: {missing}"
    multi = [i for i in C.CANARY_IDS if m[i].turns]
    assert not multi, (
        f"canary 只能是单轮题，这些是多轮: {multi}。"
        "多轮题一拍上记忆模式（off 回灌 / state 渲染），翻转就分不清是权重变了还是编排变了。"
    )


def test_no_canary_case_is_ambiguous():
    m = _by_id()
    amb = [i for i in C.CANARY_IDS if m[i].category == "ambiguity"]
    assert not amb, (
        f"歧义题靠 alt_ground_truths 容错，模型换个合理口径也算对，判定边界在晃: {amb}"
    )


def test_canary_ground_truth_returns_a_scalar():
    """本条是 2026-10-30 那次作废换来的，最贵的一条。

    Series / DataFrame 的比对要额外约定索引写成日期还是日期区间、行列谁先谁后、
    标签是周起始还是周结束。那些抖动属于判分器，不属于模型权重，放进探针就是把
    噪声当信号。
    """
    runner = EvalRunner(agent="react")
    m = _by_id()
    bad = []
    for cid in C.CANARY_IDS:
        outs, err = runner.expected_all(m[cid])
        assert not err, f"{cid} 的 ground_truth 跑不起来: {err}"
        assert outs, f"{cid} 的 ground_truth 没有产出结果"
        for v in outs:
            ok = isinstance(v, (bool, str, int, float, np.bool_, np.integer, np.floating))
            if not ok:
                bad.append((cid, type(v).__name__))
    assert not bad, (
        f"这些题的 gold 不是标量，判定会依赖表示法，不能当探针: {bad}"
    )


def test_canary_covers_five_categories_two_each():
    """类别摊开：十条全堆在聚合上，别的能力面就没人盯。"""
    m = _by_id()
    counts = {}
    for cid in C.CANARY_IDS:
        cat = m[cid].category
        counts[cat] = counts.get(cat, 0) + 1
    assert set(counts) == {"aggregation", "filtering", "correlation", "timeseries", "refusal"}, (
        f"canary 应覆盖五类，实际: {sorted(counts)}"
    )
    assert all(v == 2 for v in counts.values()), f"每类应各 2 条，实际: {counts}"


def test_every_id_has_a_stated_reason():
    assert set(C.CANARY_WHY) == set(C.CANARY_IDS), (
        "CANARY_WHY 必须逐条给理由：以后想换题的人得先看到当初为什么选它"
    )


def test_canary_cases_follow_the_declared_order():
    picked = C.canary_cases()
    assert [c.id for c in picked] == list(C.CANARY_IDS), (
        "跑序必须恒等于清单顺序，否则两次运行题序不同，读数就不再可比"
    )


def test_canary_cases_raises_on_missing_id():
    partial = [c for c in ALL_CASES if c.id != C.CANARY_IDS[0]]
    try:
        C.canary_cases(partial)
    except ValueError as e:
        assert C.CANARY_IDS[0] in str(e)
    else:
        raise AssertionError("缺题时必须抛错，不能静默少跑几条")


def test_fingerprint_is_twelve_hex_chars():
    fp = C.canary_fingerprint()
    assert len(fp) == 12 and all(ch in "0123456789abcdef" for ch in fp), fp


def test_fingerprint_changes_when_a_question_changes():
    """指纹的意义：题动过就必须变，否则改了题还沿用旧基准，等于换了卷子比成绩。"""
    base = C.canary_fingerprint()
    cases = C.canary_cases()
    original = cases[0].question
    try:
        cases[0].question = original + "（改）"
        assert C.canary_fingerprint() != base
    finally:
        cases[0].question = original
    assert C.canary_fingerprint() == base, "改回来必须回到原值，否则不是确定性哈希"


def test_reasons_are_not_placeholders():
    """理由非空且不是"补类别"这种空话——第一版里就有一条写成"补类别"，事后看等于没写。"""
    thin = [k for k, v in C.CANARY_WHY.items() if len(v.strip()) < 12]
    assert not thin, f"这几条理由太短，等于没说明为什么它不抖: {thin}"
