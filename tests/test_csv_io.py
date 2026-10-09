import pytest

from app.tools.csv_io import read_csv


def test_read_utf8(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("地区,销量\n华东,1\n", encoding="utf-8")
    assert list(read_csv(str(p)).columns) == ["地区", "销量"]


def test_read_gbk(tmp_path):
    p = tmp_path / "g.csv"
    p.write_bytes("地区,销量\n华东,1\n".encode("gbk"))
    assert read_csv(str(p)).iloc[0, 0] == "华东"


@pytest.mark.xfail(raises=AssertionError, reason="B15: latin-1 兜底永不报错，坏编码静默变乱码")
def test_undecodable_file_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n\x81\xff\xfe,1\n")
    try:
        read_csv(str(p))
        raised = False
    except Exception:
        raised = True
    assert raised
