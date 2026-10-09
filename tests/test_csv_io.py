import codecs

import pytest

from app.tools.csv_io import CSVEncodingError, detect_encoding, read_csv, read_csv_with_encoding


def test_read_utf8(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("地区,销量\n华东,1\n", encoding="utf-8")
    assert list(read_csv(str(p)).columns) == ["地区", "销量"]


def test_read_gbk(tmp_path):
    p = tmp_path / "g.csv"
    p.write_bytes("地区,销量\n华东,1\n".encode("gbk"))
    df, enc = read_csv_with_encoding(str(p))
    assert df.iloc[0, 0] == "华东" and enc == "gb18030"


def test_undecodable_file_raises(tmp_path):
    """B15：坏编码明确报错，不再被 latin-1 静默吞成乱码。"""
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n\x81\xff\xfe,1\n")
    with pytest.raises(CSVEncodingError):
        read_csv(str(p))


@pytest.mark.parametrize("data,enc", [
    (codecs.BOM_UTF8 + "地区\n华东\n".encode("utf-8"), "utf-8-sig"),
    ("地区\n华东\n".encode("utf-16"), "utf-16"),          # 自带 BOM
    ("地区\n华东\n".encode("utf-8"), "utf-8"),
    ("地区\n华东\n".encode("gb2312"), "gb18030"),
    ("地区\n𠀀\n".encode("gb18030"), "gb18030"),           # GBK 之外的四字节字符
])
def test_detect_encoding(data, enc):
    assert detect_encoding(data) == enc


@pytest.mark.parametrize("enc", ["utf-8-sig", "utf-16"])
def test_bom_files_have_clean_header(tmp_path, enc):
    p = tmp_path / "b.csv"
    p.write_bytes("地区,销量\n华东,1\n".encode(enc))
    assert list(read_csv(str(p)).columns) == ["地区", "销量"]


def test_western_single_byte_needs_explicit_encoding(tmp_path):
    p = tmp_path / "w.csv"
    p.write_bytes("name\ncafé\n".encode("cp1252"))
    with pytest.raises(CSVEncodingError):
        read_csv(str(p))
    assert read_csv(str(p), encoding="cp1252").iloc[0, 0] == "café"


def test_explicit_wrong_encoding_raises(tmp_path):
    p = tmp_path / "g.csv"
    p.write_bytes("地区\n华东\n".encode("gbk"))
    with pytest.raises(CSVEncodingError):
        read_csv(str(p), encoding="utf-8")
