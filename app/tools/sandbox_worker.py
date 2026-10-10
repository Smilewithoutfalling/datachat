"""沙箱子进程（阶段 2，B01 B02 B03）。由 app/tools/sandbox.py 用 `python -I sandbox_worker.py <工作目录>` 启动。

流程：导入 pandas/matplotlib、设好绘图样式 → 向 stdout 写 READY（主进程可以预启动一个备用进程）
→ 等主进程写好 job.json 与 input.pkl（主进程写的，可信）、Windows 上把本进程放进 Job Object，再在 stdin 发 go
→ 读任务、设内存上限、装审计钩子 → exec 模型代码 → 结果用 JSON（app/tools/wire.py）写到 out.json，图存成 chart.png。

隔离层次：
1. 进程：与主进程分开，环境变量只留白名单（不含 API Key）；超时由主进程强杀；内存上限（Linux RLIMIT_AS、
   Windows Job Object）；Windows 上 Job 限制同时只能有 1 个进程（无法再起子进程）。
2. 审计钩子（sys.addaudithook，装上后无法移除）：禁止起进程、联网、ctypes、注册表、sqlite、gc 遍历对象、
   访问 traceback/生成器的帧；读文件只允许 Python 安装目录、字体目录、工作目录；写文件只允许工作目录。
   Python 文档说明审计钩子不是严格的安全边界，它是纵深防御的一层，不是唯一一层。
3. 受限 builtins + import 白名单（沿用阶段 1.5）。
"""
import builtins
import io
import json
import os
import sys
import traceback

_BLOCKED_PREFIXES = (
    "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile", "os.fork",
    "os.forkpty", "os.kill", "os.killpg", "os.chdir", "os.fchdir", "os.chroot",
    "socket.", "ctypes.", "winreg.", "_winapi.", "msvcrt.", "sqlite3.", "urllib.", "http.", "ftplib.",
    "smtplib.", "poplib.", "imaplib.", "nntplib.", "telnetlib.", "webbrowser.", "pty.",
    "gc.get_objects", "gc.get_referrers", "gc.get_referents", "sys._current_frames",
    "sys._current_exceptions", "pickle.find_class", "cpython.", "_xxsubinterpreters.",
)
_WRITE_EVENTS = {
    "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.utime",
    "os.symlink", "os.link", "os.chflags", "os.lchflags", "os.setxattr", "os.removexattr",
    "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.rmtree",
    "shutil.move", "shutil.chown", "shutil.make_archive", "shutil.unpack_archive",
}
_LIST_EVENTS = {"os.listdir", "os.scandir", "glob.glob", "glob.glob/2", "os.listxattr", "os.getxattr"}
# 这几个属性的读取会触发 object.__getattr__ 审计事件；禁掉以免从 traceback/生成器拿到外层帧
_FRAME_ATTRS = {"tb_frame", "gi_frame", "cr_frame", "ag_frame"}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _norm(p):
    if isinstance(p, bytes):
        p = os.fsdecode(p)
    p = os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(p))))
    return p


def _under(p, roots):
    for r in roots:
        try:
            if p == r or os.path.commonpath([p, r]) == r:
                return True
        except ValueError:          # Windows 不同盘符
            continue
    return False


def _install_guard(read_roots, write_roots):
    """装审计钩子。钩子与它引用的目录列表只存在于闭包里，函数返回后没有任何名字指向它们。"""
    read_roots = tuple(_norm(r) for r in read_roots if r)
    write_roots = tuple(_norm(r) for r in write_roots if r)
    read_roots = read_roots + write_roots
    blocked, write_events, list_events, frame_attrs = (
        _BLOCKED_PREFIXES, frozenset(_WRITE_EVENTS), frozenset(_LIST_EVENTS), frozenset(_FRAME_ATTRS))
    PathLike = os.PathLike

    def _path_args(args):
        for a in args:
            if isinstance(a, (str, bytes, PathLike)):
                yield _norm(a)

    def hook(event, args):
        if event.startswith(blocked):
            raise PermissionError(f"沙箱禁止操作：{event}")
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            if path is None or isinstance(path, int):
                return
            p = _norm(path)
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                mode is None and isinstance(flags, int) and flags & _WRITE_FLAGS)
            if writing and not _under(p, write_roots):
                raise PermissionError(f"沙箱禁止写文件：{path}")
            if not _under(p, read_roots):
                raise PermissionError(f"沙箱禁止读文件：{path}")
        elif event in write_events:
            for p in _path_args(args):
                if not _under(p, write_roots):
                    raise PermissionError(f"沙箱禁止修改文件：{p}")
        elif event in list_events:
            for p in _path_args(args[:1]):
                if not _under(p, read_roots):
                    raise PermissionError(f"沙箱禁止列目录：{p}")
        elif event == "object.__getattr__" and len(args) > 1 and args[1] in frame_attrs:
            raise PermissionError(f"沙箱禁止访问 {args[1]}")

    sys.addaudithook(hook)


def _read_roots(workdir, extra):
    import sysconfig
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, workdir}
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        try:
            roots.add(sysconfig.get_path(key))
        except Exception:
            pass
    roots.update(p for p in sys.path if p and os.path.isdir(p) and "site-packages" in p)
    try:
        import matplotlib
        roots.add(matplotlib.get_data_path())
        roots.add(matplotlib.get_cachedir())
    except Exception:
        pass
    for p in ("C:/Windows/Fonts", "/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/zoneinfo",
              "/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/.fonts"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")):
        if p and os.path.isdir(p):
            roots.add(p)
    roots.update(extra or [])
    return roots


def _limit_memory(mem_mb):
    """Linux/macOS：对自己设地址空间上限（软硬相同，之后无法调高）。Windows 由主进程的 Job Object 负责。"""
    if os.name != "posix" or not mem_mb:
        return
    try:
        import resource
        limit = int(mem_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass


def _format_error(e):
    """不经过帧对象（tb_frame 已被禁，traceback 模块会去读它）格式化报错：模型代码的行号 + 异常本身。"""
    lines = ["Traceback (most recent call last):"]
    tb = e.__traceback__
    linenos = []
    while tb is not None:
        linenos.append(tb.tb_lineno)
        tb = tb.tb_next
    if len(linenos) > 1:                     # 第 0 层是 worker 里的 exec，第 1 层是模型代码
        lines.append(f'  File "<string>", line {linenos[1]}, in <module>')
    cls = type(e)
    name = cls.__qualname__ if cls.__module__ in ("builtins", "__main__") else f"{cls.__module__}.{cls.__qualname__}"
    if isinstance(e, SyntaxError):
        lines.append(f'  File "<string>", line {e.lineno}')
        if e.text:
            lines.append("    " + e.text.strip())
        lines.append(f"{name}: {e.msg}")
    else:
        msg = str(e)
        lines.append(f"{name}: {msg}" if msg else name)
    return "\n".join(lines) + "\n"


def main():
    workdir = os.path.abspath(sys.argv[1])
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(workdir)

    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from app.tools.plotting import apply_style
    from app.tools import wire
    from app.tools.sandbox_policy import make_safe_builtins

    apply_style()
    # 预热：让 pandas 常见的延迟导入（strptime、时区、格式化）在装钩子之前完成
    pd.Timestamp("2024-01-31").strftime("%Y-%m")
    pd.to_datetime(pd.Series(["2024-01-01"]))
    read_roots = _read_roots(workdir, None)

    # 预启动：导入完成后报 READY，进程可以先备着；主进程写好 job.json / input.pkl 后再发 go
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    if sys.stdin.read(2)[:1] != "g":        # 主进程放弃了这个进程
        return

    job = json.load(open(os.path.join(workdir, "job.json"), encoding="utf-8"))
    df = pd.read_pickle(os.path.join(workdir, "input.pkl"))
    os.remove(os.path.join(workdir, "input.pkl"))
    chart_path = os.path.join(workdir, "chart.png")
    out_path = os.path.join(workdir, "out.json")
    code = job["code"]

    _orig_savefig = plt.savefig

    def _redirect_savefig(*args, **kwargs):
        kwargs.pop("fname", None)
        return _orig_savefig(chart_path, **kwargs)

    plt.savefig = _redirect_savefig
    ns = {"__builtins__": make_safe_builtins(builtins), "df": df, "pd": pd, "np": np, "plt": plt,
          "chart_path": chart_path, "result": None, "__name__": "__sandbox__"}

    real_stdout = sys.stdout
    sys.stdout = sys.stderr = io.StringIO()   # 模型代码的 print 不回传
    _limit_memory(job.get("mem_mb"))
    _install_guard(read_roots, [workdir, os.environ.get("MPLCONFIGDIR")])
    del job
    out = {"error": None, "result": None, "chart": False}
    try:
        exec(compile(code, "<string>", "exec"), ns)
    except BaseException as e:
        out["error"] = _format_error(e)
    if out["error"] is None:
        try:
            if plt.get_fignums():
                _orig_savefig(chart_path)
        except Exception:
            pass
        try:
            out["result"] = wire.encode(ns.get("result"))
        except Exception:
            out["error"] = "结果无法回传：" + _format_error(sys.exc_info()[1])
    plt.close("all")
    out["chart"] = os.path.exists(chart_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    real_stdout.write("DONE\n")
    real_stdout.flush()


if __name__ == "__main__":
    main()
