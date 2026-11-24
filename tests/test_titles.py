"""阶段 7.6 U5：会话标题（app/server/titles.py，docs/roadmap/phase76-u3u5.md §2.3 / §2.5）。

① §2.3 对照表 15 行逐行相等；② 标题 ≤ 12 字（去重后缀除外）；③ 同一数据集重名追加（2）（3），不同数据集不追加；
④ 先 PATCH 改名再首问不覆盖，首问后再问不变；⑤ X-Session-Title 解码后等于库里的标题；
⑥ PATCH 空串 = 用第一问重新生成（§4 已定 3）；⑦ sidecar 自检 imports 一项含 jieba.posseg 且真调一次 posseg.cut。
"""
import ast
import inspect
import os
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.server.app import create_app
from app.server.titles import TITLE_MAX, session_title, unique_title
from tests.test_core_analyze import wf_model

TABLE = [
    ("各地区销售额是多少", "地区销售额"),
    ("哪个品类的利润最高？", "品类利润"),
    ("华东区客单价环比变化", "华东区客单价"),
    ("按部门统计离职人数", "部门离职人数"),
    ("商品退款金额前十", "商品退款金额"),
    ("员工平均年龄是多少", "员工平均年龄"),
    ("2024年各月的订单数量趋势", "订单数量"),
    ("各城市销量", "城市销量"),
    ("哪个地区卖得最好", "哪个地区卖得最好"),
    ("看看这份数据有什么：有哪些表和字段、各列大概是什么意思、覆盖的范围，先给我一个整体概览。", "看看这份数据有什么"),
    ("找出这份数据里的异常值：哪些数值列有明显偏离的值，具体是哪几行，可能是什么原因。", "找出这份数据里的异常值"),
    ("生成你认为重要的分析图表", "生成你认为重要的分析图表"),
    ("画 5000 点", "画 5000 点"),
    ("近三个月每周新增客户数的走势如何", "近三个月每周新增客户数的"),
    (" \t\n  ", ""),
]


@pytest.mark.parametrize("question,title", TABLE)
def test_title_table(question, title):
    got = session_title(question)
    assert got == title
    assert len(got) <= TITLE_MAX


@pytest.mark.parametrize("question", [
    "全角ＡＢＣ　的销售额",                         # NFKC + 全角空格
    "a\x07b\u200f c\n\n\nd",                       # 控制字符、连续空白
    "，，开头就是标点的问题",
    "x" * 300,
    "各个大区各个城市各个门店各个品类各个渠道的销售额",
])
def test_title_is_short_and_clean(question):
    t = session_title(question)
    assert len(t) <= TITLE_MAX
    assert t == t.strip() and "\x07" not in t and "\n" not in t and "  " not in t


def test_unique_title_suffix():
    assert unique_title("城市销量", []) == "城市销量"
    assert unique_title("城市销量", ["城市销量"]) == "城市销量（2）"
    assert unique_title("城市销量", ["城市销量", "城市销量（2）"]) == "城市销量（3）"
    assert unique_title("", ["", "x"]) == ""


# ---------------------------------------------------------------- 接口
TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path / "home"), TOKEN,
                                 chat_model_factory=lambda: wf_model(["result = int(len(df))"], answer="共 15 行。")))


def _dataset(c, path):
    files = [("files", (os.path.basename(path), open(path, "rb"), "text/csv"))]
    return c.post("/datasets", files=files, data={"name": ""}, headers=H).json()["id"]


def _session(c, ds):
    return c.post("/sessions", json={"dataset_id": ds, "agent": "workflow"}, headers=H).json()["id"]


def _ask(c, sid, q):
    r = c.post(f"/sessions/{sid}/messages", json={"content": q}, headers=H)
    assert r.status_code == 200
    return r


def _title(c, sid):
    return c.get(f"/sessions/{sid}", headers=H).json()["title"]


def test_first_question_sets_title_and_header_matches_db(c, sample_path):
    ds = _dataset(c, sample_path)
    sid = _session(c, ds)
    r = _ask(c, sid, "各地区销售额是多少")
    assert unquote(r.headers["x-session-title"]) == _title(c, sid) == "地区销售额"
    assert r.headers["x-session-title"].isascii()                     # 百分号编码，HTTP 头只能是 latin-1
    r2 = _ask(c, sid, "哪个品类的利润最高？")                            # 首问之后再问：标题不变
    assert _title(c, sid) == "地区销售额" == unquote(r2.headers["x-session-title"])


def test_same_dataset_duplicates_get_numbered_other_dataset_does_not(c, sample_path, tmp_path):
    ds = _dataset(c, sample_path)
    sids = [_session(c, ds) for _ in range(3)]
    for sid in sids:
        _ask(c, sid, "生成你认为重要的分析图表")
    assert [_title(c, s) for s in sids] == ["生成你认为重要的分析图表", "生成你认为重要的分析图表（2）", "生成你认为重要的分析图表（3）"]
    other = tmp_path / "other.csv"
    other.write_text(open(sample_path, encoding="utf-8").read(), encoding="utf-8")
    sid = _session(c, _dataset(c, str(other)))
    _ask(c, sid, "生成你认为重要的分析图表")
    assert _title(c, sid) == "生成你认为重要的分析图表"


def test_user_title_before_first_question_is_kept(c, sample_path):
    ds = _dataset(c, sample_path)
    sid = _session(c, ds)
    assert c.patch(f"/sessions/{sid}", json={"title": "我的会话"}, headers=H).json()["title"] == "我的会话"
    r = _ask(c, sid, "各地区销售额是多少")
    assert _title(c, sid) == "我的会话" == unquote(r.headers["x-session-title"])
    # 用户手动起的名字不去重：同一数据集另一个会话也可以叫「我的会话」
    sid2 = _session(c, ds)
    assert c.patch(f"/sessions/{sid2}", json={"title": "我的会话"}, headers=H).json()["title"] == "我的会话"


def test_patch_empty_restores_auto_title_from_first_question(c, sample_path):
    ds = _dataset(c, sample_path)
    sid = _session(c, ds)
    _ask(c, sid, "各城市销量")
    _ask(c, sid, "按部门统计离职人数")
    assert c.patch(f"/sessions/{sid}", json={"title": "改过"}, headers=H).json()["title"] == "改过"
    assert c.patch(f"/sessions/{sid}", json={"title": "   "}, headers=H).json()["title"] == "城市销量"   # 第一问，不是最近一问
    assert _title(c, sid) == "城市销量"
    # 还原时同样按同一数据集去重（不跟自己比）
    sid2 = _session(c, ds)
    _ask(c, sid2, "各城市销量")
    assert _title(c, sid2) == "城市销量（2）"
    assert c.patch(f"/sessions/{sid2}", json={"title": ""}, headers=H).json()["title"] == "城市销量（2）"
    # 还没有提问的会话：清空就是空串（首问时再生成）
    sid3 = _session(c, ds)
    assert c.patch(f"/sessions/{sid3}", json={"title": ""}, headers=H).json()["title"] == ""
    _ask(c, sid3, "商品退款金额前十")
    assert _title(c, sid3) == "商品退款金额"


def test_sidecar_selftest_probes_posseg():
    """#109 教训：冻结包里缺的模块只有自检能发现。imports 一项要静态 import jieba.posseg（PyInstaller 才会收进包），并真调一次 posseg.cut。"""
    from app import sidecar
    src = inspect.getsource(sidecar.selftest)
    tree = ast.parse(src.lstrip() if not src.startswith("def") else src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "imports")
    body = ast.unparse(fn)
    assert "import jieba.posseg" in body
    assert "jieba.posseg.cut(" in body
