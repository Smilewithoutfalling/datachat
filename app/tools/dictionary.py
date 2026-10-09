"""数据字典 RAG（BM25 词法检索）。

为什么是 BM25：DeepSeek 没有提供 embedding 接口，BM25 纯词法、零网络依赖、
几毫秒返回，对"列名 / 字段中文说明"这种短文本检索足够好。

用法：每个 CSV 旁可放一个同名 .dict.csv（两列：field,description）。
提问时用 retrieve_notes 检索最相关的几条字段说明，作为**独立的 field_notes**
交给 planner/codegen/reviewer（或 ReAct 的系统提示），帮模型把口语化问法对应到真实列名。

B04：旧的 augment_question 把字段说明拼进 question，planner/codegen/日志/评测拿到的都是被污染的问题，
也无法单独衡量 RAG 的增益。现在 question 保持原样；augment_question 仅为兼容保留，内核不再使用。
字典内容同样来自用户文件，进 prompt 前会截断并包进数据分隔块（format_notes）。
"""
import os

import jieba
from rank_bm25 import BM25Okapi

from app.tools.csv_io import read_csv
from app.tools.schema import clip, data_block

MAX_DESC_CHARS = 200     # 单条字段说明最长字符数


def _tok(text: str):
    return [w for w in jieba.lcut(str(text)) if w.strip()]


def dict_path_for(df_path: str) -> str:
    """data/sample.csv -> data/sample.dict.csv"""
    stem, _ = os.path.splitext(df_path)
    return stem + ".dict.csv"


class DictRetriever:
    def __init__(self, entries):
        # entries: list of (field, description)
        self.entries = entries
        docs = [f"{f} {d}" for f, d in entries]
        self._bm25 = BM25Okapi([_tok(x) for x in docs])

    def search(self, query: str, k: int = 3):
        scores = self._bm25.get_scores(_tok(query))
        ranked = sorted(zip(scores, self.entries), key=lambda x: x[0], reverse=True)
        return [e for s, e in ranked[:k] if s > 0]


def load_retriever(df_path: str):
    """若存在同名 .dict.csv 则构建检索器，否则返回 None。"""
    path = dict_path_for(df_path)
    if not os.path.exists(path):
        return None
    d = read_csv(path)
    if "field" not in d.columns or "description" not in d.columns:
        return None
    d = d.dropna(subset=["field", "description"])
    entries = list(zip(d["field"].astype(str), d["description"].astype(str)))
    if not entries:
        return None
    return DictRetriever(entries)


def augment_question(question: str, retriever, k: int = 3) -> str:
    """把检索到的字段说明拼到问题前；无检索器或无命中则原样返回。"""
    if retriever is None:
        return question
    hits = retriever.search(question, k=k)
    if not hits:
        return question
    lines = "\n".join(f"- {f}：{d}" for f, d in hits)
    return f"[相关字段说明]\n{lines}\n\n[用户问题] {question}"


def retrieve_notes(question: str, retriever, k: int = 3):
    """返回检索到的 [(field, description), ...]；无检索器或无命中返回空列表。"""
    if retriever is None:
        return []
    return [(clip(f, 64), clip(d, MAX_DESC_CHARS)) for f, d in retriever.search(question, k=k)]


def format_notes(notes) -> str:
    """把字段说明格式化成 prompt 片段；无命中返回"（无）"。"""
    if not notes:
        return "（无）"
    return data_block("\n".join(f"- {f}：{d}" for f, d in notes))
