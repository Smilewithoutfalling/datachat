import os

import pandas as pd
import pytest

from app.tools.sandbox import run_code


def test_result_returned(sample_df, chart_path):
    result, chart, err = run_code("result = int(df['units'].sum())", sample_df, chart_path)
    assert err is None and result == int(sample_df["units"].sum()) and chart is None


def test_chart_saved_even_with_other_filename(sample_df, chart_path):
    code = "df.groupby('region')['units'].sum().plot.bar()\nplt.savefig('other.png')\nresult = 1"
    _, chart, err = run_code(code, sample_df, chart_path)
    assert err is None and chart == chart_path and os.path.exists(chart_path)
    assert not os.path.exists("other.png")


def test_runtime_error_reported(sample_df, chart_path):
    _, _, err = run_code("result = df['no_such_col']", sample_df, chart_path)
    assert err and "KeyError" in err


def test_import_blocked(sample_df, chart_path):
    _, _, err = run_code("import os", sample_df, chart_path)
    assert err is not None


def test_parent_matplotlib_untouched(sample_df, chart_path):
    # B03：模型代码在子进程里改 plt / rcParams，不影响主进程
    import matplotlib.pyplot as plt
    original = plt.savefig
    run_code("plt.savefig = None\nplt.rcParams['font.size'] = 99\nraise ValueError('x')", sample_df, chart_path)
    assert plt.savefig is original and plt.rcParams["font.size"] != 99


# ---- B01（阶段 2 已修）：逃逸用例全部被挡 ----
ESCAPES = {
    "shell_via_pandas_module": "result = pd.io.common.os.popen('echo pwned').read()",
    "system_via_pandas_module": "result = pd.io.common.os.system('echo pwned')",
    "popen_via_subclasses": "result = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'Popen'][0](['echo', 'x'])",
    # CDLL(None) 在 Windows 上先在 ctypes 的 Python 代码里报 TypeError，到不了 dlopen；按平台给真实库名
    "ctypes_dlopen": "ct = pd.io.common.os.sys.modules['ctypes']\n"
                     "result = ct.CDLL('kernel32' if pd.io.common.os.name == 'nt' else 'libc.so.6')",
    "ctypes_memory_read": "result = pd.io.common.os.sys.modules['ctypes'].string_at(4096, 8)",  # 被拦则不会真去读这个地址
    "socket": "result = pd.io.common.os.sys.modules['socket'].create_connection(('1.1.1.1', 80))",
    "gc_walk": "result = pd.io.common.os.sys.modules['gc'].get_objects()[:1]",
    "frame_via_traceback": "try:\n    1/0\nexcept Exception as e:\n    result = e.__traceback__.tb_frame",
}


@pytest.mark.parametrize("name", list(ESCAPES))
def test_escape_blocked(name, sample_df, chart_path):
    result, _, err = run_code(ESCAPES[name], sample_df, chart_path)
    assert err is not None and "PermissionError" in err and not result


def test_api_key_not_in_child_env(sample_df, chart_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("SOME_TOKEN", "tok-should-not-leak")
    result, _, err = run_code("result = dict(pd.io.common.os.environ)", sample_df, chart_path)
    assert err is None
    assert "DEEPSEEK_API_KEY" not in result and "sk-should-not-leak" not in str(result)
    assert "SOME_TOKEN" not in result


def test_file_write_blocked(sample_df, chart_path, tmp_path):
    target = tmp_path / "pwned.csv"
    _, _, err = run_code(f"df.to_csv(r'{target}')\nresult = 1", sample_df, chart_path)
    assert not target.exists() and err and "PermissionError" in err


def test_file_read_outside_blocked(sample_df, chart_path, tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("DEEPSEEK_API_KEY=sk-on-disk\n", encoding="utf-8")
    for code in (f"result = pd.read_csv(r'{secret}')", f"result = pd.io.common.os.listdir(r'{tmp_path}')"):
        result, _, err = run_code(code, sample_df, chart_path)
        assert result is None and err and "PermissionError" in err


def test_workdir_write_allowed_and_cleaned(sample_df, chart_path):
    result, _, err = run_code("df.to_csv('tmp.csv')\nresult = len(pd.read_csv('tmp.csv'))", sample_df, chart_path)
    assert err is None and result == len(sample_df)


def test_timeout_kills_process(sample_df, chart_path):
    # B02：超时强杀子进程（旧版线程杀不掉）
    import time
    t = time.perf_counter()
    _, _, err = run_code("while True:\n    pass", sample_df, chart_path, timeout=1)
    assert err and "TimeoutError" in err
    assert time.perf_counter() - t < 15


def test_memory_limit(sample_df, chart_path):
    _, _, err = run_code("x = np.ones(512 * 1024 ** 2)\nresult = 1", sample_df, chart_path, mem_mb=1024)
    assert err and ("MemoryError" in err or "SandboxError" in err)


def test_concurrent_runs_isolated(sample_df, tmp_path):
    # B03：并发执行各自有工作目录与 matplotlib 状态，结果与图表互不串
    from concurrent.futures import ThreadPoolExecutor
    def job(i):
        path = str(tmp_path / f"c{i}.png")
        code = f"plt.plot([0, {i}])\nplt.savefig('x.png')\nresult = {i}"
        return i, run_code(code, sample_df, path)
    with ThreadPoolExecutor(4) as ex:
        for i, (result, chart, err) in ex.map(job, range(4)):
            assert err is None and result == i and chart and chart.endswith(f"c{i}.png") and os.path.exists(chart)


def test_result_types_round_trip(sample_df, chart_path):
    code = ("d = df.copy(); d['date'] = pd.to_datetime(d['date'])\n"
            "m = d.groupby(d['date'].dt.to_period('M'))['units'].sum()\n"
            "e = d.set_index('date')['units'].resample('ME').sum()\n"
            "mi = d.groupby(['region', 'product'])['units'].sum()\n"
            "result = {'m': m, 'e': e, 'mi': mi, 'pv': mi.unstack(), 'np': np.float64(1.5), 't': ('a', 2),"
            " 'ts': pd.Timestamp('2024-01-31'), 'nan': float('nan'), 'none': None}")
    result, _, err = run_code(code, sample_df, chart_path)
    assert err is None
    assert isinstance(result["m"].index, pd.PeriodIndex)
    assert isinstance(result["e"].index, pd.DatetimeIndex)
    assert isinstance(result["mi"].index, pd.MultiIndex) and result["mi"].index.names == ["region", "product"]
    assert result["pv"].shape == (len(result["mi"].index.levels[0]), len(result["mi"].index.levels[1]))
    assert result["np"] == 1.5 and result["t"] == ("a", 2) and result["ts"] == pd.Timestamp("2024-01-31")
    assert result["nan"] != result["nan"] and result["none"] is None


def test_timestamp_strftime_works(sample_df, chart_path):
    result, _, err = run_code("result = pd.Timestamp('2024-05-31').strftime('%Y-%m')", sample_df, chart_path)
    assert err is None and result == "2024-05"


# ---- B28/B29：白名单 import ----
def test_whitelisted_imports_and_np(sample_df, chart_path):
    code = "import numpy as np\nimport matplotlib.pyplot as plt\nfrom math import sqrt\nresult = float(np.sqrt(sqrt(16)))"
    result, _, err = run_code(code, sample_df, chart_path)
    assert err is None and result == 2.0
    result, _, err = run_code("result = int(np.sum(df['units']))", sample_df, chart_path)
    assert err is None and result == int(sample_df["units"].sum())


@pytest.mark.parametrize("mod", ["os", "subprocess", "sys", "shutil", "importlib"])
def test_other_imports_blocked(sample_df, chart_path, mod):
    _, _, err = run_code(f"import {mod}\nresult = 1", sample_df, chart_path)
    assert err and "ImportError" in err and mod in err
