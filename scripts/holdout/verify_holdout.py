"""在留出集上算标准答案，产出 `answers.json`（`run_holdout.py` 读的那个）。

## 为什么要有这个脚本

`run_holdout.py` 执行 `EvalCase.ground_truth` 取期望值，而那段代码跑在**脏化表**上
（`EvalRunner.frame()` 读的就是 agent 看的那份）。所以 `ground_truth` 必须用脏化表的列名。

但"标准答案"不能只由脏化表自己算 —— 那样万一脏化改了数值，题目和答案会一起错，而且
错得自洽，跑多少遍都发现不了。所以每条答案可以附一段 `raw_code`：同一件事在**原始数据**
（英文列名、未脏化）上再算一遍，两边的值必须一致，不一致就拒绝写出 `answers.json`。

原始数据从题库目录的 `_cache/air.zip` 里读：外层包 → 内层 `PRSA2017_*.zip` → 12 个站点 CSV
纵向合并。这段路径与 `build_holdout_data.py` 的 `load_raw()` 一致，但**两边不共用函数**：
共用就等于"用同一份实现核对它自己"。

## 输入（题库目录）

- `questions.json`   题面（`run_holdout.py` 读）
- `answers_spec.json`  题号 → `{"code": "...", "raw_code": "...", "note": "..."}`

## 输出

- `answers.json`    题号 → `{"ground_truth": ..., "alt": [...], "note": ...}`
                    `note` 里记下算出来的值，方便人工扫一眼就发现明显的错。

## `code` / `raw_code` 的写法

一段 Python，最后把答案赋给 `result`。可用变量：

    pd     pandas
    df     单表题：脏化表（code 用）或原始表（raw_code 用）
    dfs    多表题：表名 → DataFrame 的字典；**两个数据源的表名相同**，
           列名不同 —— `dfs['房源']['每晚价格']`（脏化）vs `dfs['房源']['price']`（原始）

单表题只注入 `df`，多表题只注入 `dfs`，**不同时给**：写错表名时应当立刻 NameError，
而不是"恰好也能跑"。

两边列名不同（脏化表是中文列名 + `监测时间` 字符串；原始是 `PM2.5`/`TEMP`/`year` 分列），
这不是麻烦，是刻意的 —— 它逼你分别写一遍，而不是复制粘贴。

    "code":     "v = pd.to_numeric(df['PM2.5'], errors='coerce'); result = round(v.mean(), 2)"
    "raw_code": "result = round(df['PM2.5'].mean(), 2)"
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.tools.dataset import load_data  # noqa: E402

AIR_INNER = "PRSA2017_Data_20130301-20170228.zip"


def sha256_of(obj) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run(code: str, data):
    """执行答案代码。`data` 是单表 DataFrame 时注入 `df`，是多表 dict 时注入 `dfs`。

    两个变量**不同时注入** —— 单表题里写 `dfs[...]` 应该立刻 NameError，
    而不是"恰好也能跑"。这条是刻意的：它让题面写错表名时当场暴露。
    """
    ns = {"pd": pd}
    if isinstance(data, dict):
        ns["dfs"] = data
    else:
        ns["df"] = data
    exec(compile(code, "<answer>", "exec"), ns)     # noqa: S102 —— 可信代码，与 verify_gate.py 同
    if "result" not in ns:
        raise RuntimeError("代码里没有给 result 赋值")
    return ns["result"]


def load_raw(bank: str, name: str):
    """原始数据（未脏化）。单表返回 DataFrame，多表返回 dict。"""
    if name == "air":
        zpath = os.path.join(bank, "data", "_cache", "air.zip")
        if not os.path.exists(zpath):
            sys.exit(f"找不到原始数据 {zpath}；先跑 build_holdout_data.py")
        with zipfile.ZipFile(zpath) as z:
            inner = z.read(AIR_INNER)
        frames = []
        with zipfile.ZipFile(io.BytesIO(inner)) as z:
            for n in sorted(x for x in z.namelist() if x.lower().endswith(".csv")):
                frames.append(pd.read_csv(io.BytesIO(z.read(n))))
        return pd.concat(frames, ignore_index=True)

    if name == "rental":
        # 多表：键用**中文表名**，与 agent 看到的一致（`dfs['房源']`）。
        # 列名保持英文原文 —— 这是 raw_code 存在的意义：换一套列名再算一遍。
        cache = os.path.join(bank, "data", "_cache", "insideairbnb")
        if not os.path.isdir(cache):
            sys.exit(f"找不到原始数据 {cache}；先跑 build_holdout_multi.py 并放好缓存")
        return {
            "房源": pd.read_csv(os.path.join(cache, "listings.csv.gz"), low_memory=False),
            "可订日历": pd.read_csv(os.path.join(cache, "calendar.csv.gz"), low_memory=False),
            "评论": pd.read_csv(os.path.join(cache, "reviews.csv.gz"), low_memory=False),
            "社区": pd.read_csv(os.path.join(cache, "neighbourhoods.csv"), low_memory=False),
        }
    sys.exit(f"不认识的 dataset: {name}")


def load_dirty(bank: str, spec: dict, name: str):
    """脏化数据 —— 与 agent 看到的**同一份**，而且**同一个读取函数**。

    不能自己 `pd.read_csv(..., dtype=str)`：`EvalRunner.frame()` 走的是
    `app.tools.dataset.load_data`，类型是推断出来的（`房源编号` 是 int、`每晚价格` 因为带
    `$` 才是 str）。两边读法不一致，标准答案按字符串算、agent 按数值算，答案会分叉，
    而这种分叉在核对阶段看不出来 —— 只有真跑模型才会暴露。
    """
    rel = (spec.get("datasets") or {}).get(name)
    if not rel:
        sys.exit(f"questions.json 的 datasets 里没有 {name}")
    p = rel if os.path.isabs(rel) else os.path.join(bank, rel)
    if not os.path.exists(p):
        sys.exit(f"找不到脏化数据 {p}；先跑 build_holdout_*.py")
    data, _ = load_data(p)
    return data


def same(a, b) -> bool:
    """两个答案是否等价。数值按 1e-6 容差比，其余按 repr 比。"""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        return a.equals(b)
    return repr(a) == repr(b)


def main() -> None:
    ap = argparse.ArgumentParser(description="在留出集上算标准答案")
    ap.add_argument("--dir", required=True, help="题库目录")
    ap.add_argument("--write", action="store_true", help="写出 answers.json（默认只核对不写）")
    args = ap.parse_args()

    bank = os.path.abspath(args.dir)
    qpath = os.path.join(bank, "questions.json")
    spath = os.path.join(bank, "answers_spec.json")
    for p in (qpath, spath):
        if not os.path.exists(p):
            sys.exit(f"缺少 {p}")
    with open(qpath, encoding="utf-8") as f:
        qspec = json.load(f)
    with open(spath, encoding="utf-8") as f:
        sspec = json.load(f)

    questions = qspec["questions"]
    qids = [q["id"] for q in questions]
    qmap = {q["id"]: q for q in questions}
    specs = sspec.get("answers") or {}
    missing = [i for i in qids if i not in specs]
    extra = [i for i in specs if i not in qids]
    if missing or extra:
        sys.exit(f"题号不一致 —— questions 缺答案：{missing}；answers_spec 多出：{extra}")

    dirty_cache, raw_cache = {}, {}
    out, bad = {}, []
    for qid in qids:
        s = specs[qid]
        name = qmap.get(qid, {}).get("dataset", "air")
        if name not in dirty_cache:
            dirty_cache[name] = load_dirty(bank, qspec, name)
            raw_cache[name] = load_raw(bank, name)
            n = len(dirty_cache[name]) if not isinstance(dirty_cache[name], dict) else \
                sum(len(v) for v in dirty_cache[name].values())
            print(f"{name}: 脏化 {n} 行")
        dirty, raw = dirty_cache[name], raw_cache[name]
        try:
            got = run(s["code"], dirty)
        except Exception as e:                                    # noqa: BLE001
            bad.append(f"{qid}: code 执行失败 —— {type(e).__name__}: {e}")
            continue

        note = s.get("note", "")
        claim = s.get("expect")
        line = f"  {qid:8} {str(got)[:60]}"
        if claim is not None and not same(got, claim):
            bad.append(f"{qid}: spec 里写的 expect={claim!r} 与实际算出的 {got!r} 不一致")
            line += f"   ⚠️ 与 expect 不符"

        if s.get("raw_code"):
            try:
                rr = run(s["raw_code"], raw)
            except Exception as e:                                # noqa: BLE001
                bad.append(f"{qid}: raw_code 执行失败 —— {type(e).__name__}: {e}")
                continue
            if not same(got, rr):
                bad.append(f"{qid}: 脏化表算出 {got!r}，原始表算出 {rr!r} —— 脏化改了数值？")
                line += "   ⚠️ 两表不一致"
            else:
                line += "   ✓ 两表一致"
        else:
            line += "   （无 raw_code，未交叉核对）"
        print(line)
        out[qid] = {"ground_truth": s["code"], "note": f"{note}｜算出：{got}".strip("｜")}
        if s.get("alt"):
            out[qid]["alt"] = s["alt"]

    print()
    if bad:
        sys.exit("核对失败，不写 answers.json：\n" + "\n".join("  " + b for b in bad))

    if not args.write:
        print("核对通过。加 --write 才会写 answers.json。")
        return
    payload = {"questions_sha256": sha256_of(questions), "answers": out}
    with open(os.path.join(bank, "answers.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已写 {os.path.join(bank, 'answers.json')}（{len(out)} 题，questions_sha256={payload['questions_sha256'][:12]}）")


if __name__ == "__main__":
    main()
