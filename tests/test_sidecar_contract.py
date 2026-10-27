"""sidecar 启动契约（issue #44，docs/sidecar-contract.md）：真起一个子进程，走壳会走的路径。

壳用 --port 0 启动，从 stdout 第一行 JSON 读 {"port","token","home"}。端口独占：不设 SO_REUSEADDR，
运行期间别的 socket 绑不上同一个端口（"只监听 127.0.0.1、只有本进程能收"的前提）。
"""
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def sidecar(tmp_path):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"}
    env.pop("DATACHAT_TOKEN", None)
    p = subprocess.Popen([sys.executable, "-m", "app.server", "--port", "0", "--home", str(tmp_path / "h")],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        line = p.stdout.readline()
        yield p, line, tmp_path / "h"
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def _health(port, tries=100):
    import time
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                return r.status
        except OSError:
            time.sleep(0.1)
    return None


def test_port0_first_line_is_json_with_port_token_home(sidecar):
    _, line, home = sidecar
    info = json.loads(line)                                     # 第一行就是 JSON，前面不能有任何日志
    assert set(info) == {"port", "token", "home"}
    assert isinstance(info["port"], int) and 0 < info["port"] < 65536   # 0 已被换成真实端口
    assert isinstance(info["token"], str) and len(info["token"]) >= 16  # 没传 --token 时随机生成
    assert os.path.samefile(info["home"], home)
    assert _health(info["port"]) == 200


def test_port_is_exclusive_while_running(sidecar):
    _, line, _ = sidecar
    port = json.loads(line)["port"]
    assert _health(port) == 200
    s = socket.socket()
    try:
        with pytest.raises(OSError):                            # 没有 SO_REUSEADDR：别人抢不走这个端口
            s.bind(("127.0.0.1", port))
    finally:
        s.close()


def test_main_sets_no_reuse_options():
    # 代码证据：bind 前不设任何 SO_* 选项（#44：不要用 SO_REUSEADDR 解决 TIME_WAIT，壳用 --port 0）
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "server", "__main__.py"), encoding="utf-8").read()
    assert "setsockopt" not in src and "SO_REUSE" not in src.replace("不设 SO_REUSEADDR", "")


def test_shutdown_endpoint_exits_process(sidecar):
    """阶段 6 D1：壳正常退出时 POST /shutdown，sidecar 自己退出（退出码 0），不用等强杀。"""
    import time
    p, line, _ = sidecar
    info = json.loads(line)
    assert _health(info["port"]) == 200
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/shutdown", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:       # 不带 token：401，不能让本机任意进程关掉它
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401
    assert p.poll() is None
    req.add_header("Authorization", f"Bearer {info['token']}")
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 202
    assert p.wait(timeout=10) == 0
    assert time.monotonic() - t < 8
