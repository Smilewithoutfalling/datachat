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
PER_TABLE_K = 3          # 多表数据集：每张表最多取几条
TOTAL_CAP = 15           # 多表数据集：总条数上限（5 张表各 3 条刚好 15，再多的表靠第一轮覆盖）


def _tok(text: str):
    return [w for w in jieba.lcut(str(text)) if w.strip()]


def dict_path_for(df_path: str) -> str:
    """data/sample.csv -> data/sample.dict.csv"""
    stem, _ = os.path.splitext(df_path)
    return stem + ".dict.csv"


class DictRetriever:
    """字段说明检索器。

    单表：全局 top-k，与 B04 时代逐字节一致。
    多表：**按表分组检索、轮转合并**。合并所有表的条目做全局 top-k 时，词面最像的
    少数条目（往往是与答案无关的主键，如"订单表 order_id：整行重复需去重"）会霸占
    全部名额，而"status 前后带空格需 strip"这类真正决定答案对错的规则一次都进不了
    prompt —— 实测 biz 11 道错题的三条关键规则召回 0/11。分组后每张表各占 1 条起，
    低分表不会被高分表挤掉。
    """

    def __init__(self, entries, groups=None):
        # entries: list of (field, description)
        # groups:  [(表名, [(field, description), ...]), ...]，单表时为 None
        self.entries = entries
        docs = [f"{f} {d}" for f, d in entries]
        self._bm25 = BM25Okapi([_tok(x) for x in docs])
        # 只有真·多表（≥2 张表各自有字典）才启用分组检索；否则保持全局 top-k，
        # 让单表数据集的 prompt 一个字节都不变。
        self._groups = None
        if groups and len(groups) > 1:
            self._groups = [
                (name, es, BM25Okapi([_tok(f"{f} {d}") for f, d in es]))
                for name, es in groups
            ]

    @staticmethod
    def _rank(bm25, entries, tokens):
        """组内按 BM25 分数排序，只保留与 query 有词面交集的条目。

        不能用 `score > 0` 判相关：BM25 的 IDF 在小组里会变负 —— 一张表只有一两条
        字典，query 词又出现在每条里时，df≈N 使 `log((N-df+0.5)/(df+0.5))` 为负，
        rank_bm25 的 epsilon 兜底也救不回来（它按平均 IDF 缩放，平均也是负的）。
        那会把整张表的条目当成「无关」全丢掉，分组就白做了。
        词面交集是可靠的：有共同词才可能相关，排序仍交给 BM25。
        """
        scores = bm25.get_scores(tokens)
        q = set(tokens)
        docs = [set(_tok(f"{f} {d}")) for f, d in entries]
        ranked = sorted(zip(scores, docs, entries), key=lambda x: x[0], reverse=True)
        return [e for _s, doc, e in ranked if q & doc]

    def search(self, query: str, k: int = 3):
        tokens = _tok(query)
        if self._groups is None:
            # 单表：逐字保留 B04 的写法 —— 先截前 k 再过滤零分，与分组路径的
            # "先过滤再截"在边界上结果不同（top-k 里混进零分时条数会少一条），
            # 而单表 prompt 必须与改动前逐字节一致。
            scores = self._bm25.get_scores(tokens)
            ranked = sorted(zip(scores, self.entries), key=lambda x: x[0], reverse=True)
            return [e for s, e in ranked[:k] if s > 0]
        # 多表：k 是"每张表最多几条"的上限（再被 PER_TABLE_K 夹住），总数受 TOTAL_CAP 约束。
        per = min(k, PER_TABLE_K)
        ranked = [self._rank(bm25, es, tokens)[:per] for _name, es, bm25 in self._groups]
        out: list = []
        for i in range(per):
            for group in ranked:            # 轮转：第 i 轮让每张表各出其第 i+1 条
                if i < len(group) and len(out) < TOTAL_CAP:
                    out.append(group[i])
        return out


def _entries(path: str, prefix: str = ""):
    if not os.path.exists(path):
        return []
    d = read_csv(path)
    if "field" not in d.columns or "description" not in d.columns:
        return []
    d = d.dropna(subset=["field", "description"])
    return [(prefix + f, desc) for f, desc in zip(d["field"].astype(str), d["description"].astype(str))]


def load_retriever(df_path):
    """若存在同名 .dict.csv 则构建检索器，否则返回 None。
    多表数据集（目录或路径列表）：每张表的 .dict.csv 各自成组（字段写成"表名.字段"），
    检索时按表分组（见 DictRetriever）；没有字典的表不参与分组。"""
    from app.tools.dataset import table_paths
    tables = table_paths(df_path)
    groups = None
    if tables is None:
        entries = _entries(dict_path_for(os.fspath(df_path)))
    else:
        groups = [(name, es) for name, p in tables if (es := _entries(dict_path_for(p), f"{name}."))]
        entries = [e for _name, es in groups for e in es]
    if not entries:
        return None
    return DictRetriever(entries, groups=groups)


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
