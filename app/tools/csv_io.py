"""CSV 读取与编码检测（B15）。

旧实现最后用 latin-1 兜底：latin-1 能"解码"任意字节，坏编码会静默变成乱码进 prompt。
现在的顺序：
1. BOM：utf-8-sig / utf-16 / utf-32（有 BOM 就确定）；
2. 严格 utf-8；
3. 严格 gb18030（GBK/GB2312 的超集，覆盖国内 Excel 导出的 CSV）；
4. 都失败 → 抛 CSVEncodingError，提示用户另存为 UTF-8，或显式传 encoding。

为什么不用 charset-normalizer 自动猜：实测短文件上它会把坏字节判成 utf_16_be、
把 GBK 判成 cp949（chaos 都是 0），猜错比报错更糟，所以只做确定性检测。
已知局限：Big5（繁体）字节多数也能被 gb18030 严格解码，会得到错字而不报错；需要时显式传 encoding="big5"。
"""
import codecs
import io

import pandas as pd

_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]
_CANDIDATES = ["utf-8", "gb18030"]


class CSVEncodingError(ValueError):
    """文件无法用支持的编码严格解码。"""


def detect_encoding(data: bytes) -> str:
    """返回能严格解码 data 的编码名；都不行则抛 CSVEncodingError。"""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return enc
    for enc in _CANDIDATES:
        try:
            data.decode(enc, errors="strict")
            return enc
        except UnicodeDecodeError:
            continue
    raise CSVEncodingError(
        f"无法识别文件编码（已尝试 BOM 检测、{' / '.join(_CANDIDATES)}）。"
        "请把文件另存为 UTF-8 后再上传，或显式指定 encoding（如 big5、cp1252）。"
    )


def read_csv_with_encoding(path: str, encoding: str | None = None):
    """读取 CSV，返回 (DataFrame, 实际使用的编码)。只读一次磁盘。"""
    with open(path, "rb") as f:
        data = f.read()
    enc = encoding or detect_encoding(data)
    try:
        text = data.decode(enc, errors="strict")
    except UnicodeDecodeError as e:
        raise CSVEncodingError(f"文件不能用指定编码 {enc} 解码：{e}") from e
    if text.startswith("\ufeff"):
        text = text[1:]
    return pd.read_csv(io.StringIO(text)), enc


def read_csv(path: str, encoding: str | None = None) -> pd.DataFrame:
    return read_csv_with_encoding(path, encoding)[0]
