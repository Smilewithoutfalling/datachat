"""打印「不带 --memory 跑一次全量，报告里会有多少题」——给 CI 的 --expect-n 用。

**为什么要有这个脚本，而不是在 YAML 里写个 one-liner。** `tier_check --expect-n`
必须镜像 `run_eval.py` 的取舍，两边各写一份就一定会漂：2026-11 之前 YAML 里写死
`len(ALL_CASES)`（202），而默认档是 `off`、runner 会跳过 7 条 `requires_memory` 题，
实际只产出 195 条 → 结构性红灯，永远不可能绿。

2026-11-16（C-021）产品默认档改成 `state` 之后，默认跑批**收录**全部 `requires_memory`
题，报告是 202 条 —— 同一个 one-liner 又反过来错了。所以判定改成和 runner 同一份逻辑：
`resolve_memory_mode()` 是 off 才减掉那 7 条，否则全收。

`DATACHAT_MEMORY` 会影响结果（env 优先于默认档），这正是要的：CI 若哪天设了 env，
这里算出来的数就和 runner 实际跑的题数一致。

**必须自己把仓库根塞进 sys.path**：CI 里是 `python scripts/eval/expected_cases.py`，
直跑时 `sys.path[0]` 是 `scripts/eval`，`import app` 会 ModuleNotFoundError
（2026-11-17 本地复现 CI 时踩到；`tier_check.py` 同样的写法）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.eval.cases import ALL_CASES  # noqa: E402
from app.memory.config import resolve_memory_mode  # noqa: E402


def expected_count() -> int:
    if resolve_memory_mode() == "off":
        return sum(1 for c in ALL_CASES if not getattr(c, "requires_memory", ""))
    return len(ALL_CASES)


if __name__ == "__main__":
    print(expected_count())
