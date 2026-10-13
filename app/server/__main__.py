"""python -m app.server [--port 8765] [--home 目录] [--token xxx]

只监听 127.0.0.1。启动后打印一行 JSON：{"port": ..., "token": ...}，桌面外壳读这一行拿到端口和 token；
命令行调试时把 token 填进 Authorization: Bearer 头即可。--port 0 表示自动选空闲端口。
"""
import argparse
import json
import logging
import os
import socket
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--home", default=None, help="数据目录（默认 DATACHAT_HOME 或 %%LOCALAPPDATA%%\\datachat）")
    ap.add_argument("--token", default=os.getenv("DATACHAT_TOKEN"), help="默认每次启动随机生成")
    a = ap.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv()
    import uvicorn
    from app.server.app import create_app

    app = create_app(a.home, a.token)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(app.state.home, "server.log"), encoding="utf-8"),
                                  logging.StreamHandler(sys.stderr)])
    sock = socket.socket()
    sock.bind(("127.0.0.1", a.port))
    port = sock.getsockname()[1]
    print(json.dumps({"port": port, "token": app.state.token, "home": app.state.home}), flush=True)
    config = uvicorn.Config(app, log_level="info", log_config=None)
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
