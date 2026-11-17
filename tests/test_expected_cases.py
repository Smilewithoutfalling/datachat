"""CI 的 `--expect-n` 必须和 runner 实际跑的题数一致（scripts/eval/expected_cases.py）。

**为什么单独钉这个。** `tier_check --expect-n` 判的是"题数少了 = 没跑完"，所以这个数
只能从 runner 的取舍里算出来，不能手写：2026-11 之前 YAML 里写死 `len(ALL_CASES)`=202，
而默认档是 `off`、runner 跳过 7 条 `requires_memory` 题 → 实际 195 条 → 结构性红灯，
永远不可能绿。2026-11-16（C-021）默认档改成 `state` 之后，同一个 one-liner 又反过来
少了 7 条。两次都是"两处各写一份逻辑"造成的，所以算题现在只有 `expected_cases` 一份。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "eval"))

from expected_cases import expected_count  # noqa: E402

from app.eval.cases import ALL_CASES  # noqa: E402


def _requires_memory_count() -> int:
    return sum(1 for c in ALL_CASES if getattr(c, "requires_memory", ""))


def test_default_mode_counts_every_case(monkeypatch):
    """默认档（C-021 起 state）收全部题：202 条。"""
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    assert len(ALL_CASES) == 202          # 加题时这一行要跟着改（题数写死是有意的）
    assert expected_count() == 202


def test_off_mode_drops_requires_memory(monkeypatch):
    """off 档跳过 requires_memory 题：202 − 7 = 195，与 runner 跳过的同一批。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "off")
    assert _requires_memory_count() == 7
    assert expected_count() == len(ALL_CASES) - 7 == 195


def test_full_mode_counts_every_case(monkeypatch):
    """full 与 state 一样收全部题 —— 只有 off 会跳过。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "full")
    assert expected_count() == len(ALL_CASES)
