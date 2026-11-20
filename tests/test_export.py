"""阶段 7.5 第 2 步：结果表导出与代码导出（app/tools/export.py、app/tools/export_runtime.py、
POST /messages/{id}/export/code|result）。验收见 docs/roadmap/phase75-assess.md 第 40 行：

导出的 .py 要在**仓库外、不装 DataChat 的干净 venv** 里重跑出同一个 result。沙箱
（app/tools/sandbox_worker.py:205-220）会注入 df / dfs / chart / chart_path、重定向 plt.savefig，
所以在开发环境里直接 exec 跑通不算数。

三部分：
1. 读数对照（快）：导出运行时的 CSV / xlsx 读法与 DataChat 的 load_data 逐值相等（perturb 9 变体、真合并单元格报表、
   隐藏 / 空 sheet、多 sheet、前导零、目录混放……）。
2. 生成与接口（快）：安全检查、注释注入、结果表 CSV / xlsx、导出端点（鉴权、状态码、写盘位置、重名不覆盖）。
3. 干净 venv（慢，@pytest.mark.slow，CI 照跑）：python -m venv 新建（不带 --system-site-packages），
   只装 pandas / numpy / matplotlib / openpyxl（版本与当前环境相同），先证明 `import app`、`import fastapi` 失败，
   再在仓库外的目录用 `python -I` 跑导出的脚本，把 result 用 wire 编码带回，与沙箱 run_code 的 result 逐值比较。
   装包：默认先 pip（联网），失败再从当前环境按依赖闭包逐文件拷贝（离线也能跑）；DATACHAT_EXPORT_VENV=pip|copy 可指定。
   Windows CI 上 tmp_path 在 C:、仓库在 D:——这里只用绝对路径，不做 relpath。
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile

import openpyxl
import pandas as pd
import pytest

from app.tools import excel_io, export_runtime as rt, wire
from app.tools.dataset import load_data
from app.tools.export import (build_script, result_table, runtime_source, to_csv_bytes, to_xlsx_bytes,
                              unsafe_reasons)
from app.tools.sandbox import run_code

import test_excel_io as tx      # 同目录的 xlsx 构造工具（write_xlsx、_report_book、perturb 变体）
import perturb                  # test_excel_io 已把 scripts/ 放进 sys.path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ================================================================ 公共工具
def rt_load(target):
    """用导出运行时读 target（文件或目录），口径同 build_script 传给脚本的参数。"""
    target = os.fspath(target)
    if os.path.isdir(target):
        files = sorted(f for f in os.listdir(target)
                       if (f.lower().endswith(".csv") and not f.lower().endswith(".dict.csv"))
                       or f.lower().endswith(".xlsx"))
        return rt._dc_load(target, [(f, None) for f in files], True, target, False)
    return rt._dc_load(os.path.dirname(target), [(os.path.basename(target), None)], False,
                       os.path.dirname(target), False)


def assert_same(a, b):
    """逐值相等：DataFrame / Series 精确比较（列名、索引、dtype、取值），dict 逐键，标量含 NaN。"""
    if isinstance(a, dict) and isinstance(b, dict) and all(isinstance(v, pd.DataFrame) for v in a.values()):
        assert list(a) == list(b)
        for k in a:
            pd.testing.assert_frame_equal(a[k], b[k], check_exact=True)
    elif isinstance(a, pd.DataFrame):
        pd.testing.assert_frame_equal(a, b, check_exact=True)
    elif isinstance(a, pd.Series):
        pd.testing.assert_series_equal(a, b, check_exact=True)
    elif isinstance(a, float) and a != a:
        assert isinstance(b, float) and b != b
    else:
        assert type(a) is type(b) and a == b, (a, b)


# ================================================================ 1. 读数对照
@pytest.mark.parametrize("kind", perturb.KINDS)
def test_runtime_reads_perturb_xlsx_and_csv_like_datachat(tmp_path, kind):
    header, rows = tx.orders_table()
    table = perturb.TRANSFORM[kind](header, rows)
    csv_path, xlsx_path = tmp_path / f"o.{kind}.csv", tmp_path / f"o.{kind}.xlsx"
    perturb._write_csv(csv_path, table, quote_all=kind in perturb.QUOTE_ALWAYS)
    tx.write_xlsx(xlsx_path, {"Sheet1": tx._xlsx_rows(table)}, raw=True)
    for p in (csv_path, xlsx_path):
        assert_same(rt_load(p), load_data(str(p))[0])


def test_runtime_reads_merged_report_like_datachat(tmp_path):
    p = tmp_path / "report.xlsx"
    tx._report_book(p)
    want = load_data(str(p))[0]
    assert "金额-线上" in want.columns                    # 确实走到了合并表头的分支
    assert_same(rt_load(p), want)


def _odd_book(path):
    """一本把 xlsx 独有结构凑齐的工作簿：隐藏 sheet、空 sheet、表头不在首行 + 左侧空列、横向合并表头、
    前导零文本、日期、错误值、数据中间空行、布尔、混合列。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append([])
    ws.append([None, "工号", "日期", "地区", None, "状态"])
    ws.merge_cells("D2:E2")                              # 横向合并、下一行是数据
    ws.append([None, "00123", pd.Timestamp("2024-01-05").to_pydatetime(), "华东", 1, True])
    ws.append([])
    ws.append([None, "04567", pd.Timestamp("2024-01-06 13:30").to_pydatetime(), "华北", "N/A", False])
    ws.append([None, "00999", None, "#DIV/0!", 2.5, True])
    for r in (3, 5, 6):
        ws.cell(r, 2).number_format = "@"
    wb.create_sheet("Sheet2")
    h = wb.create_sheet("辅助")
    h.append(["k"])
    h.append([1])
    h.sheet_state = "hidden"
    s = wb.create_sheet("汇总")
    s.append(["2024 年汇总"])
    s.merge_cells("A1:C1")
    s.append(["地区", "金额", None])
    s.append([None, "线上", "线下"])
    s.merge_cells("A2:A3")
    s.merge_cells("B2:C2")
    s.append(["华东", 1, 2])
    s.append(["合计", 1, 2])
    wb.save(path)


def test_runtime_reads_hidden_empty_multi_sheet_like_datachat(tmp_path):
    p = tmp_path / "book.xlsx"
    _odd_book(p)
    want = load_data(str(p))[0]
    assert list(want) == ["book.明细", "book.汇总"]        # 空的、隐藏的都跳过
    assert want["book.明细"]["工号"].tolist() == ["00123", "04567", "00999"]
    got = rt_load(p)
    assert_same(got, want)


def test_runtime_reads_directory_mix_like_datachat(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    _odd_book(d / "book.xlsx")
    tx.write_xlsx(d / "one.xlsx", {"唯一": [["a", "b"], ["1", "x"]]})
    (d / "orders.csv").write_bytes("编号,金额\n00123,1.5\n2,\n".encode("gb18030"))
    (d / "bom.csv").write_bytes("\ufeffa,b\n1,2\n".encode("utf-8"))
    (d / "orders.dict.csv").write_text("field,description\n金额,元\n", encoding="utf-8")
    want = load_data(str(d))[0]
    assert list(want) == ["bom", "book.明细", "book.汇总", "one", "orders"]
    assert_same(rt_load(d), want)


def test_runtime_constants_match_excel_io():
    """运行时里抄的几项可配置规则与 excel_io 同值（excel_io 改了，这里会红）。"""
    assert rt._DC_NA_STRINGS == excel_io.NA_STRINGS
    assert rt._DC_INCLUDE_HIDDEN_SHEETS == excel_io.INCLUDE_HIDDEN_SHEETS
    assert rt._DC_SHEET_NAME_SEP == excel_io.SHEET_NAME_SEP
    assert rt._DC_HEADER_JOIN == excel_io.HEADER_JOIN
    assert rt._DC_MAX_HEADER_ROWS == excel_io.MAX_HEADER_ROWS


def test_runtime_source_has_no_app_import():
    tree = ast.parse(runtime_source())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "app" not in mods
    assert mods <= {"codecs", "datetime", "hashlib", "io", "math", "os", "sys", "numpy", "pandas", "warnings",
                    "openpyxl", "matplotlib"}, mods


def test_runtime_shipped_as_data_in_sidecar_build():
    """打包后模块只有字节码，嵌进导出脚本的源码要作为数据文件带上（同 providers.json）。"""
    text = open(os.path.join(REPO, "packaging", "build_sidecar.py"), encoding="utf-8").read()
    assert "'app', 'tools', 'export_runtime.py')}{os.pathsep}app/tools" in text


# ================================================================ 2. 生成与接口
@pytest.mark.parametrize("code, frag", [
    ("import os\nresult = 1", "os"),
    ("from subprocess import run\nresult = 1", "subprocess"),
    ("try:\n    open('/etc/passwd')\nexcept Exception:\n    pass\nresult = 1", "open"),
    ("result = ().__class__.__bases__", "__class__"),
    ("try:\n    df.to_csv('C:/x.csv')\nexcept Exception:\n    pass\nresult = 1", "to_csv"),
    ("x = pd.read_pickle('a.pkl')\nresult = 1", "read_pickle"),
    ("result = np.ctypeslib", "ctypeslib"),
    ("result = eval('1')", "eval"),
    ("open = open\ntry:\n    open('x')\nexcept Exception:\n    pass\nresult = 1", "open"),
])
def test_unsafe_code_is_flagged(code, frag):
    reasons = unsafe_reasons(code)
    assert reasons and any(frag in r for r in reasons), reasons


def test_normal_code_is_not_flagged():
    code = ("id = df['id'] if 'id' in df else None\ntype_ = 1\nformat = '%Y'\n"
            "import numpy as np\nimport matplotlib.pyplot as plt\nfrom datetime import date\n"
            "s = df.groupby('region')['units'].sum().sort_values()\nchart('bar', s, title='销量')\n"
            "fig, ax = plt.subplots(); ax.plot([1, 2]); plt.savefig(chart_path)\n"
            "result = s.to_frame().to_dict()")
    assert unsafe_reasons(code) == []


def test_build_script_comment_injection_and_no_app_import():
    evil = "标题\nimport os; os.system('x')\r\n\u2028print(1)"
    text = build_script("result = df.shape", files=[("a\nb.csv", "ab" * 32)], data_dir="C:\\数据\\x",
                        multi_source=False,
                        meta={"session_title": evil, "question": evil, "dataset_name": evil, "message_id": "m1"})
    tree = ast.parse(text)
    for n in ast.walk(tree):                              # 元数据里的换行没有逃出注释变成代码
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr != "system"
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            assert all(not x.split(".")[0] == "app" for x in names)
    assert "DATA_DIR = 'C:\\\\数据\\\\x'" in text
    assert "('a\\nb.csv', '" in text                       # 文件名进的是 repr 字面量
    assert "# ---------------- DataChat 生成的代码（原样） ----------------\nresult = df.shape\n" in text


def test_result_table_shapes():
    f, idx = result_table(pd.DataFrame({"a": [1, 2]}))
    assert list(f.columns) == ["a"] and idx is False
    f, idx = result_table(pd.Series([1, 2], index=pd.Index(["x", "y"], name="地区"), name="销量"))
    assert list(f.columns) == ["销量"] and idx is True
    f, _ = result_table({"x": 1, "y": 2.5})
    assert f.to_dict("list") == {"项": ["x", "y"], "值": [1, 2.5]}
    f, _ = result_table(42)
    assert f.to_dict("list") == {"result": [42]}
    f, _ = result_table(pd.DataFrame([[1, 2]], columns=pd.MultiIndex.from_tuples([("a", "x"), ("a", "y")])))
    assert list(f.columns) == ["a / x", "a / y"]


def test_csv_bytes_bom_and_values_verbatim():
    s = pd.Series([1.25, None], index=pd.Index(["华东", "=SUM(A1)"], name="地区"), name="金额")
    b = to_csv_bytes(s)
    assert b.startswith(b"\xef\xbb\xbf")
    assert b.decode("utf-8-sig") == "地区,金额\r\n华东,1.25\r\n=SUM(A1),\r\n"
    back = pd.read_csv(io.BytesIO(b), encoding="utf-8-sig", index_col=0)["金额"]
    assert back.iloc[0] == 1.25


def test_xlsx_bytes_text_stays_text():
    df = pd.DataFrame({"工号": ["00123", "=1+1"], "金额": [1.5, None], "t": pd.to_datetime(["2024-01-01", None]),
                       "备注": ["a\x01b", "ok"]})
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx_bytes(df)))
    ws = wb["结果"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0] == ["工号", "金额", "t", "备注"]
    assert rows[1][:2] == ["00123", 1.5] and rows[2][:2] == ["=1+1", None]
    assert ws.cell(3, 1).data_type == "s"                 # 不是公式
    assert rows[1][3] == "ab"


# ---------------------------------------------------------------- 接口
TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}
SALES = "region,units,code\n华东,3,00123\n华北,5,00456\n华东,4,00789\n"


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient
    from app.server.app import create_app
    from app.server.db import make_sessionmaker
    home = tmp_path / "home"
    app = create_app(str(home), TOKEN)
    app.state.export_dir = str(tmp_path / "dl")
    c = TestClient(app)
    r = c.post("/datasets", headers=H, files=[("files", ("销售.csv", SALES.encode("utf-8"), "text/csv"))])
    assert r.status_code == 200, r.text
    ds = r.json()["id"]
    sid = c.post("/sessions", headers=H, json={"dataset_id": ds, "agent": "workflow", "title": "各地区\n销量"}).json()["id"]
    return c, make_sessionmaker(os.path.join(str(home), "datachat.db")), sid, str(tmp_path / "dl")


def _turn(Session, sid, code, *, executed=True, status="ok", result_text=None):
    from app.core.result import format_result
    from app.server.db import Message, now
    if result_text is None:
        df = pd.read_csv(io.StringIO(SALES))
        ns = {"df": df, "pd": pd, "result": None}
        exec(code, ns)
        result_text = format_result(ns["result"])
    rec = {"agent": "workflow", "code": code, "executed": executed, "result_text": result_text, "ok": True}
    with Session() as db:
        q = Message(session_id=sid, role="user", content="各地区销量是多少？", created_at=now())
        db.add(q)
        db.flush()
        a = Message(session_id=sid, role="assistant", status=status, content="……", created_at=now(),
                    result_json=json.dumps(rec, ensure_ascii=False))
        db.add(a)
        db.commit()
        return q.id, a.id


CODE = "result = df.groupby('region')['units'].sum()"


def test_export_code_endpoint_writes_standalone_script(api):
    c, Session, sid, dl = api
    _q, mid = _turn(Session, sid, CODE)
    r = c.post(f"/messages/{mid}/export/code", headers=H)
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert os.path.dirname(path) == os.path.realpath(dl) and path.endswith(".py")
    assert r.json()["filename"] == f"各地区销量_{mid[:6]}.py"        # 会话标题里的换行被清掉
    text = open(path, encoding="utf-8").read()
    assert "# 问题：各地区销量是多少？" in text and "销售.csv  sha256=" in text
    assert CODE in text and "import app" not in text and "from app" not in text
    r2 = c.post(f"/messages/{mid}/export/code", headers=H)            # 重名编号，不覆盖
    assert r2.json()["filename"] == f"各地区销量_{mid[:6]} (1).py"


def test_export_result_endpoint_csv_and_xlsx(api):
    c, Session, sid, dl = api
    _q, mid = _turn(Session, sid, CODE)
    r = c.post(f"/messages/{mid}/export/result", headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["matches_original"] is True and j["rows"] == 2 and j["columns"] == 1
    b = open(j["path"], "rb").read()
    assert b.decode("utf-8-sig") == "region,units\r\n华东,7\r\n华北,5\r\n" and b.startswith(b"\xef\xbb\xbf")
    r = c.post(f"/messages/{mid}/export/result?format=xlsx", headers=H)
    assert r.status_code == 200 and r.json()["path"].endswith(".xlsx")
    ws = openpyxl.load_workbook(r.json()["path"])["结果"]
    assert [[x.value for x in row] for row in ws.iter_rows()] == [["region", "units"], ["华东", 7], ["华北", 5]]
    assert c.post(f"/messages/{mid}/export/result?format=pdf", headers=H).status_code == 422


def test_export_result_reports_mismatch(api):
    c, Session, sid, _dl = api
    _q, mid = _turn(Session, sid, CODE, result_text="（旧的预览）")
    r = c.post(f"/messages/{mid}/export/result", headers=H)
    assert r.status_code == 200 and r.json()["matches_original"] is False


def test_export_endpoints_reject(api):
    c, Session, sid, dl = api
    qid, mid = _turn(Session, sid, CODE)
    for url in (f"/messages/{mid}/export/code", f"/messages/{mid}/export/result"):
        assert c.post(url).status_code == 401
        assert c.post(url, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post(f"/messages/{qid}/export/code", headers=H).status_code == 400
    assert c.post("/messages/nope/export/code", headers=H).status_code == 404
    _q, failed = _turn(Session, sid, CODE, executed=False, status="error", result_text="")
    assert c.post(f"/messages/{failed}/export/code", headers=H).status_code == 409
    assert c.post(f"/messages/{failed}/export/result", headers=H).status_code == 409
    _q, evil = _turn(Session, sid, "try:\n    open('x')\nexcept Exception:\n    pass\nresult = 1", result_text="1")
    r = c.post(f"/messages/{evil}/export/code", headers=H)
    assert r.status_code == 422 and "open" in r.json()["detail"]
    assert not os.path.exists(dl) or not any(f.endswith(".py") for f in os.listdir(dl))


def test_export_dir_defaults_to_downloads_when_not_desktop(tmp_path, monkeypatch, api):
    c, Session, sid, _dl = api
    c.app.state.export_dir = None
    monkeypatch.setenv("DATACHAT_EXPORT_DIR", str(tmp_path / "env-dl"))
    _q, mid = _turn(Session, sid, CODE)
    r = c.post(f"/messages/{mid}/export/code", headers=H)
    assert r.status_code == 200 and os.path.dirname(r.json()["path"]) == os.path.realpath(tmp_path / "env-dl")


# ================================================================ 3. 干净 venv（慢）
VENV_PKGS = ("pandas", "numpy", "matplotlib", "openpyxl")


def _venv_python(venv):
    return os.path.join(venv, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv, "bin", "python")


def _clean_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV", "CONDA"))}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "MPLBACKEND": "Agg"})
    return env


def _closure(names):
    """当前环境里 names 这几个包的运行依赖闭包（distribution 名）。"""
    from importlib import metadata
    from packaging.requirements import Requirement
    seen, todo = {}, list(names)
    while todo:
        n = todo.pop()
        key = n.lower().replace("_", "-")
        if key in seen:
            continue
        dist = metadata.distribution(n)
        seen[key] = dist
        for r in dist.requires or []:
            req = Requirement(r)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                todo.append(req.name)
    return seen


def _copy_install(py, env):
    """离线：把依赖闭包里每个 distribution 的 RECORD 文件逐个拷进干净 venv 的 site-packages（等价于 pip 装同版本）。"""
    site = subprocess.run([py, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                          capture_output=True, text=True, env=env, check=True).stdout.strip()
    for dist in _closure(VENV_PKGS).values():
        base = dist.locate_file("")
        for f in dist.files or []:
            rel = str(f)
            if rel.startswith("..") or os.path.isabs(rel) or "__pycache__" in rel:
                continue
            src = os.path.join(os.fspath(base), rel)
            if os.path.isfile(src):
                dst = os.path.join(site, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)


def _pip_install(py, env):
    from importlib import metadata
    pins = [f"{p}=={metadata.version(p)}" for p in VENV_PKGS]
    subprocess.run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", *pins],
                   env={**env, **{k: v for k, v in os.environ.items() if "proxy" in k.lower()}},
                   check=True, timeout=900, capture_output=True)


@pytest.fixture(scope="session")
def clean_python(tmp_path_factory):
    """干净 venv 的 python：没有 DataChat，也没有它的其他依赖。返回 (python 路径, 装包方式)。"""
    venv = str(tmp_path_factory.mktemp("export-venv") / "venv")
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)      # 不带 --system-site-packages
    py, env = _venv_python(venv), _clean_env()
    mode = os.environ.get("DATACHAT_EXPORT_VENV", "auto")
    used = None
    if mode in ("auto", "pip"):
        try:
            _pip_install(py, env)
            used = "pip"
        except (subprocess.SubprocessError, OSError) as e:
            if mode == "pip":
                raise
            print(f"[export venv] pip 安装失败，改用拷贝：{type(e).__name__}", file=sys.stderr)
    if used is None:
        _copy_install(py, env)
        used = "copy"
    return py, used


def _run(py, args, cwd):
    return subprocess.run([py, "-I", *args], cwd=cwd, env=_clean_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


@pytest.mark.slow
def test_clean_venv_has_no_datachat(clean_python, tmp_path):
    py, used = clean_python
    run_dir = tmp_path / "outside"
    run_dir.mkdir()
    r = _run(py, ["-c", "import app"], run_dir)
    assert r.returncode != 0 and "ModuleNotFoundError: No module named 'app'" in r.stderr
    for mod in ("fastapi", "langgraph", "langchain_core", "sqlalchemy", "keyring", "jieba"):
        r = _run(py, ["-c", f"import {mod}"], run_dir)
        assert r.returncode != 0 and "ModuleNotFoundError" in r.stderr, (mod, used)
    r = _run(py, ["-c", "import pandas, numpy, matplotlib, openpyxl, sys; print(sys.prefix)"], run_dir)
    assert r.returncode == 0, r.stderr
    assert os.path.realpath(r.stdout.strip()) != os.path.realpath(sys.prefix)


HARNESS = r'''
import json, os, runpy, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I 下脚本目录不在 sys.path
import _wire_copy
ns = runpy.run_path(sys.argv[1], run_name="__main__")
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump({"result": _wire_copy.encode(ns.get("result"))}, f, ensure_ascii=False)
'''


def run_exported(py, code, target, tmp_path, *, name="分析"):
    """导出 code（数据 = target）→ 在仓库外的 run 目录用干净 python 跑 → (result, run 目录, stdout)。
    result 用 app/tools/wire.py 的同一套编码带回（wire.py 只依赖 numpy / pandas，拷一份给 harness 用，
    导出的脚本本身不用它）。"""
    target = os.fspath(target)
    if os.path.isdir(target):
        files = sorted(f for f in os.listdir(target)
                       if (f.lower().endswith(".csv") and not f.lower().endswith(".dict.csv"))
                       or f.lower().endswith(".xlsx"))
        data_dir, multi = target, True
    else:
        files, data_dir, multi = [os.path.basename(target)], os.path.dirname(target), False
    text = build_script(code, files=[(f, None) for f in files], data_dir=data_dir, multi_source=multi,
                        meta={"session_title": "测试", "message_id": "m"})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script = run_dir / f"{name}.py"
    script.write_text(text, encoding="utf-8")
    shutil.copy(os.path.join(REPO, "app", "tools", "wire.py"), run_dir / "_wire_copy.py")
    (run_dir / "harness.py").write_text(HARNESS, encoding="utf-8")
    out = run_dir / "out.json"
    r = _run(py, [str(run_dir / "harness.py"), str(script), str(out)], str(run_dir))
    assert r.returncode == 0, r.stderr[-3000:]
    return wire.decode(json.loads(out.read_text(encoding="utf-8"))["result"]), run_dir, r


def sandbox_result(code, target, tmp_path):
    data, _ = load_data(os.fspath(target))
    result, chart, err = run_code(code, data, str(tmp_path / "sbx_chart.png"), timeout=60)
    assert err is None, err
    return result, chart


@pytest.mark.slow
def test_clean_venv_csv_single(clean_python, tmp_path):
    p = tmp_path / "data" / "销售.csv"
    p.parent.mkdir()
    p.write_bytes("地区,销量,编号,日期\n华东,3,00123,2024-01-05\n华北,5,00456,2024-02-01\n华东,4.5,,2024-01-20\n"
                  .encode("gb18030"))                                  # GBK：走编码检测
    code = ("df['月'] = pd.to_datetime(df['日期']).dt.to_period('M').astype(str)\n"
            "result = df.groupby(['地区', '月'], as_index=False).agg(销量=('销量', 'sum'), 编号=('编号', 'max'))\n"
            "print(result.shape)")
    want, _ = sandbox_result(code, p, tmp_path)
    got, run_dir, r = run_exported(clean_python[0], code, p, tmp_path)
    assert_same(got, want)
    assert "地区" in r.stdout                                          # 末尾打印了 result


@pytest.mark.slow
def test_clean_venv_multi_table_dfs(clean_python, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "orders.csv").write_text("oid,uid,amount\n1,u1,10.5\n2,u2,3\n3,u1,7.25\n", encoding="utf-8")
    tx.write_xlsx(d / "users.xlsx", {"用户": [["uid", "city"], ["u1", "北京"], ["u2", "上海"]]})
    (d / "orders.dict.csv").write_text("field,description\namount,金额\n", encoding="utf-8")
    code = ("m = dfs['orders'].merge(dfs['users'], on='uid')\n"
            "result = m.groupby('city')['amount'].agg(['sum', 'count']).sort_values('sum')")
    want, _ = sandbox_result(code, d, tmp_path)
    got, _run_dir, _r = run_exported(clean_python[0], code, d, tmp_path)
    assert_same(got, want)


@pytest.mark.slow
def test_clean_venv_xlsx_multi_sheet(clean_python, tmp_path):
    p = tmp_path / "data" / "book.xlsx"
    p.parent.mkdir()
    _odd_book(p)
    code = ("a = dfs['book.明细']\n"
            "b = dfs['book.汇总']\n"
            "result = {'工号': ','.join(a['工号']), '行数': len(a), '列': '|'.join(map(str, a.columns)),\n"
            "          '线上': float(b['金额-线上'].sum()), '汇总列': '|'.join(map(str, b.columns)),\n"
            "          '地区': ','.join(a['地区'].astype(str)), '日期': ','.join(a['日期'].fillna('缺'))}")
    want, _ = sandbox_result(code, p, tmp_path)
    assert want["工号"] == "00123,04567,00999"                         # 前导零按文本保留
    assert "金额-线上" in want["汇总列"]                                 # 「-」表头
    got, _run_dir, _r = run_exported(clean_python[0], code, p, tmp_path)
    assert_same(got, want)


@pytest.mark.slow
def test_clean_venv_chart(clean_python, tmp_path):
    p = tmp_path / "data" / "s.csv"
    p.parent.mkdir()
    p.write_text("region,units,cost\n华东,3,1\n华北,5,2\n华南,4,3\n", encoding="utf-8")
    code = ("s = df.groupby('region')['units'].sum().sort_values()\n"
            "chart('bar', s, title='各地区销量')\n"
            "chart('line', df, x='region', y=['units', 'cost'])\n"
            "chart('pie', s)\n"
            "chart('scatter', df, x='cost', y='units')\n"
            "chart('bar', df, x='region', y='不存在的列')\n"                # 出错不打断
            "result = s")
    want, _ = sandbox_result(code, p, tmp_path)
    got, run_dir, r = run_exported(clean_python[0], code, p, tmp_path, name="图表")
    assert_same(got, want)
    pngs = sorted(f for f in os.listdir(run_dir) if f.endswith(".png"))
    assert pngs == [f"图表_chart{i}.png" for i in (1, 2, 3, 4)], pngs
    for f in pngs:
        assert (run_dir / f).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "未出图" in r.stderr


@pytest.mark.slow
def test_clean_venv_plt_savefig(clean_python, tmp_path):
    p = tmp_path / "data" / "s.csv"
    p.parent.mkdir()
    p.write_text("region,units\n华东,3\n华北,5\n", encoding="utf-8")
    code = ("fig, ax = plt.subplots()\n"
            "ax.bar(df['region'], df['units'])\n"
            "ax.set_title('销量')\n"
            "plt.savefig('任意名字.png', dpi=80)\n"
            "result = int(df['units'].sum())")
    want, chart = sandbox_result(code, p, tmp_path)
    assert chart is not None                                           # 沙箱里确实出了图
    got, run_dir, _r = run_exported(clean_python[0], code, p, tmp_path, name="画图")
    assert_same(got, want)
    assert (run_dir / "画图_plt.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"   # 落在脚本旁
    assert not (run_dir / "任意名字.png").exists()                      # 与沙箱一样被重定向


@pytest.mark.slow
def test_clean_venv_end_to_end_from_endpoint(clean_python, api, tmp_path):
    """接口导出的原文件（DATA_DIR 指向 DataChat 的数据目录）在干净 venv 里跑出与沙箱相同的 result；
    数据文件改动后 sha256 提示出现。"""
    c, Session, sid, _dl = api
    code = "result = df.assign(code=df['code'].astype(str)).groupby('region').agg({'units': 'mean', 'code': 'min'})"
    _q, mid = _turn(Session, sid, code)
    path = c.post(f"/messages/{mid}/export/code", headers=H).json()["path"]
    run_dir = tmp_path / "far"
    run_dir.mkdir()
    script = run_dir / "x.py"
    shutil.copy(path, script)
    shutil.copy(os.path.join(REPO, "app", "tools", "wire.py"), run_dir / "_wire_copy.py")
    (run_dir / "harness.py").write_text(HARNESS, encoding="utf-8")
    py = clean_python[0]
    r = _run(py, [str(run_dir / "harness.py"), str(script), str(run_dir / "o.json")], str(run_dir))
    assert r.returncode == 0, r.stderr
    assert "sha256 不一致" not in r.stderr
    got = wire.decode(json.loads((run_dir / "o.json").read_text(encoding="utf-8"))["result"])
    data_dir = os.path.dirname(_dataset_file(Session, sid))
    want, _ = sandbox_result(code, os.path.join(data_dir, "销售.csv"), tmp_path)
    assert_same(got, want)
    with open(os.path.join(data_dir, "销售.csv"), "a", encoding="utf-8") as f:
        f.write("华南,1,00001\n")
    r = _run(py, [str(script)], str(run_dir))
    assert r.returncode == 0 and "sha256 不一致" in r.stderr


def _dataset_file(Session, sid):
    from app.server.db import ChatSession, Dataset
    with Session() as db:
        s = db.get(ChatSession, sid)
        return db.get(Dataset, s.dataset_id).files[0].path
