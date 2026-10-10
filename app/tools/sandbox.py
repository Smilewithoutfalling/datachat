"""执行模型生成的 pandas 代码（阶段 2：子进程沙箱，解决 B01 B02 B03）。

run_code()：不可信代码。每次在独立子进程里跑（app/tools/sandbox_worker.py）：
- 环境变量只留白名单，API Key 等一概不传；
- 独立临时工作目录，图表与结果都落在里面，主进程只拷回 chart_path；
- 超时由主进程强杀（Windows 关闭 Job Object 连带杀掉，其他平台杀整个进程组），不再有泄漏的线程；
- 内存上限：Windows 用 Job Object（_winjob.py），Linux/macOS 由子进程对自己设 RLIMIT_AS；
- 子进程里装审计钩子，禁止起进程、联网、ctypes、读写工作目录以外的文件（见 sandbox_worker.py）；
- 结果经 JSON 回传（app/tools/wire.py），主进程不反序列化子进程产生的 pickle。
run_trusted()：可信代码（评测的标准答案），在本进程执行，省去子进程启动开销。
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import warnings

import builtins

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # 无界面后端，服务器/脚本下也能出图
import matplotlib.pyplot as plt

from app.tools import wire
from app.tools.plotting import apply_style
from app.tools.sandbox_policy import make_safe_builtins

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_worker.py")
DEFAULT_MEM_MB = int(os.environ.get("DATACHAT_SANDBOX_MEM_MB", "2048"))
STARTUP_TIMEOUT = float(os.environ.get("DATACHAT_SANDBOX_STARTUP_TIMEOUT", "60"))

# 传给子进程的环境变量白名单：只放运行 Python/numpy 必需、且不含机密的变量
_ENV_KEEP = {
    "PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "HOME", "USERPROFILE", "LOCALAPPDATA",
    "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
}


def _child_env(workdir: str, mpl_cache: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    env.update({
        "TMP": workdir, "TEMP": workdir, "TMPDIR": workdir,
        "MPLBACKEND": "Agg", "MPLCONFIGDIR": mpl_cache,
        "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })
    return env


def _mpl_cache_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "datachat-mplcache")
    os.makedirs(d, exist_ok=True)
    return d


def _drain(stream, sink: list, limit: int = 8000):
    try:
        for line in iter(stream.readline, ""):
            sink.append(line)
            while sum(map(len, sink)) > limit and len(sink) > 1:
                sink.pop(0)
    except Exception:
        pass


def _kill(proc, job):
    try:
        if job is not None:
            job.kill()
        elif os.name == "posix":
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class _Worker:
    """一个已启动、正在导入或已就绪（READY）等待任务的沙箱子进程。每个进程只执行一次代码。"""

    def __init__(self):
        self.workdir = tempfile.mkdtemp(prefix="datachat-sbx-")
        mpl_cache = _mpl_cache_dir()
        # 打包成 exe（阶段 6，PyInstaller）后 sys.executable 是应用本身，需要改成 `<exe> --sandbox-worker`
        cmd = [sys.executable, "-I", "-B", "-X", "utf8", _WORKER, self.workdir]
        kwargs = dict(cwd=self.workdir, env=_child_env(self.workdir, mpl_cache), stdin=subprocess.PIPE,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                      errors="replace")
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        self.job = None
        self.err_tail: list = []
        self._ready_line = None
        self._ready = threading.Event()
        try:
            self.proc = subprocess.Popen(cmd, **kwargs)
        except Exception:
            shutil.rmtree(self.workdir, ignore_errors=True)
            raise
        threading.Thread(target=_drain, args=(self.proc.stderr, self.err_tail), daemon=True).start()
        threading.Thread(target=self._wait_ready, daemon=True).start()

    def _wait_ready(self):
        try:
            self._ready_line = self.proc.stdout.readline()
        finally:
            self._ready.set()

    def wait_ready(self, timeout: float) -> bool:
        self._ready.wait(timeout)
        return (self._ready_line or "").strip() == "READY" and self.proc.poll() is None

    def kill(self):
        if self.proc.poll() is None:
            _kill(self.proc, self.job)
            try:
                self.proc.wait(5)
            except Exception:
                pass

    def dispose(self):
        self.kill()
        if self.job is not None:
            self.job.close()
            self.job = None
        shutil.rmtree(self.workdir, ignore_errors=True)


PREWARM = os.environ.get("DATACHAT_SANDBOX_PREWARM", "1") != "0"
_spare_lock = threading.Lock()
_spare: "_Worker | None" = None


def _take_worker() -> _Worker:
    """取一个备用进程（没有就现起一个），并在后台再预启动一个，把下一次的导入开销藏起来。"""
    global _spare
    with _spare_lock:
        w, _spare = _spare, None
        if PREWARM:
            try:
                _spare = _Worker()
            except Exception:
                _spare = None
    if w is None or w.proc.poll() is not None:
        if w is not None:
            w.dispose()
        w = _Worker()
    return w


@atexit.register
def _shutdown_spare():
    global _spare
    with _spare_lock:
        w, _spare = _spare, None
    if w is not None:
        w.dispose()


def run_code(code: str, df: pd.DataFrame, chart_path: str, timeout: float = 20, mem_mb: int | None = None):
    """在子进程沙箱里执行模型生成的 pandas 代码。

    约定：代码使用变量 df，把最终答案赋给 result；若画图则 plt.savefig(chart_path)（任何文件名都会落到 chart_path）。
    返回 (result, chart_path_or_None, error_or_None)。
    """
    mem_mb = DEFAULT_MEM_MB if mem_mb is None else mem_mb
    w = None
    try:
        w = _take_worker()
        if not w.wait_ready(STARTUP_TIMEOUT):
            return None, None, ("SandboxError: 沙箱进程启动失败\n" + "".join(w.err_tail)[-2000:]).rstrip()
        workdir, proc = w.workdir, w.proc
        df.to_pickle(os.path.join(workdir, "input.pkl"))
        with open(os.path.join(workdir, "job.json"), "w", encoding="utf-8") as f:
            json.dump({"code": code, "mem_mb": mem_mb}, f, ensure_ascii=False)

        if os.name == "nt":
            try:
                from app.tools._winjob import Job
                w.job = Job(mem_mb)
                w.job.assign(proc)
            except Exception as e:      # 拿不到 Job（极少见）：照常执行，只是没有内存上限
                warnings.warn(f"沙箱 Job Object 设置失败，本次执行没有内存上限：{e}")
                if w.job is not None:
                    w.job.close()
                w.job = None

        proc.stdin.write("g\n")
        proc.stdin.close()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            w.kill()
            return None, None, f"TimeoutError: 代码执行超过 {timeout} 秒"

        out_path = os.path.join(workdir, "out.json")
        if not os.path.exists(out_path):
            return None, None, (f"SandboxError: 沙箱进程异常退出（退出码 {proc.returncode}），"
                                f"可能超出内存上限 {mem_mb} MB\n" + "".join(w.err_tail)[-1000:]).rstrip()
        with open(out_path, encoding="utf-8") as f:
            out = json.load(f)
        if out.get("error"):
            return None, None, out["error"]
        result = wire.decode(out.get("result"))
        chart = None
        src = os.path.join(workdir, "chart.png")
        if out.get("chart") and os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.abspath(chart_path)), exist_ok=True)
            shutil.copyfile(src, chart_path)
            chart = chart_path
        return result, chart, None
    except Exception:
        return None, None, "SandboxError: " + traceback.format_exc(limit=2)
    finally:
        if w is not None:
            w.dispose()


_TRUSTED_LOCK = threading.Lock()


def run_trusted(code: str, df: pd.DataFrame):
    """在本进程执行可信代码（评测标准答案），返回 (result, error)。不画图、不隔离，勿用于模型代码。"""
    ns = {"__builtins__": make_safe_builtins(builtins), "df": df, "pd": pd, "np": np, "plt": plt,
          "chart_path": os.devnull, "result": None}
    with _TRUSTED_LOCK:
        try:
            apply_style()
            exec(code, ns)
            return ns.get("result"), None
        except Exception:
            return None, traceback.format_exc(limit=3)
        finally:
            plt.close("all")
