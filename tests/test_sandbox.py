import os

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


def test_savefig_restored_after_error(sample_df, chart_path):
    import matplotlib.pyplot as plt
    original = plt.savefig
    run_code("raise ValueError('x')", sample_df, chart_path)
    assert plt.savefig is original


# ---- 已知问题 B01：同进程 exec 可逃逸。修好后这些测试会通过，届时删除 xfail ----
ESCAPES = {
    "shell_via_pandas_module": "result = pd.io.common.os.popen('echo pwned').read()",
    "env_via_pandas_module": "result = dict(pd.io.common.os.environ)",
    "popen_via_subclasses": "result = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'Popen']",
}


@pytest.mark.xfail(raises=AssertionError, reason="B01: 沙箱可逃逸，阶段 2 修复")
@pytest.mark.parametrize("name", list(ESCAPES))
def test_escape_blocked(name, sample_df, chart_path):
    result, _, err = run_code(ESCAPES[name], sample_df, chart_path)
    assert err is not None or not result


@pytest.mark.xfail(raises=AssertionError, reason="B01: 可任意写文件，阶段 2 修复")
def test_file_write_blocked(sample_df, chart_path, tmp_path):
    target = tmp_path / "pwned.csv"
    run_code(f"df.to_csv(r'{target}')\nresult = 1", sample_df, chart_path)
    assert not target.exists()


def test_timeout_reported(sample_df, chart_path):
    # 注意 B02：超时后线程仍在后台运行，这里只验证超时会被报告
    _, _, err = run_code("while True:\n    pass", sample_df, chart_path, timeout=1)
    assert err and "TimeoutError" in err
