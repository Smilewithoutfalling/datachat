"""结果比较器：比较 ground truth 与模型生成代码的执行结果。"""

import math

import pandas as pd


def results_equal(a, b, float_tol=1e-4) -> bool:
    """灵活比较两个结果是否等价。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    # DataFrame / Series: 尝试多种比较策略
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        return _df_equal(a, b)
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        try:
            # 用 to_dict 先对齐再递归比较
            da, db = _normalize_obj(a), _normalize_obj(b)
            return _deep_equal(da, db, float_tol)
        except Exception:
            return False
    if isinstance(a, pd.DataFrame):
        # a 是 DataFrame, b 可能是 dict/list
        try:
            return _df_equal(a, pd.DataFrame(b) if not isinstance(b, pd.DataFrame) else b)
        except Exception:
            return False
    if isinstance(b, pd.DataFrame):
        try:
            return _df_equal(pd.DataFrame(a) if not isinstance(a, pd.DataFrame) else a, b)
        except Exception:
            return False
    if isinstance(a, pd.Series):
        try:
            return results_equal(_normalize_obj(a), b, float_tol)
        except Exception:
            return False
    if isinstance(b, pd.Series):
        try:
            return results_equal(a, _normalize_obj(b), float_tol)
        except Exception:
            return False

    # 基础类型
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=float_tol)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=float_tol)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(results_equal(x, y, float_tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return _deep_equal(a, b, float_tol)

    # 混合类型：尝试转成数字
    try:
        fa, fb = float(a), float(b)
        return math.isclose(fa, fb, rel_tol=float_tol)
    except (ValueError, TypeError):
        pass

    return str(a).strip() == str(b).strip()


def _df_equal(a, b):
    """DataFrame 灵活比较：尝试值比较、列名对齐后比较。"""
    a, b = a.copy(), b.copy()
    # 统一列名
    if a.shape == b.shape:
        a.columns = [str(c).strip() for c in a.columns]
        b.columns = [str(c).strip() for c in b.columns]
    # 尝试用 pd.testing
    try:
        a = a.sort_index(axis=0).sort_index(axis=1).reset_index(drop=True)
        b = b.sort_index(axis=0).sort_index(axis=1).reset_index(drop=True)
        pd.testing.assert_frame_equal(a.astype(float), b.astype(float), rtol=1e-3, check_dtype=False)
        return True
    except Exception:
        pass
    # 兜底：转 dict 比较
    try:
        ea = a.to_dict(orient="records")
        eb = b.to_dict(orient="records")
        return _deep_equal(ea, eb, 1e-3)
    except Exception:
        return False


def _normalize_obj(obj):
    """把 Series 转成可比较的基础类型。"""
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, pd.Series):
        # 按值排序，确保比较不受索引顺序影响
        d = obj.sort_values(ascending=False).to_dict()
        return {str(k): _normalize_scalar(v) for k, v in d.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_scalar(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _normalize_scalar(v) for k, v in obj.items()}
    return _normalize_scalar(obj)


def _normalize_scalar(v):
    """标量值归一化。"""
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    if isinstance(v, (int, str, bool, type(None))):
        return v
    try:
        fv = float(v)
        return round(fv, 4) if fv != int(fv) else int(fv)
    except (ValueError, TypeError):
        return str(v)


def _deep_equal(a, b, tol):
    """递归深度比较，支持嵌套结构。"""
    if isinstance(a, dict) and isinstance(b, dict):
        ka = sorted(a.keys())
        kb = sorted(b.keys())
        if ka != kb:
            return False
        return all(_deep_equal(a[k], b[k], tol) for k in ka)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        # 如果元素是 dict，按内容排序后比较
        if all(isinstance(x, dict) for x in a) and all(isinstance(x, dict) for x in b):
            a = sorted(a, key=lambda x: tuple(str(v) for v in x.values()))
            b = sorted(b, key=lambda x: tuple(str(v) for v in x.values()))
        return all(_deep_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=tol)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=tol)
    try:
        fa, fb = float(a), float(b)
        return math.isclose(fa, fb, rel_tol=tol)
    except (ValueError, TypeError):
        pass
    return str(a).strip() == str(b).strip()
