"""留出集（H1）数据构建：下载外部数据、合并、按闸门的办法做中文 GBK 脏化。

**只改呈现，不改数值** —— 与 `scripts/gate/build_gate_data.py` 同一条原则。标准答案由独立脚本
在**原始数据**上算，脏化只考察读入/理解能力，不会把答案泄漏进题目。

数据与题面都不进 git（`scripts/holdout/README.md` 规则 1）。输出目录由 `--out` 指定，
通常就是 `.holdout_path` 里那一行所指的目录下面的 `data/`。

用法：
    python scripts/holdout/build_holdout_data.py --out D:/datachat_holdout/data
    python scripts/holdout/build_holdout_data.py --out D:/datachat_holdout/data --check

产出：
- `空气质量/空气质量.csv`        单表组主表：12 个监测站纵向合并，420,768 行；
                                中文列名、GB18030、Excel 风格时间串、缺失值写成"未登记"
- `空气质量/空气质量_报表.csv`   报表导出变体：两行表头（分组名）+ 末尾一行合计

## 为什么合并 12 个站点

UCI 原包是 12 个 CSV（每站一个）。直接给目录会被 `load_data` 当成 12 张表，
表名是 `PRSA_Data_Aotizhongxin_20130301-20170228` 这种 —— 题面里写不出来，模型也很难猜。
合并成一张表、加一列"监测站"，是**同一份数据换一种组织方式**，单元格的值一个没动。

## 与本文件配套的原始数据

    air.zip  sha256[:12] = b04da438b2f3   （UCI 501，外层包）
    内层 zip sha256[:12] = d1b9261c5413   （PRSA2017_Data_20130301-20170228.zip）

外层包里混了 `data.csv` / `test.csv`（与本数据集无关的示例文件），真正的数据在内层 zip。
这一点写在 `scripts/gate` 的对应脚本里没有先例 —— 那边 UCI 352 是单层包。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

import pandas as pd

AIR_URL = "https://archive.ics.uci.edu/static/public/501/beijing+multi+site+air+quality+data.zip"
AIR_ZIP_SHA12 = "b04da438b2f3"
AIR_INNER = "PRSA2017_Data_20130301-20170228.zip"

ENCODING = "gb18030"

# 原列名 → 中文列名。PM2.5 / PM10 保留原名：它们是通用写法，硬翻成"细颗粒物"反而增加歧义。
RENAME = {
    "No": "序号", "PM2.5": "PM2.5", "PM10": "PM10", "SO2": "二氧化硫", "NO2": "二氧化氮",
    "CO": "一氧化碳", "O3": "臭氧", "TEMP": "气温", "PRES": "气压", "DEWP": "露点温度",
    "RAIN": "降水量", "wd": "风向", "WSPM": "风速", "station": "监测站",
}
NUMERIC = ["PM2.5", "PM10", "二氧化硫", "二氧化氮", "一氧化碳", "臭氧",
           "气温", "气压", "露点温度", "降水量", "风速"]


def sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def excel_style(y, m, d, h) -> pd.Series:
    """2013-03-01 00 时 → '2013/3/1 0'（国内 Excel 另存 CSV 的常见样子：不补零）。"""
    return (y.astype(str) + "/" + m.astype(str) + "/" + d.astype(str) + " " + h.astype(str))


def write_csv(df: pd.DataFrame, path: str, header_rows: list[list[str]] | None = None,
              footer: list[str] | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = df.to_csv(index=False, lineterminator="\r\n")
    head = "".join(",".join(r) + "\r\n" for r in (header_rows or []))
    tail = (",".join(footer) + "\r\n") if footer else ""
    with open(path, "wb") as f:
        f.write((head + body + tail).encode(ENCODING))
    raw = open(path, "rb").read()
    print(f"  {path}  {len(df)} 行  {len(raw) / 1e6:.1f} MB  sha256[:12]={sha12(raw)}")


def load_raw(zpath: str) -> pd.DataFrame:
    """从外层 zip 里的内层 zip 读 12 个站点，纵向合并。不改任何单元格的值。"""
    with zipfile.ZipFile(zpath) as z:
        inner = z.read(AIR_INNER)
    frames = []
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 12:
            sys.exit(f"内层 zip 里应有 12 个 CSV，实际 {len(names)} 个：{names}")
        for n in sorted(names):
            frames.append(pd.read_csv(io.BytesIO(z.read(n))))
    df = pd.concat(frames, ignore_index=True)
    print(f"  合并 {len(frames)} 个站点，{len(df)} 行")
    return df


def dirty(raw: pd.DataFrame) -> pd.DataFrame:
    """只改呈现：列名中文化、时间拼成 Excel 串、缺失写成"未登记"。值一个不动。"""
    df = raw.copy()
    df["监测时间"] = excel_style(df["year"], df["month"], df["day"], df["hour"])
    df = df.drop(columns=["year", "month", "day", "hour"])
    df = df.rename(columns=RENAME)
    # 数值列保留数字，缺失一律"未登记"；风向的空值同样处理（它是字符串列，但缺失语义一样）
    for c in NUMERIC:
        df[c] = df[c].map(lambda v: "未登记" if pd.isna(v) else v)
    df["风向"] = df["风向"].map(lambda v: "未登记" if pd.isna(v) else v)
    order = ["序号", "监测时间", "监测站", "PM2.5", "PM10", "二氧化硫", "二氧化氮",
             "一氧化碳", "臭氧", "气温", "气压", "露点温度", "降水量", "风向", "风速"]
    return df[order]


def build(out: str) -> None:
    zpath = os.path.join(out, "_cache", "air.zip")
    if not os.path.exists(zpath):
        os.makedirs(os.path.dirname(zpath), exist_ok=True)
        print(f"下载 {AIR_URL} …")
        data = fetch(AIR_URL)
        got = sha12(data)
        if got != AIR_ZIP_SHA12:
            sys.exit(f"air.zip 指纹不符：{got} != {AIR_ZIP_SHA12}（上游改了包，先核对再继续）")
        with open(zpath, "wb") as f:
            f.write(data)
        print(f"  已存 {zpath}  sha256[:12]={got}")

    df = dirty(load_raw(zpath))
    d = os.path.join(out, "空气质量")
    write_csv(df, os.path.join(d, "空气质量.csv"))

    # 报表变体：第一行是分组名（合并单元格导出后的样子，非本组列留空），末尾一行合计。
    # 合计只对"求和有意义"的列写值（污染物与降水量），气温/气压这类留空 —— 写个假的会更糟。
    groups = ["基本信息", "", "", "污染物浓度（微克/立方米）", "", "", "", "", "",
              "气象", "", "", "", "", ""]
    total = ["合计", "", ""] + [str(int(pd.to_numeric(df[c], errors="coerce").sum())) if c != "臭氧"
                                else "" for c in ["PM2.5", "PM10", "二氧化硫", "二氧化氮",
                                                  "一氧化碳", "臭氧"]] + ["", "", "", "", "", ""]
    write_csv(df, os.path.join(d, "空气质量_报表.csv"), header_rows=[groups], footer=total)


def check(out: str) -> list[str]:
    """只读校验：文件在不在、行数对不对、能不能按 GB18030 读回来。返回问题列表，空 = 通过。"""
    problems = []
    for name, rows in (("空气质量.csv", 420768), ("空气质量_报表.csv", 420768)):
        p = os.path.join(out, "空气质量", name)
        if not os.path.exists(p):
            problems.append(f"缺失：{p}")
            continue
        try:
            df = pd.read_csv(p, encoding=ENCODING, dtype=str, skiprows=1 if "报表" in name else 0)
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"读不回来（{ENCODING}）：{p}  {e}")
            continue
        n = len(df) - (1 if "报表" in name else 0)               # 报表变体末尾有合计行
        if n != rows:
            problems.append(f"行数不符：{name}  期望 {rows}  实际 {n}")
        else:
            print(f"  ok  {name}  {n} 行")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="留出集（H1）数据构建")
    ap.add_argument("--out", required=True, help="输出目录（不含数据本身进 git）")
    ap.add_argument("--check", action="store_true", help="只校验现场：不下载、不写文件")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if args.check:
        problems = check(out)
        if problems:
            sys.exit("校验失败：\n" + "\n".join("  " + p for p in problems))
        print("校验通过。")
        return
    build(out)


if __name__ == "__main__":
    main()
