"""容错的 CSV 读取：中文 CSV 常见 GBK/GB2312 编码，
默认 utf-8 会 UnicodeDecodeError。这里依次尝试常见编码。
"""
import pandas as pd

_ENCODINGS = ["utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"]


def read_csv(path: str) -> pd.DataFrame:
    last_err = None
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
    raise last_err
