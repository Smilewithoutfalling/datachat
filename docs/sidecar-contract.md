# sidecar 启动契约

桌面壳（Tauri 2，阶段 6）和 sidecar（`python -m app.server`，打包后是 `datachat-sidecar.exe`）之间的约定。来源 issue #44，DEVLOG [46]。测试见 `tests/test_sidecar_contract.py`。

## 启动

- 壳**必须**用 `--port 0` 启动 sidecar，由系统分配空闲端口。不要传固定端口：上一次运行的端口可能还处在 TIME_WAIT，会报 Address already in use。
- `--home <目录>`：数据目录。不传时用 `DATACHAT_HOME`，再不行用 `%LOCALAPPDATA%\datachat`。
- `--desktop`：桌面壳**必须**传。开启 `POST /exports/png`，把前端导出的 PNG 写进用户的「下载」文件夹（取 Windows 已知文件夹 FOLDERID_Downloads；`DATACHAT_EXPORT_DIR` 可覆盖）。不传时这个接口返回 404，浏览器模式照旧用 `<a download>`。
- `--token`：一般不传，sidecar 每次启动随机生成。

## 握手

- sidecar 的 stdout **第一行**是一行 JSON：`{"port": <int>, "token": <str>, "home": <str>}`。这一行之前不会有别的输出（日志走 stderr 和 `home/server.log`）。
- 壳读到这一行之后，轮询 `GET http://127.0.0.1:<port>/health`，返回 200 就算就绪。端口在打印之前已经 bind 好，所以不存在打印后被别人抢走的窗口。
- 前端地址是 `http://127.0.0.1:<port>/#token=<token>`。token 放在 fragment 里，不发给服务器，也不进访问日志。其余 API 都用 `Authorization: Bearer <token>`。
- 参考实现：`packaging/smoke_sidecar.py`。

## 模型连接接口（阶段 6.5）

都要 Bearer。任何响应都不含 Key，只有 `key: {needed, configured}`。方案见 docs/roadmap/phase65-models.md。

- `GET /providers`：服务商预设（app/core/providers.json）和协议列表。
- `GET /connections`、`POST /connections`、`PUT /connections/{id}`、`DELETE /connections/{id}`：连接的增删改查。删除时一并删掉钥匙串里的 `conn:<id>`；删除生效连接后，最早建的连接接替。
- `PUT /connections/{id}/api-key`、`DELETE /connections/{id}/api-key`：Key 存进系统钥匙串，service `datachat`，account `conn:<id>`。
- `POST /connections/{id}/activate`：设为生效连接。第一个建的连接自动生效。
- `POST /connections/{id}/test`：两步测试（连接 + 工具调用探测），结果存进连接的 `probe`。和 `/settings/test` 共用一把锁。
- `GET /connections/{id}/models`：读服务商的 `/models`，超时 10 秒；失败或 Azure 时返回预设模型，并给出原因（`source: "preset"`）。
- 兼容：旧的 `GET/PUT /settings`、`PUT/DELETE /settings/api-key`、`POST /settings/test` 保留一个版本，作用于当前生效的连接；没有任何连接时，作用于 `DEEPSEEK_*` 环境变量那个只读虚拟连接。
- 启动时执行一次旧设置迁移（规则见方案 §4）。

## 记忆与保留（阶段 6.6）

方案见 docs/roadmap/memory-system-spec.md（M0、§3.7、§14.3）。

- `DELETE /messages/{id}`：删除一轮（助手消息和紧挨在它前面的那条用户消息），事件和反馈级联删除，图表 PNG 一并删除。成功返回 204；传入用户消息返回 400；找不到返回 404；同一会话还有正在分析的消息时返回 409。
- `DELETE /sessions/{id}`、`DELETE /datasets/{id}`：现在会连带删除这些会话产出的图表 PNG。
- `GET /settings` 新增 `memory: {mode, setting, env}`：`mode` 是实际生效值，`env` 非空表示被环境变量 `DATACHAT_MEMORY` 覆盖。`PUT /settings` 接受 `memory_mode: "off" | "state"`，默认 `off`。
- 数据库空间回收：新库使用 `auto_vacuum=INCREMENTAL`；旧库只在启动时、开始监听之前，并且空闲页超过 25% 时转换一次；`POST /shutdown` 只执行有上限的 `incremental_vacuum`。

## 端口独占（不要改）

- sidecar 只监听 127.0.0.1，bind 前不设任何 `SO_*` 选项。
- **不要**加 `SO_REUSEADDR`。在 Windows 上，它是唯一能重绑 TIME_WAIT 端口的选项，但同时也允许别的进程抢占同一个端口，会破坏"只有本进程能收"这个前提。
- `SO_EXCLUSIVEADDRUSE` 只防别人来抢，不解决 TIME_WAIT，加了没用。
- 测试 `test_port_is_exclusive_while_running` 钉住了这一点：sidecar 运行期间，另一个 socket 绑不上同一个端口。

## 测试工具

- Playwright 的 webServer 要求事先知道端口，不能用 `--port 0` 再读 stdout。所以 `ui/web/playwright.config.ts` 在主进程里随机挑一组端口（P、P+1、P+2），写回 `E2E_PORT`，worker 进程继承同一组。显式设置 `E2E_PORT` 时就用设置的值。
