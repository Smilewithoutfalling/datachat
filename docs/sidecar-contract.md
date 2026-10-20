# sidecar 启动契约

桌面壳（Tauri 2，阶段 6）和 sidecar（`python -m app.server`，打包后是 `datachat-sidecar.exe`）之间的约定。来源 issue #44，DEVLOG [46]。测试见 `tests/test_sidecar_contract.py`。

## 启动

- 壳**必须**用 `--port 0` 启动 sidecar，由系统分配空闲端口。不要传固定端口：上一次运行的端口可能还处在 TIME_WAIT，会报 Address already in use。
- `--home <目录>`：数据目录。不传时用 `DATACHAT_HOME`，再不行用 `%LOCALAPPDATA%\datachat`。
- `--token`：一般不传，sidecar 每次启动随机生成。

## 握手

- sidecar 的 stdout **第一行**是一行 JSON：`{"port": <int>, "token": <str>, "home": <str>}`。这一行之前不会有别的输出（日志走 stderr 和 `home/server.log`）。
- 壳读到这一行之后，轮询 `GET http://127.0.0.1:<port>/health`，返回 200 就算就绪。端口在打印之前已经 bind 好，所以不存在打印后被别人抢走的窗口。
- 前端地址是 `http://127.0.0.1:<port>/#token=<token>`。token 放在 fragment 里，不发给服务器，也不进访问日志。其余 API 都用 `Authorization: Bearer <token>`。
- 参考实现：`packaging/smoke_sidecar.py`。

## 端口独占（不要改）

- sidecar 只监听 127.0.0.1，bind 前不设任何 `SO_*` 选项。
- **不要**加 `SO_REUSEADDR`。在 Windows 上，它是唯一能重绑 TIME_WAIT 端口的选项，但同时也允许别的进程抢占同一个端口，会破坏"只有本进程能收"这个前提。
- `SO_EXCLUSIVEADDRUSE` 只防别人来抢，不解决 TIME_WAIT，加了没用。
- 测试 `test_port_is_exclusive_while_running` 钉住了这一点：sidecar 运行期间，另一个 socket 绑不上同一个端口。

## 测试工具

- Playwright 的 webServer 要求事先知道端口，不能用 `--port 0` 再读 stdout。所以 `ui/web/playwright.config.ts` 在主进程里随机挑一组端口（P、P+1、P+2），写回 `E2E_PORT`，worker 进程继承同一组。显式设置 `E2E_PORT` 时就用设置的值。
