"""数据字典 RAG（BM25 词法检索）。

为什么是 BM25：DeepSeek 没有提供 embedding 接口，BM25 纯词法、零网络依赖、
几毫秒返回，对"列名 / 字段中文说明"这种短文本检索足够好。

用法：每个 CSV 旁可放一个同名 .dict.csv（两列：field,description）。
提问前用 augment_question 把最相关的几条字段说明拼到问题前面，
帮助模型把口语化的问法对应到真实列名。
"""
import os

import jieba
from rank_bm25 import BM25Okapi

from app.tools.csv_io import read_csv


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
