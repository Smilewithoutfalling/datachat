"""桌面端 sidecar 的统一入口（阶段 4 spike，PyInstaller 打包用；见 .github/workflows/sidecar.yml）。

    datachat-sidecar [--port N] [--home 目录] [--token T]   启动本地后端（同 python -m app.server）
    datachat-sidecar --sandbox-worker <工作目录>             沙箱子进程（由 app/tools/sandbox.py 启动，B35）
    datachat-sidecar --selftest                              不需要 Key 的自检：沙箱各项限制 + 关键依赖导入，输出 JSON

源码环境下也能跑：python -m app.sidecar --selftest
"""
import json
import os
import sys
import time


def _utf8_stdio():
    for s in (sys.stdout, sys.stderr, sys.stdin):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def selftest() -> int:
    import pandas as pd
    import tempfile

    from app.tools.sandbox import run_code

    df = pd.DataFrame({"region": ["华东", "华北", "华东"], "units": [1, 2, 3]})
    tmp = tempfile.mkdtemp(prefix="datachat-selftest-")
    chart = os.path.join(tmp, "c.png")
    win_ini = "C:/Windows/win.ini" if os.name == "nt" else "/etc/hostname"
    checks = []

    def check(name, fn):
        t = time.perf_counter()
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        checks.append({"name": name, "ok": bool(ok), "seconds": round(time.perf_counter() - t, 2),
                       "detail": str(detail)[:300]})

    def compute():
        r, _, err = run_code("result = df.groupby('region')['units'].sum().to_dict()", df, chart)
        return r == {"华东": 4, "华北": 2}, err or r

    def plot():
        r, c, err = run_code("plt.bar(df['region'], df['units']); plt.savefig('x.png'); result = 1", df, chart)
        return c is not None and os.path.getsize(c) > 0, err or c

    def stdout():
        cap = {}
        r, _, err = run_code("print('你好'); result = 1", df, chart, capture=cap)
        return cap.get("stdout", "").strip() == "你好", err or cap

    def blocked_read():
        # 绕开受限 builtins（没有 open），直接测审计钩子这一层：用 pandas 去读工作目录以外的文件
        r, _, err = run_code(f"result = pd.read_csv({win_ini!r}).shape", df, chart)
        # 必须是因为读目标文件被拦；被拦在别处（例如延迟导入读不到 exe）不算通过——第一次 runner 就是这样假通过的
        target = os.path.normcase(os.path.realpath(win_ini))
        return err is not None and "沙箱禁止读文件" in err and target in os.path.normcase(err), err

    def blocked_import():
        r, _, err = run_code("import subprocess; result = 1", df, chart)
        return err is not None, err

    def timeout():
        r, _, err = run_code("while True: pass", df, chart, timeout=3)
        return err is not None and "Timeout" in err, err

    def memory():
        # 测操作系统那一层（Windows Job Object / Linux RLIMIT_AS）：512 MB 上限下申请约 1.6 GB
        r, _, err = run_code("x = np.ones(200_000_000); result = float(x.sum())", df, chart, mem_mb=512)
        return err is not None and ("MemoryError" in err or "SandboxError" in err), err

    def imports():
        import keyring
        import langchain_openai  # noqa: F401
        import langgraph  # noqa: F401
        import uvicorn  # noqa: F401
        import jieba
        from app.react_agent import build_react_agent  # noqa: F401
        from app.server.app import create_app
        create_app(tempfile.mkdtemp(prefix="datachat-selftest-home-"), "x")
        list(jieba.cut("各地区销量"))
        return True, f"keyring={type(keyring.get_keyring()).__name__}"

    for name, fn in [("compute", compute), ("plot", plot), ("stdout", stdout), ("blocked_read", blocked_read),
                     ("blocked_import", blocked_import), ("timeout", timeout), ("memory", memory),
                     ("imports", imports)]:
        check(name, fn)
    ok = all(c["ok"] for c in checks)
    print(json.dumps({"ok": ok, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable,
                      "checks": checks}, ensure_ascii=False, indent=1), flush=True)
    return 0 if ok else 1


def main():
    _utf8_stdio()
    if len(sys.argv) >= 2 and sys.argv[1] == "--sandbox-worker":
        del sys.argv[1]                            # sandbox_worker.main() 读 sys.argv[1] = 工作目录
        from app.tools import sandbox_worker
        sandbox_worker.main()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    from app.server.__main__ import main as server_main
    server_main(sys.argv[1:])


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
    main()
