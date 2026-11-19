"""数据指纹覆盖 xlsx（阶段 7.5 第 2 步补丁，S 2026-11-19）。

以前 `report._dataset_files` 只认 .csv：全是 xlsx 的目录数据集，数据指纹里一个文件都没有，
回放 / 可比性校验对 Excel 用户等于失效。现在 xlsx 不展开 sheet，登记原始字节的 sha256 和大小。

另一半同样要紧：**CSV 数据集的指纹值一个字节都不能变**，否则 v7 的 evalset / judge 指纹全部断代。
下面用改动前的算法原样重算一遍，和现在的实现逐值比对。
"""
from __future__ import annotations

import hashlib
import os

import openpyxl
import pytest

from app.eval import fingerprint as fp
from app.eval import report as rp


# ---------------------------------------------------------------- 改动前的算法（原样抄下，只用来钉值）
def _legacy_dataset_files(dataset):
    from app.tools.dataset import is_dict_file
    if isinstance(dataset, (list, tuple)):
        return [os.fspath(p) for p in dataset]
    if isinstance(dataset, (str, os.PathLike)) and os.path.isdir(dataset):
        return sorted(os.path.join(dataset, f) for f in os.listdir(dataset)
                      if f.lower().endswith(".csv") and not is_dict_file(f))
    return None


def _legacy_files(datasets):
    from app.tools.dictionary import dict_path_for
    files = []
    for path in datasets.values():
        tables = _legacy_dataset_files(path)
        if tables is None:
            files += [path, dict_path_for(path)]
        else:
            for f in tables:
                files += [f, dict_path_for(f)]
    return files


def _legacy_hash(h, parts, files, repo):
    for f in sorted(set(files)):
        if not os.path.exists(f):
            continue
        data = open(f, "rb").read().replace(b"\r\n", b"\n")
        rel = os.path.relpath(f, repo).replace(os.sep, "/")
        parts[rel] = hashlib.sha256(data).hexdigest()[:12]
        h.update(rel.encode() + b"\0" + data + b"\0")


def _legacy_judge(datasets):
    h, parts = hashlib.sha256(), {}
    for rel in fp.JUDGE_FILES:
        data = open(os.path.join(fp._REPO, rel), "rb").read().replace(b"\r\n", b"\n")
        parts[rel] = hashlib.sha256(data).hexdigest()[:12]
        h.update(rel.encode() + b"\0" + data + b"\0")
    _legacy_hash(h, parts, _legacy_files(datasets), fp._REPO)
    return {"sha12": h.hexdigest()[:12], "files": parts}


def _legacy_evalset(datasets):
    h, parts = hashlib.sha256(), {}
    files = [os.path.join(rp._REPO, f) for f in rp.EVALSET_FILES] + _legacy_files(datasets)
    _legacy_hash(h, parts, files, rp._REPO)
    return {"sha256": h.hexdigest()[:12], "files": parts}



@pytest.fixture
def repo_tmp():
    """指纹按相对仓库根的路径记文件（os.path.relpath）。Windows CI 上 pytest 的 tmp_path 在 C:、仓库在 D:，
    跨盘 relpath 抛 ValueError —— 生产里数据集都在仓库内，不会跨盘；测试数据集因此也建在仓库里，用完删掉。"""
    import shutil, tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp(prefix=".fp_tmp_", dir=fp._REPO))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)

def _csv_datasets(tmp_path):
    single = tmp_path / "one.csv"
    single.write_bytes(b"a,b\r\n1,2\r\n")                    # CRLF：归一规则也要保持
    (tmp_path / "one.dict.csv").write_text("field,description\na,甲\n", encoding="utf-8")
    d = tmp_path / "multi"
    d.mkdir()
    (d / "x.csv").write_text("k,v\n1,2\n", encoding="utf-8")
    (d / "y.csv").write_text("k,w\n1,3\n", encoding="utf-8")
    (d / "x.dict.csv").write_text("field,description\nv,值\n", encoding="utf-8")
    (d / "notes.txt").write_text("不是表", encoding="utf-8")
    return {"single": str(single), "multi": str(d), "list": [str(d / "x.csv"), str(d / "y.csv")]}


# ---------------------------------------------------------------- CSV 指纹不变
def test_csv_data_fingerprint_identical_to_pre_xlsx_algorithm_on_real_datasets():
    """真实评测数据集（cases.DATASETS，全是 CSV）：judge / evalset 指纹与改动前的算法逐值相等。
    2026-11-19 实测改前改后都是 evalset 672b52a3a6b0、judge 289474f4d943（v7 断代值）。"""
    from app.eval.cases import DATASETS
    assert fp.judge_fingerprint() == _legacy_judge(DATASETS)
    new = rp.evalset_fingerprint()
    old = _legacy_evalset(DATASETS)
    assert new["files"] == old["files"]
    assert new["sha256"] == old["sha256"]


def test_csv_data_fingerprint_identical_on_single_dir_and_list(repo_tmp):
    ds = _csv_datasets(repo_tmp)
    assert fp.judge_fingerprint(ds) == _legacy_judge(ds)
    new = rp.evalset_fingerprint(ds)
    old = _legacy_evalset(ds)
    assert new["files"] == old["files"] and new["sha256"] == old["sha256"]


# ---------------------------------------------------------------- xlsx 进指纹
def _book(path, value):
    wb = openpyxl.Workbook()
    wb.active.title = "S"
    wb.active.append(["a", "b"])
    wb.active.append([value, 2])
    wb.save(path)


def test_xlsx_dataset_fingerprint_nonempty_and_tracks_content(repo_tmp):
    """只有 xlsx 的目录数据集：数据指纹非空（xlsx 文件在 files 里）；改一个单元格，三处指纹都变。"""
    d = repo_tmp / "xl"
    d.mkdir()
    book = d / "sales.xlsx"
    _book(book, 1)
    for ds in ({"x": str(d)}, {"x": str(book)}, {"x": [str(book)]}):    # 目录 / 单文件 / 路径列表
        j0 = fp.judge_fingerprint(ds)
        rel = os.path.relpath(book, rp._REPO).replace(os.sep, "/")
        assert set(j0["files"]) - set(fp.JUDGE_FILES) == {rel}            # 数据部分非空，正好是这个 xlsx
        assert j0["files"][rel] == hashlib.sha256(book.read_bytes()).hexdigest()[:12]   # 原始字节，不做换行归一
        assert j0["sha12"] != fp.judge_fingerprint({})["sha12"]
        e0 = rp.evalset_fingerprint(ds)["sha256"]
        m0 = rp.datasets_metadata(ds)["x"]["sha256"]

        _book(book, 999)
        assert fp.judge_fingerprint(ds)["sha12"] != j0["sha12"]
        assert rp.evalset_fingerprint(ds)["sha256"] != e0
        assert rp.datasets_metadata(ds)["x"]["sha256"] != m0
        _book(book, 1)


def test_xlsx_record_includes_sha256_and_size(tmp_path):
    book = tmp_path / "a.xlsx"
    _book(book, 1)
    raw = book.read_bytes()
    data, sha12 = rp.fingerprint_record(str(book))
    assert sha12 == hashlib.sha256(raw).hexdigest()[:12]
    assert hashlib.sha256(raw).hexdigest().encode() in data and f"size={len(raw)}".encode() in data
    csv = tmp_path / "a.csv"
    csv.write_bytes(b"a\r\n1\r\n")
    assert rp.fingerprint_record(str(csv)) == (b"a\n1\n", hashlib.sha256(b"a\n1\n").hexdigest()[:12])


def test_xlsx_sheet_dictionary_in_fingerprint(repo_tmp):
    """xlsx 的字典（foo.dict.csv 和 foo.<sheet>.dict.csv，sheet 名带点也算）改了，数据指纹要变。"""
    d = repo_tmp / "xl"
    d.mkdir()
    _book(d / "fy.2024.xlsx", 1)
    ds = {"x": str(d)}
    j0 = fp.judge_fingerprint(ds)["sha12"]
    (d / "fy.2024.2024.Q1.dict.csv").write_text("field,description\na,甲\n", encoding="utf-8")
    j1 = fp.judge_fingerprint(ds)
    assert j1["sha12"] != j0
    assert any(k.endswith("fy.2024.2024.Q1.dict.csv") for k in j1["files"])
    (d / "fy.2024.dict.csv").write_text("field,description\na,乙\n", encoding="utf-8")
    assert fp.judge_fingerprint(ds)["sha12"] != j1["sha12"]
    assert rp.datasets_metadata(ds)["x"]["dictionary_files"] == ["fy.2024"]
