import os

from app.tools.dictionary import augment_question, dict_path_for, load_retriever


def test_dict_path_for():
    assert dict_path_for(os.path.join("data", "sample.csv")) == os.path.join("data", "sample.dict.csv")


def test_retriever_hits_region(sample_path):
    r = load_retriever(sample_path)
    assert r is not None
    fields = [f for f, _ in r.search("哪个地区卖得最好", k=3)]
    assert "region" in fields


def test_augment_without_retriever_is_identity():
    assert augment_question("总销售额", None) == "总销售额"


def test_no_dict_file_returns_none(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    assert load_retriever(str(p)) is None
