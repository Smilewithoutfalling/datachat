"""EV-C3：`--repeat` 的稳定性块。

这里测的是 `run_eval._stability` 的读数口径，不是 `stats.py` 的算法（那是 test_stats.py）。
分开测的理由：算法对了，口径还能错——把 flip_rate 写成"翻转题数/题数"就是一个不会报错的错。
"""
import math

import pytest

from run_eval import _stability


def _rec(passes, sig=None):
    """默认 sig 让 k 跑之间 token 有抖动——这是真实情况。

    eval-v1 的 130 题 3 跑里，只有 15 题 (tokens, code) 全同（11.5%），
    默认全同会直接把 valid 打成 False，测的就不是 pass^k 了。
    """
    if sig is None:
        sig = [(100 + i, f"code_{i}") for i in range(len(passes))]
    return {"passes": list(passes), "sig": sig}


def test_all_correct_and_one_flip():
    """126 题三跑全对 + 4 题各翻一次（passes=2）：pass^3 = 126/130，flip_rate = 4·(2·1/3)/130。"""
    per_case = {f"case_{i:03d}": _rec([True, True, True]) for i in range(126)}
    for j, cid in enumerate(["inv_021", "ord_004", "ord_030", "inv_016"]):
        per_case[cid] = _rec([True, False, True])
    s = _stability(per_case, 3)
    assert s["k"] == 3 and s["n_cases"] == 130
    assert s["pass_pow_k"] == pytest.approx(126 / 130)
    assert s["any_correct"] == pytest.approx(1.0)
    assert s["flipped"]["count"] == 4
    assert set(s["flipped"]["ids"]) == {"inv_021", "ord_004", "ord_030", "inv_016"}
    # 每道翻转题的单题 flip_rate 是 2·(3−2)/C(3,2) = 2/3
    assert s["flip_rate"] == pytest.approx(4 * (2 / 3) / 130)
    assert s["always_wrong"] == []
    assert s["valid"] is True


def test_flip_rate_is_not_flipped_count_over_n():
    """这条是防回归的靶子：口径写错（翻转题数/题数 = 3.08%）时它会挂。

    两个数的量级接近，所以光看打印值发现不了；差在分母——一个是(题, 跑对)，一个是题。
    """
    per_case = {f"case_{i:03d}": _rec([True, True, True]) for i in range(126)}
    for cid in ["a", "b", "c", "d"]:
        per_case[cid] = _rec([True, False, True])
    s = _stability(per_case, 3)
    assert s["flip_rate"] != pytest.approx(4 / 130)
    assert s["flip_rate"] == pytest.approx(2.0 / 97.5, rel=1e-3)   # 8/3 / 130


def test_asymmetric_passes_same_flip_rate():
    """passes=1 与 passes=2 必须同为 2/3：翻转是对称的。

    `min(passes, k−passes)/k` 这种写法会给 0.33 / 0.67 且上限只有 0.5，
    所有题都翻一次也永远过不了 50% 的门槛，等于把测量仪器的量程砍掉一半。
    """
    a = _stability({"x": _rec([True, False, False])}, 3)
    b = _stability({"x": _rec([True, True, False])}, 3)
    assert a["flip_rate"] == pytest.approx(b["flip_rate"])
    assert a["flip_rate"] == pytest.approx(2 / 3)
    # 但 pass^k 与 any_correct 必须区分这两者
    assert a["pass_pow_k"] == 0.0 and a["any_correct"] == 1.0
    assert b["pass_pow_k"] == 0.0 and b["any_correct"] == 1.0


def test_always_wrong_listed():
    per_case = {"ok": _rec([True] * 3), "bad": _rec([False] * 3), "flip": _rec([True, False, True])}
    s = _stability(per_case, 3)
    assert s["always_wrong"] == ["bad"]
    assert s["pass_pow_k"] == pytest.approx(1 / 3)
    assert s["any_correct"] == pytest.approx(2 / 3)
    assert s["flipped"]["ids"] == ["flip"]


def test_identical_everywhere_marks_invalid():
    """k 次跑出来 (tokens, code) 全同 → 缓存嫌疑，pass^k 不能当结论用。

    文案要同时点出 `--oracle` 的可能：那模式下 tokens 是桩值（恒 30），也会命中这里，
    但原因不是缓存。只写"响应被复用"会把人引到错误方向。
    """
    per_case = {f"c{i}": {"passes": [True] * 3, "sig": [(100, "result = 1")] * 3} for i in range(5)}
    s = _stability(per_case, 3)
    assert s["identical_cases"] == 5
    assert s["valid"] is False
    assert "复用" in s["invalid_reason"]
    assert "oracle" in s["invalid_reason"]


def test_partial_identical_stays_valid():
    """temp=0 时部分题逐字相同是正常的：只有全库都相同才算异常。

    用比例做门禁（比如 >80% 就 invalid）会把"模型很稳"误判成"命中缓存"，
    而这两件事在温度 0 下本来就分不开。
    """
    per_case = {f"c{i}": {"passes": [True] * 3, "sig": [(100, "x")] * 3} for i in range(4)}
    per_case["flip"] = {"passes": [True, False, True], "sig": [(100, "x"), (120, "y"), (100, "x")]}
    s = _stability(per_case, 3)
    assert s["identical_cases"] == 4
    assert s["valid"] is True


def test_missing_tokens_not_counted_as_identical():
    """tokens 拿不到（None）时不能算"逐字相同"，否则缺数据会被读成缓存。"""
    per_case = {"a": {"passes": [True] * 3, "sig": [(None, ""), (None, ""), (None, "")]}}
    s = _stability(per_case, 3)
    assert s["identical_cases"] == 0
    assert s["valid"] is True


def test_needs_at_least_two_runs():
    assert _stability({"a": _rec([True, True])}, 1) is None
    assert _stability({}, 3) is None
