"""沙箱子进程 → 主进程的结果编码（阶段 2，B01）。

只用 JSON：主进程绝不反序列化子进程产出的 pickle（那等于让沙箱里的代码在主进程执行）。
保真范围：DataFrame / Series（含 RangeIndex、MultiIndex、DatetimeIndex、PeriodIndex、列 dtype）、
dict / list / tuple / set、numpy 标量、Timestamp / Period / Timedelta、NaN / NaT / None。
其他对象退化为 repr 字符串（与旧版 format_result 的展示效果一致）。
"""
import math

import numpy as np
import pandas as pd

MAX_DEPTH = 20


# ------------------------------------------------------------------ 标量
def _enc_scalar(x):
    if isinstance(x, np.generic):
        x = x.item()
    if x is None:
        return None
    if x is pd.NaT:
        return {"t": "nat"}
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if math.isnan(x):
            return {"t": "nan"}
        if math.isinf(x):
            return {"t": "inf", "v": 1 if x > 0 else -1}
        return x
    if isinstance(x, str):
        return x
    if isinstance(x, pd.Timestamp):
        return {"t": "ts", "v": x.isoformat()}
    if isinstance(x, pd.Period):
        return {"t": "per", "v": str(x), "f": x.freqstr}
    if isinstance(x, pd.Timedelta):
        return {"t": "td", "v": x.value}
    if isinstance(x, (np.datetime64,)):
        return {"t": "ts", "v": pd.Timestamp(x).isoformat()}
    try:
        import datetime as _dt
        if isinstance(x, _dt.datetime):
            return {"t": "ts", "v": pd.Timestamp(x).isoformat()}
        if isinstance(x, _dt.date):
            return {"t": "date", "v": x.isoformat()}
    except Exception:
        pass
    if x is pd.NA:
        return {"t": "na"}
    return {"t": "repr", "v": repr(x)[:2000]}


def _dec_scalar(d):
    if not isinstance(d, dict):
        return d
    t = d.get("t")
    if t == "nan":
        return float("nan")
    if t == "inf":
        return float("inf") * d["v"]
    if t == "nat":
        return pd.NaT
    if t == "na":
        return pd.NA
    if t == "ts":
        return pd.Timestamp(d["v"])
    if t == "per":
        return pd.Period(d["v"], freq=d["f"])
    if t == "td":
        return pd.Timedelta(int(d["v"]))
    if t == "date":
        import datetime as _dt
        return _dt.date.fromisoformat(d["v"])
    if t == "tuple":
        return tuple(_dec_scalar(v) for v in d["v"])
    return d.get("v")          # repr


def _enc_label(x):
    if isinstance(x, tuple):
        return {"t": "tuple", "v": [_enc_scalar(v) for v in x]}
    return _enc_scalar(x)


# ------------------------------------------------------------------ 索引
def _enc_index(idx: pd.Index):
    if isinstance(idx, pd.RangeIndex):
        return {"k": "range", "start": idx.start, "stop": idx.stop, "step": idx.step, "name": _enc_label(idx.name)}
    if isinstance(idx, pd.MultiIndex):
        return {"k": "multi", "names": [_enc_label(n) for n in idx.names],
                "levels": [_enc_index(idx.get_level_values(i)) for i in range(idx.nlevels)]}
    out = {"k": "flat", "name": _enc_label(idx.name), "values": [_enc_label(v) for v in idx], "dtype": str(idx.dtype)}
    if isinstance(idx, pd.PeriodIndex):
        out["freq"] = idx.freqstr
    return out


def _dec_index(d):
    k = d["k"]
    if k == "range":
        return pd.RangeIndex(d["start"], d["stop"], d["step"], name=_dec_scalar(d["name"]))
    if k == "multi":
        arrays = [_dec_index(level) for level in d["levels"]]
        return pd.MultiIndex.from_arrays(arrays, names=[_dec_scalar(n) for n in d["names"]])
    values = [_dec_scalar(v) for v in d["values"]]
    name = _dec_scalar(d["name"])
    if "freq" in d:
        return pd.PeriodIndex(values, freq=d["freq"], name=name)
    idx = pd.Index(values, name=name)
    return _astype(idx, d.get("dtype"))


def _astype(obj, dtype):
    if not dtype or dtype == str(obj.dtype):
        return obj
    try:
        return obj.astype(dtype)
    except Exception:
        return obj


# ------------------------------------------------------------------ 入口
def encode(v, depth: int = 0):
    if depth > MAX_DEPTH:
        return {"k": "repr", "v": repr(v)[:2000]}
    if isinstance(v, pd.DataFrame):
        return {"k": "frame", "index": _enc_index(v.index), "columns": _enc_index(v.columns),
                "data": [[_enc_scalar(x) for x in v.iloc[:, i].tolist()] for i in range(v.shape[1])],
                "dtypes": [str(t) for t in v.dtypes]}
    if isinstance(v, pd.Series):
        return {"k": "series", "index": _enc_index(v.index), "name": _enc_label(v.name),
                "data": [_enc_scalar(x) for x in v.tolist()], "dtype": str(v.dtype)}
    if isinstance(v, pd.Index):
        return {"k": "index", "v": _enc_index(v)}
    if isinstance(v, np.ndarray):
        return {"k": "ndarray", "v": [encode(x, depth + 1) for x in v.tolist()]}
    if isinstance(v, tuple):
        return {"k": "tuple", "v": [encode(x, depth + 1) for x in v]}
    if isinstance(v, list):
        return {"k": "list", "v": [encode(x, depth + 1) for x in v]}
    if isinstance(v, (set, frozenset)):
        return {"k": "set", "v": [encode(x, depth + 1) for x in v]}
    if isinstance(v, dict):
        return {"k": "dict", "v": [[_enc_label(k), encode(x, depth + 1)] for k, x in v.items()]}
    return {"k": "scalar", "v": _enc_scalar(v)}


def decode(d):
    if d is None:
        return None
    k = d.get("k")
    if k == "frame":
        index, columns = _dec_index(d["index"]), _dec_index(d["columns"])
        cols = [_astype(pd.Series([_dec_scalar(x) for x in col], index=index), t)
                for col, t in zip(d["data"], d["dtypes"])]
        if not cols:
            return pd.DataFrame(index=index, columns=columns)
        df = pd.concat(cols, axis=1)
        df.columns = columns
        return df
    if k == "series":
        s = pd.Series([_dec_scalar(x) for x in d["data"]], index=_dec_index(d["index"]),
                      name=_dec_scalar(d["name"]))
        return _astype(s, d.get("dtype"))
    if k == "index":
        return _dec_index(d["v"])
    if k == "ndarray":
        return np.array([decode(x) for x in d["v"]])
    if k == "tuple":
        return tuple(decode(x) for x in d["v"])
    if k == "list":
        return [decode(x) for x in d["v"]]
    if k == "set":
        return {decode(x) for x in d["v"]}
    if k == "dict":
        return {_dec_scalar(key): decode(x) for key, x in d["v"]}
    if k == "scalar":
        return _dec_scalar(d["v"])
    return d.get("v")          # repr
