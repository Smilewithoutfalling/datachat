"""python -m app.server [--port 8765] [--home 目录] [--token xxx] [--open]

只监听 127.0.0.1。启动后打印一行 JSON：{"port": ..., "token": ...}，桌面外壳读这一行拿到端口和 token；
命令行调试时把 token 填进 Authorization: Bearer 头即可。--port 0 表示自动选空闲端口。
--open：启动后用默认浏览器打开 http://127.0.0.1:端口/#token=…（token 放 fragment：不发给服务器、不进访问日志，
前端读出后立即从地址栏抹掉）。
"""
import argparse
import json
import logging
import os
import re
import socket
import sys


_TOKEN_QS = re.compile(r"([?&]token=)[^&\s]*")


class RedactToken(logging.Filter):
    """访问日志里把 ?token= 的值换成 ***（图表 URL 带 token，不让它落进 server.log）。"""

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(_TOKEN_QS.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = _TOKEN_QS.sub(r"\1***", record.msg)
        return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--home", default=None, help="数据目录（默认 DATACHAT_HOME 或 %%LOCALAPPDATA%%\\datachat）")
    ap.add_argument("--token", default=os.getenv("DATACHAT_TOKEN"), help="默认每次启动随机生成")
    ap.add_argument("--open", action="store_true", help="启动后在浏览器打开前端")
    a = ap.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv()
    import uvicorn
    from app.server.app import create_app

    app = create_app(a.home, a.token)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(app.state.home, "server.log"), encoding="utf-8"),
                                  logging.StreamHandler(sys.stderr)])
    logging.getLogger("uvicorn.access").addFilter(RedactToken())
    sock = socket.socket()
    sock.bind(("127.0.0.1", a.port))
    port = sock.getsockname()[1]
    print(json.dumps({"port": port, "token": app.state.token, "home": app.state.home}), flush=True)
    if a.open:
        import threading
        import webbrowser
        url = f"http://127.0.0.1:{port}/#token={app.state.token}"
        threading.Timer(1.0, webbrowser.open, [url]).start()
    config = uvicorn.Config(app, log_level="info", log_config=None)
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
