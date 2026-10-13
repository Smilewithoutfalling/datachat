"""打包产物的冒烟测试（只用标准库）。在仓库根目录运行：

    python packaging/smoke_sidecar.py dist/datachat-sidecar/datachat-sidecar.exe report.json

1. <exe> --selftest：沙箱各项限制在打包后是否仍然生效（B35）；
2. 启动后端：测启动耗时，走 上传 → 建会话 → 提问（没有 Key，应得到 error → done）→ 查历史；
3. 重启后端（同一数据目录）：会话还在。
退出码非 0 = 有一项失败。报告写成 JSON。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 不走代理：S 的机器常配 HTTP(S)_PROXY，127.0.0.1 的请求被转给代理会 404
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def start(exe, home):
    t = time.perf_counter()
    env = {**os.environ, "DEEPSEEK_API_KEY": ""}
    p = subprocess.Popen([exe, "--port", "0", "--home", home], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", env=env)
    line = p.stdout.readline()
    info = json.loads(line)
    base = f"http://127.0.0.1:{info['port']}"
    while True:                      # 端口已绑定，等 uvicorn 真正开始服务
        try:
            OPENER.open(base + "/health", timeout=2).read()
            break
        except Exception:  # noqa: BLE001
            if time.perf_counter() - t > 120:
                raise
            time.sleep(0.2)
    return p, base, info["token"], round(time.perf_counter() - t, 2)


def req(base, token, method, path, body=None, ctype="application/json"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    with OPENER.open(r, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if resp.headers.get_content_type() == "application/json" else raw


def multipart(path):
    b = uuid.uuid4().hex
    with open(path, "rb") as f:
        content = f.read()
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: text/csv\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def main(exe, out_path):
    report, ok = {"exe": exe}, True
    t = time.perf_counter()
    st = subprocess.run([exe, "--selftest"], capture_output=True, text=True, encoding="utf-8", timeout=600)
    report["selftest_seconds"] = round(time.perf_counter() - t, 2)
    try:
        report["selftest"] = json.loads(st.stdout)
    except ValueError:
        report["selftest"] = {"ok": False, "stdout": st.stdout[-3000:], "stderr": st.stderr[-3000:]}
    ok &= st.returncode == 0

    home = tempfile.mkdtemp(prefix="datachat-smoke-")
    steps = {}
    try:
        p, base, token, steps["startup_seconds"] = start(exe, home)
        body, ctype = multipart(os.path.join(HERE, "data", "sample.csv"))
        ds = req(base, token, "POST", "/datasets", body, ctype)
        steps["dataset_tables"] = ds.get("tables")
        s = req(base, token, "POST", "/sessions", {"dataset_id": ds["id"], "agent": "react"})
        sse = req(base, token, "POST", f"/sessions/{s['id']}/messages", {"content": "总销量"})
        steps["sse_events"] = [l[7:] for l in sse.splitlines() if l.startswith("event: ")]
        p.terminate()
        p.wait(timeout=30)
        p, base, token, steps["restart_seconds"] = start(exe, home)
        sess = req(base, token, "GET", f"/sessions/{s['id']}")
        steps["after_restart_messages"] = [[m["role"], m["status"]] for m in sess["messages"]]
        p.terminate()
        p.wait(timeout=30)
        ok &= bool(steps["dataset_tables"]) and steps["sse_events"] == ["error", "done"] \
            and steps["after_restart_messages"] == [["user", "ok"], ["assistant", "error"]]
    except Exception as e:  # noqa: BLE001
        steps["exception"] = f"{type(e).__name__}: {e}"
        ok = False
    report["server"] = steps
    report["ok"] = bool(ok)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=list)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=list))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1]), sys.argv[2]))
