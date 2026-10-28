"""评测用例的静态校验（EV-A1）。

刻意做成"返回错误列表"而不是在 `EvalCase.__post_init__` 里抛异常：
一条用例有 3 个问题时，一次看全比改一个错再发现下一个省事；批量加题时尤其是。
也让测试能用临时构造的用例单独验证某条规则，不碰 `ALL_CASES`。

规则与 §3.1 的 5 条硬约束一一对应，另加第 6 条（`expect_turns` 的取值枚举）：
枚举写错时断言会静默失效——`expect_turns=["executed"]` 看着像对的，执行器却认不出，
于是那轮的约束根本没检查，报告还是绿的。
"""
from __future__ import annotations

import os
import re

# 评测题号。闸门题号（s01…s15 / m01…m10）是另一套命名空间，存在 docs/gate/answers.json 里，
# 以 dict 形式传给 run_gate.py，永远不经过这里——别把这个正则扩成包含 (s|m)，
# 那个分支在评测集里恒不命中，是死条件。
ID_RE = re.compile(r"^[a-z]{2,6}_\d{3}$")

CATEGORIES = {"aggregation", "filtering", "correlation", "timeseries", "refusal", "ambiguity"}

EXPECT_TURN_KINDS = {"exec", "refusal", "any"}
EXPECT_TURN_PREFIX = "inherit:"

EXPECT_KINDS = {"", "refusal", "clarify", "impossible"}
GOLD_KINDS = {"", "scalar", "series", "frame", "text"}


def _expect_turn_ok(spec: str) -> bool:
    if spec in EXPECT_TURN_KINDS:
        return True
    if spec.startswith(EXPECT_TURN_PREFIX):
        # "inherit:" 后面必须有东西——空的 regex 会匹配一切，等于没约束
        return bool(spec[len(EXPECT_TURN_PREFIX):].strip())
    return False


def validate_cases(cases: list) -> list[str]:
    """返回错误列表，空列表 = 通过。

    known_ids 取本批用例的 id 集合，而不是去 import ALL_CASES：
    validate 会被 cases.py 在模块级调用，反向 import 会成环。对 ALL_CASES 来说
    这两种取法等价；对临时构造的一批也能直接验。
    """
    from app.eval.cases import DATASETS  # 懒导入：模块级会成环

    errors: list[str] = []
    known_ids = {c.id for c in cases}

    seen: dict[str, int] = {}
    for c in cases:
        # 1. id 格式与唯一
        if not ID_RE.match(c.id):
            errors.append(f"{c.id}: id 必须匹配 ^[a-z]{{2,6}}_\\d{{3}}$")
        seen[c.id] = seen.get(c.id, 0) + 1

        # 5. category 限定在现有 6 类（新增会改所有按类报表的分母）
        if c.category not in CATEGORIES:
            errors.append(f"{c.id}: category={c.category!r} 不在 {sorted(CATEGORIES)}")

        # 2. 多轮：expect_turns 长度对齐，question 必须就是最后一轮
        if c.turns:
            if len(c.expect_turns) != len(c.turns):
                errors.append(
                    f"{c.id}: len(expect_turns)={len(c.expect_turns)} 与 len(turns)={len(c.turns)} 不等")
            if c.question != c.turns[-1]:
                # 不在这里把 question 改成 turns[-1]：静默改题面会让历史报告对不上
                errors.append(f"{c.id}: question 必须等于 turns[-1]（{c.turns[-1]!r}），实际 {c.question!r}")
            for i, spec in enumerate(c.expect_turns):
                if not _expect_turn_ok(spec):
                    errors.append(f"{c.id}: expect_turns[{i}]={spec!r} 不是 exec/refusal/any/inherit:<regex>")
        elif c.expect_turns:
            errors.append(f"{c.id}: expect_turns 只在多轮题上有效（turns 为空）")

        # 3. 数据集：名字必须已知，或是一个存在的绝对路径
        for field_name in ("dataset", "gold_dataset"):
            value = getattr(c, field_name)
            if not value:
                continue
            if value in DATASETS:
                continue
            if os.path.isabs(value) and os.path.exists(value):
                continue
            errors.append(f"{c.id}: {field_name}={value!r} 既不在 DATASETS 里也不是存在的绝对路径")

        # 4. 变体必须指得到基线题
        if c.variant_of and c.variant_of not in known_ids:
            errors.append(f"{c.id}: variant_of={c.variant_of!r} 在本批用例里不存在")
        if c.variant_kind and not c.variant_of:
            errors.append(f"{c.id}: 有 variant_kind 却没有 variant_of")

        # 6. 枚举字段写错会静默失效，这里挡掉
        if c.expect_kind not in EXPECT_KINDS:
            errors.append(f"{c.id}: expect_kind={c.expect_kind!r} 不在 {sorted(EXPECT_KINDS - {''})}")
        if c.gold_kind not in GOLD_KINDS:
            errors.append(f"{c.id}: gold_kind={c.gold_kind!r} 不在 {sorted(GOLD_KINDS - {''})}")
        if not c.expect_refusal and c.expect_kind == "refusal":
            errors.append(f"{c.id}: expect_kind=refusal 与 expect_refusal=False 矛盾")

    for cid, n in seen.items():
        if n > 1:
            errors.append(f"{cid}: id 重复出现 {n} 次")

    return errors
