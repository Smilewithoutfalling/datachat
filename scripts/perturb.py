"""扰动生成器（EV-B6）：同一份逻辑数据换形态，测鲁棒性，不是加新题。

用法：
    python scripts/perturb.py --case agg_001 --kind total_row --out outputs/perturb/
产出：
    outputs/perturb/agg_001.total_row.dirty.csv   # agent 看的
    outputs/perturb/agg_001.total_row.clean.csv   # gold 算的（与原表逐字节等价）
    stdout 打一条可直接粘进 cases 的 EvalCase 片段（不自动写进 cases.py —— id 冲突与
    evalset 指纹变更必须由人显式过一次，见 docs/eval/perturb.md）。

clean 与 dirty 的关系是**语义等价**：total_row 的 clean 就是去掉合计行的原表，
不是另一份数据 —— 期望值变了就不是测扰动而是测新题了。

9 种变体的"期望"在规格表里（表头识别 / 类型转换 / 剔除汇总行 / 列名消歧 / 空列 / 尾部噪声）。
纯 pandas + csv，不新增依赖。
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

KINDS = ("merged_header", "two_row_header", "total_row", "thousand_sep", "percent_str",
         "date_compact", "dup_columns", "empty_col", "footer_note")


# ---------------------------------------------------------------- 9 种变换
# 输入输出都是 (header: list[str], rows: list[list[str]])，纯文本进出，
# 不用 pandas 读回写 —— pandas 会自作主张改类型，扰动就测不到原始形态了。

def _numeric_cols(header, rows):
    """哪些列是数字列：非空值全是数字即算（允许空单元格，如未支付订单的金额）。"""
    out = []
    for j, col in enumerate(header):
        vals = [r[j] for r in rows if j < len(r) and r[j] != ""]
        if vals and all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vals):
            out.append(j)
    return out


def _num(v: str) -> float:
    return float(v) if v != "" else 0.0


def v_merged_header(header, rows):
    """首行做合并单元格：导出系统最爱干的事 —— 第一行是横跨全表的标题。"""
    title = [f"{header[0]}相关数据（导出于报表系统）", *[""] * (len(header) - 1)]
    return [title, header, *rows]


def v_two_row_header(header, rows):
    """两行表头：第 1 行大类、第 2 行子列，第 3 行起才是数据。"""
    top = [header[0]] + [f"指标-{c}" if i else c for i, c in enumerate(header[1:])]
    return [top, header, *rows]


def v_total_row(header, rows):
    """末尾插一行「合计」：数字列求和（空单元格按 0），文本列写「合计」。"""
    total = []
    num_cols = set(_numeric_cols(header, rows))
    for j, col in enumerate(header):
        if j in num_cols:
            total.append(str(round(sum(_num(r[j]) for r in rows), 2)))
        elif j == 0:
            total.append("合计")
        else:
            total.append("")
    return [header, *rows, total]


def v_thousand_sep(header, rows):
    """数值列加千分位字符串（空单元格保持空）。写 csv 时带引号，否则 pandas 读成数字就测不到了。"""
    num_cols = set(_numeric_cols(header, rows))
    out_rows = []
    for r in rows:
        r = list(r)
        for j in num_cols:
            if r[j] == "":
                continue
            v = float(r[j])
            r[j] = f"{int(v):,}" if v == int(v) else f"{v:,.2f}"
        out_rows.append(r)
    return [header, *out_rows]


def v_percent_str(header, rows):
    """把最后一个数值列写成百分数字符串（12.3%；空单元格保持空）。"""
    num_cols = _numeric_cols(header, rows)
    if not num_cols:
        raise SystemExit("percent_str 需要至少一个纯数字列")
    target = num_cols[-1]
    out_rows = []
    for r in rows:
        r = list(r)
        if r[target] != "":
            r[target] = f"{float(r[target]):.1f}%"
        out_rows.append(r)
    return [header, *out_rows]


def v_date_compact(header, rows):
    """ISO 日期 → 紧凑数字（2024-01-05 → 20240105）。"""
    date_cols = [j for j, col in enumerate(header)
                 if rows and all(ISO_DATE.fullmatch(r[j]) for r in rows if j < len(r))]
    if not date_cols:
        raise SystemExit("date_compact 需要至少一列 ISO 日期（YYYY-MM-DD）")
    out_rows = []
    for r in rows:
        r = list(r)
        for j in date_cols:
            r[j] = r[j].replace("-", "")
        out_rows.append(r)
    return [header, *out_rows]


def v_dup_columns(header, rows):
    """两列同名（把第 2 列复制并重名）。pandas 读进来会自动叫 `xxx.1`，测列名消歧。"""
    j = 1 % len(header)
    return [[header[0], header[j], *header[1:]],
            *[[r[0], r[j], *r[1:]] for r in rows]]


def v_empty_col(header, rows):
    """插一列全空（放倒数第二位，命名成备注风格的空表头）。"""
    k = len(header) - 1
    new_header = [*header[:k], "", *header[k:]]
    return [new_header, *([*r[:k], "", *r[k:]] for r in rows)]


def v_footer_note(header, rows):
    """末尾两行备注（含逗号，带引号），测尾部噪声剔除。"""
    note1 = [f"注：以上共 {len(rows)} 行，数据,来源为业务系统导出", *[""] * (len(header) - 1)]
    note2 = [f"制表人: {header[0]}-组, 仅供内部使用", *[""] * (len(header) - 1)]
    return [header, *rows, note1, note2]


TRANSFORM = {
    "merged_header": v_merged_header, "two_row_header": v_two_row_header,
    "total_row": v_total_row, "thousand_sep": v_thousand_sep,
    "percent_str": v_percent_str, "date_compact": v_date_compact,
    "dup_columns": v_dup_columns, "empty_col": v_empty_col,
    "footer_note": v_footer_note,
}

# 千分位 / 备注行必须带引号写，否则逗号会破坏 CSV 结构或被 pandas 读成数字
QUOTE_ALWAYS = {"thousand_sep", "footer_note"}


def _write_csv(path, table, quote_all=False):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL)
        w.writerows(table)


def _read_table(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.reader(f) if any(c.strip() for c in row)]


def snippet(case, kind, dirty, clean) -> str:
    """打印一条可直接粘进 cases 的 EvalCase 片段。id 要人自己起 —— 自动起会撞号。"""
    return (
        f'EvalCase(id="pert_XXX", category="{case.category}",\n'
        f'         question={case.question!r},\n'
        f'         ground_truth={case.ground_truth!r},\n'
        f'         keywords={case.keywords!r},\n'
        f'         dataset={dirty!r},          # 脏表：agent 看\n'
        f'         gold_dataset={clean!r},   # 干净表：gold 算\n'
        f'         variant_of="{case.id}", variant_kind="{kind}"),'
    )


def main():
    ap = argparse.ArgumentParser(description="EV-B6 扰动生成器")
    ap.add_argument("--case", required=True, help="基线题 id（如 agg_001）")
    ap.add_argument("--kind", required=True, choices=KINDS)
    ap.add_argument("--out", default=os.path.join(REPO, "outputs", "perturb"))
    args = ap.parse_args()

    from app.eval.cases import ALL_CASES
    matches = [c for c in ALL_CASES if c.id == args.case]
    if not matches:
        raise SystemExit(f"找不到用例 {args.case!r}，可选前缀："
                         f"{sorted({c.id.split('_')[0] for c in ALL_CASES})}")
    case = matches[0]
    if case.turns:
        raise SystemExit("扰动不支持多轮题（成本翻倍且归因困难）")

    from app.tools.dataset import load_data
    src = case.gold_dataset or case.dataset
    if src not in (case.dataset, case.gold_dataset):
        src = case.dataset
    from app.eval.runner import EvalRunner  # 仅复用 datasets 解析，不执行评测
    path = EvalRunner().datasets.get(case.dataset, case.dataset)
    data, _ = load_data(path)
    if not isinstance(data, __import__("pandas").DataFrame):
        raise SystemExit("扰动只支持单表题（多表的表头语义属于表本身，不适合换形态）")

    header = [str(c) for c in data.columns]
    rows = [[("" if v is None or (isinstance(v, float) and v != v) else (
        f"{v:g}" if isinstance(v, float) else str(v))) for v in rec]
            for rec in data.itertuples(index=False, name=None)]

    os.makedirs(args.out, exist_ok=True)
    stem = f"{case.id}.{args.kind}"
    clean_path = os.path.join(args.out, f"{stem}.clean.csv")
    dirty_path = os.path.join(args.out, f"{stem}.dirty.csv")
    _write_csv(clean_path, [header, *rows])
    _write_csv(dirty_path, TRANSFORM[args.kind](header, rows), quote_all=args.kind in QUOTE_ALWAYS)

    print(snippet(case, args.kind,
                  os.path.relpath(dirty_path, REPO).replace(os.sep, "/"),
                  os.path.relpath(clean_path, REPO).replace(os.sep, "/")))
    print(f"\n# dirty: {dirty_path}\n# clean: {clean_path}")


if __name__ == "__main__":
    main()
