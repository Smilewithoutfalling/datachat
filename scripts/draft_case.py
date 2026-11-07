"""👎 → 草稿用例（EV-D4）：把用户的一次差评变成一条待补 gold 的草稿。

这是**唯一会把用户数据写出仓库的脚本**，所以默认行为是"什么都别写出去"：

- 默认只输出**问题原文 + 数据集的列名与形状 + 反馈备注**，不输出答案、不输出 result_text、
  不输出代码。问题原文必须留——它就是用例本身，去掉就没有题了。
- `--raw` 才把原始答案的前 200 字放进 note，并在 stderr 打警告。用之前想清楚：那段文字里
  很可能有用户数据的具体数值。
- 数据库**只读打开**（`mode=ro`）：这个脚本没有任何写库路径，跑坏了也动不了用户数据。

草稿的 `ground_truth` 恒为空——**不要自动生成 gold**。标准答案要人看着数据写，猜出来的
gold 会让整道题变成"测模型和猜测是否一致"，比没有这道题更糟。

用法见 `docs/eval/drafting.md`；规格见 `docs/roadmap/eval-system-spec.md` §EV-D4。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/ 的上一层
sys.path.insert(0, ROOT)

RAW_LIMIT = 200


def _connect_ro(path: str) -> sqlite3.Connection:
    """只读打开。WAL 库在 `mode=ro` 下只读 -wal，不会写任何东西。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据库不存在：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def fetch(conn, message_id: str):
    """取助手消息、它前面那条用户问题、以及反馈行。任何一项缺都返回 None 由调用方报错。"""
    msg = _one(conn, "select * from messages where id = ?", (message_id,))
    if msg is None:
        return None, None, None
    fb = _one(conn, "select * from feedback where message_id = ?", (message_id,))
    ask = _one(conn, """select * from messages
                        where session_id = ? and role = 'user' and created_at <= ?
                        order by created_at desc limit 1""", (msg["session_id"], msg["created_at"]))
    return msg, ask, fb


def public_dataset(dataset: str) -> str:
    """只留文件名/目录名。真实记录里的 `dataset` 是绝对路径（`C:\\Users\\<用户名>\\...`），
    原样写进草稿等于把安装路径和用户名带进仓库——这条和 EV-B10 出境审计的 ④ 同一条理由。"""
    if not dataset:
        return ""
    return os.path.basename(os.path.normpath(dataset))


def schema_of(dataset: str) -> dict | None:
    """数据集的列名与形状。**只取结构，不取值**——这是默认脱敏的全部内容。"""
    if not dataset:
        return None
    try:
        from app.tools.dataset import load_data
        df, _ = load_data(dataset)
    except (ImportError, ModuleNotFoundError):
        raise                           # 环境/路径坏了不是"数据不在本机"，静默吞会把 bug 藏起来
    except Exception:                   # noqa: BLE001 —— 数据不在本机是常态，不是错误
        return None
    if isinstance(df, dict):                # 多表：每张表各给一份形状
        return {"tables": {name: {"columns": [str(c) for c in d.columns],
                                   "shape": [int(d.shape[0]), int(d.shape[1])]}
                           for name, d in sorted(df.items())}}
    return {"columns": [str(c) for c in df.columns], "shape": [int(df.shape[0]), int(df.shape[1])]}


def build_draft(message_id: str, question: str, dataset: str, fb, answer: str | None = None,
                draft_id: str = "draft_001") -> dict:
    """answer=None 是默认脱敏路径：调用方**不把答案正文传进来**，这里也就无从写出。
    answer 给字符串 = `--raw`，只留前 200 字。"""
    note_bits = ["来自 👎"]
    if fb is not None and (fb["note"] or "").strip():
        note_bits.append(f"用户备注：{fb['note'].strip()}")
    if answer is None:
        note_bits.append("原始答案已省略（--raw 输出前 200 字，会带出数据值）")
    else:
        note_bits.append(f"原始答案：{answer.strip().replace(chr(10), ' ')[:RAW_LIMIT]}")
    draft = {
        "id": draft_id,
        "question": question,
        "turns": [],
        "ground_truth": "",                 # 必须人工补，见模块 docstring
        "dataset": public_dataset(dataset),
        "note": "；".join(note_bits) + f"（message {message_id}）",
    }
    sch = schema_of(dataset)
    if sch:
        draft["schema"] = sch
    return draft


def to_yaml(d: dict, header: list[str]) -> str:
    """手写 YAML（不引 PyYAML：它不在 requirements 里，CI 装不上）。

    字符串一律用 JSON 双引号标量——YAML 的双引号标量与 JSON 兼容，中文照原样写。
    dict 走嵌套块（多表的 `schema.tables` 压成一行内联 JSON 没法读），list 走内联流式。
    """
    def emit(obj: dict, indent: int) -> list[str]:
        pad = " " * indent
        out = []
        for k, v in obj.items():
            if isinstance(v, dict) and v:
                out.append(f"{pad}{k}:")
                out.extend(emit(v, indent + 2))
            else:
                out.append(f"{pad}{k}: {json.dumps(v, ensure_ascii=False)}")
        return out

    lines = [f"# {h}" for h in header]
    lines.extend(emit(d, 0))
    return "\n".join(lines) + "\n"


def next_draft_id(out_dir: str) -> str:
    """接着目录里已有的 draft_NNN 往后编。没有就 001。"""
    try:
        names = os.listdir(out_dir)
    except OSError:
        return "draft_001"
    nums = [int(m.group(1)) for n in names if (m := re.fullmatch(r"draft_(\d+)\.ya?ml", n))]
    return f"draft_{(max(nums) + 1) if nums else 1:03d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把一条 👎 消息转成待补 gold 的草稿用例（EV-D4）")
    ap.add_argument("--db", default=os.path.join(os.getenv("LOCALAPPDATA") or
                                                 os.path.join(os.path.expanduser("~"), ".local", "share"),
                                                 "datachat", "datachat.db"),
                    help="sqlite 路径（默认与桌面版一致）")
    ap.add_argument("--message-id", required=True, help="助手消息 id（不是用户那条）")
    ap.add_argument("--out", default="", help="写到文件；不给就打到 stdout")
    ap.add_argument("--raw", action="store_true", help="把原始答案前 200 字写进 note（会带出数据值）")
    ap.add_argument("--any-rating", action="store_true", help="不要求 👎（没有反馈也出草稿）")
    a = ap.parse_args(argv)

    try:
        conn = _connect_ro(a.db)
    except (OSError, sqlite3.Error) as e:
        print(f"✗ 打不开数据库：{e}")
        return 1
    try:
        msg, ask, fb = fetch(conn, a.message_id)
    except sqlite3.Error as e:
        print(f"✗ 读库失败：{e}（是不是还没跑过桌面版？）")
        return 1
    finally:
        conn.close()

    if msg is None:
        print(f"✗ 没有这条消息：{a.message_id}")
        return 1
    if msg["role"] != "assistant":
        print(f"✗ {a.message_id} 是 {msg['role']} 消息，要传助手那条的 id")
        return 1
    rating = (fb["rating"] if fb is not None else None)
    if rating != "down" and not a.any_rating:
        got = "没有评价" if rating is None else f"评价是 {rating}"
        print(f"✗ 这条消息{got}，不是 👎。确实要出草稿就加 --any-rating")
        return 1
    rec = {}
    if msg["result_json"]:
        try:
            rec = json.loads(msg["result_json"]) or {}
        except json.JSONDecodeError:
            rec = {}                        # 损坏的记录不该让整条路走不通，只是少几个字段
    question = ((ask["content"] if ask is not None else "") or rec.get("question") or "").strip()
    if not question:
        print("✗ 找不到它前面的用户问题，result_json 里也没有 question")
        return 1

    out_dir = os.path.dirname(os.path.abspath(a.out)) if a.out else os.path.join(ROOT, "docs", "eval", "drafts")
    # 默认路径**不把答案正文交给 build_draft**——脱敏靠"不读"，不靠"读出来再擦"
    answer = msg["content"] if a.raw else None
    draft = build_draft(a.message_id, question, rec.get("dataset") or "", fb, answer=answer,
                        draft_id=next_draft_id(out_dir))
    header = [
        f"由 scripts/draft_case.py 从 👎 生成（数据库 {os.path.basename(a.db)}，message {a.message_id}）",
        "待办：补 ground_truth（pandas 代码，执行后 result = 期望结果）；确认 category / dataset；",
        "      确认这道题真的值得进集（一次差评可能是模型错，也可能是题本身有歧义）。",
    ]
    if a.raw:
        print("⚠ --raw：note 里含原始答案前 200 字，可能带出用户数据的具体数值。"
              "进仓库前先读一遍。", file=sys.stderr)
    text = to_yaml(draft, header)
    if a.out:
        os.makedirs(out_dir, exist_ok=True)
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"✅ 草稿已写 {a.out}")
        print("   下一步：补 ground_truth；补完才谈得上入集（registry 里先记 candidate）")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
