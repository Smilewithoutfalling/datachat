# 阶段 6：桌面打包（D1、D2 已完成；D3~D5 推迟到对外分发前）

来源：plan.md 阶段 6 的交付物与验收；M19（签名 / SmartScreen / 干净机器验证）、M22（外壳选型）；sidecar 契约 docs/sidecar-contract.md；阶段 4 spike DEVLOG [18]；phase5 F5 末尾的「阶段 6 前置事项」。

**为什么单独写一份文件，不写进 phase5-frontend.md**：phase5 已经 1300 多行，阶段 6 是新阶段，有自己的步骤和验收。HANDOVER §3 的「方案先行」照旧适用，只是换了文件。

## 范围（S 10-26 定）

S 定：**目前只在自己的电脑上安装使用，不对外分发**，§1 的建议全部采纳。所以：
- **现在做**：D1 壳 + 安装包、D2 首次启动 + (a) 提示。
- **推迟到对外分发之前**：D3 自动更新（自己用的话，重装新的安装包就能升级，数据保留）、D4 许可证审计、D5 代码签名、§1 第 5 条发布渠道和第 6 条许可证。对外分发的前提条件不变：签名、许可证、THREAT_MODEL (a) 重新确认，三者缺一不可。
- **网页端保留**（S 10-26 定）：`python -m app.server --open` 用浏览器打开，这条路径继续支持。e2e 测试照旧跑在浏览器上。壳专属的功能（重启 sidecar、单实例）不能让浏览器模式坏掉：前端用能力探测决定是否显示这类按钮，不用 UA 判断。D2 的首次启动引导和 (a) 提示两种模式都要有。阶段 8 的 Web 服务器版继续复用同一套前后端。
- 未签名的安装包在 S 本机第一次运行时，SmartScreen 会拦一次（点「更多信息 → 仍要运行」），之后同一个文件不会再拦。

## 0. 已有的地基（不重做）

- sidecar：PyInstaller onedir，在 windows-latest 上打包，冒烟用 `packaging/smoke_sidecar.py` 覆盖自检、后端、重启。zip 85.7 MB（sidecar run 40282390448，去掉 pyarrow 之后）；冷启动约 1.5 s（[18]）。
- 启动契约：壳用 `--port 0` 启动 → 读 stdout 第一行 JSON `{port, token, home}` → 轮询 `/health` → 打开 `http://127.0.0.1:<port>/#token=<token>`（sidecar-contract.md）。
- 前端只通过 HTTP / SSE 和后端通信，不用 Tauri IPC（S 10-12 定，M22 回应）。壳可以换，换壳不用改前端。
- 后端托管 dist 并带 CSP，前端已经能在 Firefox 里完整走一遍（F5 已通过）。

## 1. 要 S 先定的（D0）

| # | 问题 | 我的建议 | 理由 |
|---|---|---|---|
| 1 | 外壳：Tauri 2 还是 Electron | **Tauri 2** | M22 担心的几处成本，在这里都已经卸掉了：前端不碰 IPC；sidecar 自己管进程；Rust 只写大约 200 行的进程管理；构建全在 CI 里，S 不用装 Rust。Electron 会多带一个 Chromium（约 100 MB），而且 Node 和 Python 两套运行时并存 |
| 2 | 安装包格式 | **NSIS，按当前用户安装**（`installMode: currentUser`，不要管理员权限，装到 `%LOCALAPPDATA%\Programs\DataChat`） | 不弹 UAC；S 的本机就是普通用户场景。MSI 适合企业批量部署，现在用不上 |
| 3 | WebView2 怎么装 | **downloadBootstrapper**（Tauri 默认）：缺 WebView2 时联网装 | Win11 自带 WebView2，Win10 一般也已经通过系统更新装上了，离线安装包要多出约 127 MB。离线场景另出一个包，放到以后再做 |
| 4 | 卸载时删不删数据 | **默认不删**。数据目录 `%LOCALAPPDATA%\datachat`（会话、数据集、server.log）和钥匙串里的 Key 都保留；卸载页给一个「同时删除我的数据」的勾选框 | 重装或升级后历史都还在；想彻底删的用户也有出口 |
| 5 | 发布渠道 | **GitHub Releases**（仓库是公开的），自动更新读 Release 里的 `latest.json` | 不用另找服务器 |
| 6 | 仓库许可证 | 要 S 定（MIT / Apache-2.0 / 不开源） | 仓库现在**没有 LICENSE**（GitHub API 返回 license=null），默认就是保留所有权利。这一项影响 §6 免费签名能不能申请、第三方声明怎么写，也影响别人能不能合法使用 |

## 2. D1 壳：进程管理与窗口（spike + 实现）

**规则（已定待评审）**
1. sidecar 放在 `bundle.resources`，**不用 `externalBin`**。externalBin 只拷单个 exe，PyInstaller onedir 的 `_internal/` 会丢（Tauri 文档 v2.tauri.app/develop/sidecar；社区里多个项目踩过这个坑，都改成了 resources，比如 openworker、HostWise 的提交）。Rust 用 `std::process::Command` 从 `resource_dir()/sidecar/datachat-sidecar.exe` 启动，不引入 tauri-plugin-shell。
2. 启动：`--port 0 --home %LOCALAPPDATA%\datachat`，`CREATE_NO_WINDOW`（不弹黑框），stdout 用管道接，stderr 丢弃（日志已经写进 server.log）。读第一行 JSON（超时 20 s）→ 轮询 `/health`（每 100 ms 一次，总超时 20 s）→ 主窗口 `navigate` 到 `http://127.0.0.1:<port>/#token=<token>`。等待期间窗口显示本地的「正在启动…」页（打包进壳的静态 html，不经 sidecar）。
3. **sidecar 不能变成孤儿进程**：壳一启动就建一个 Job Object，设 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，把 sidecar 放进去。壳不管是正常退出、崩溃还是被任务管理器结束，sidecar 都会被系统一起杀掉。正常退出时先 `POST /shutdown`（新接口，要 Bearer），等 3 s 再强杀。理由：Windows 没有「父进程死了子进程跟着死」的默认行为，没有 Job Object 的话，残留的 sidecar 会一直占着 SQLite 和端口。
   - 注意：沙箱 worker 已经在**另一个** Job Object 里（内存上限）。Win8 起 Job 可以嵌套，嵌套是否生效要在 spike 里实测（worker 的内存上限在嵌套后仍然生效、壳被杀后 worker 也会消失）。
   - 实测（DEVLOG [70]）：内存上限由 desktop.yml ①b 的 `--smoke-selftest` 在 CI 验证；「壳被杀后正在运行的 worker 也消失」由 S 本机验收。
4. sidecar 中途退出：窗口切到本地错误页，显示退出码和 server.log 最后 20 行（先打码，复用 T11 的打码函数），并提供「重新启动」按钮。顺带解决 P1-16（「重新打开应用」在浏览器里做不到，到了壳里就能做）。
5. 单实例：`tauri-plugin-single-instance`。第二次打开时聚焦已有窗口，不再起第二个 sidecar（两个 sidecar 写同一个 SQLite 会冲突）。
6. 导航边界：主窗口只允许 `http://127.0.0.1:<本次端口>/` 和本地启动页、错误页。其他地址（结论里的 Markdown 链接、`target=_blank`）一律用系统默认浏览器打开，不在壳里打开（`on_navigation` + `on_new_window`）。capabilities 给远程 URL 的权限为空：127.0.0.1 页面拿不到任何 Tauri API，T9 的防线不因为套了壳而变弱。
7. 下载：导出 PNG 走 WebView2 自带的下载流程，默认存到「下载」文件夹。在 spike 里确认 WebView2 不会弹出意外的对话框；如果会，再用 `on_download` 处理。
8. 代理：S 的机器常配系统代理，[18] 里遇到过 127.0.0.1 被代理转发、返回 404。Chromium 默认对 loopback 绕过代理，WebView2 应该一样。spike 在 runner 上设好系统代理再跑一遍，确认这一点；如果不绕过，就给 WebView2 加 `--proxy-bypass-list=<loopback>`。
9. 窗口：标题 DataChat，最小 1024×640（25 屏就是按 1024 设计的），记住上次的大小和位置。

**验收**
- CI（windows-latest）：`tauri build` 出 NSIS 安装包，作为工件上传。
- CI 自动冒烟：静默安装（`/S`）→ 用 `--smoke` 参数启动已安装的壳（无界面模式：起 sidecar、等 health、请求一次首页、正常退出，退出码 0）→ 检查进程表里没有残留的 sidecar → 再启动一次，`taskkill /F` 结束壳，检查 sidecar 也跟着消失 → 静默卸载，安装目录被删除、数据目录还在。
- S 本机：下载安装包 → 双击安装（未签名，SmartScreen 点「更多信息 → 仍要运行」）→ 从开始菜单打开 → F5 的五条路径里挑 ① 和 ② 再走一遍 → 关闭窗口后，任务管理器里没有 datachat-sidecar。

## 3. D2 首次启动与发布约束

1. 首次启动（钥匙串里没有 Key）：直接进设置页，顶部加一句引导「先填 API Key，再上传 CSV」。复用现有的设置页和测试连接，不另做向导。
2. **THREAT_MODEL §4 (a) 欠的账**：(a) 要求「首次加载 CSV 时提示不要加载来路不明的文件」，现在没有实现（`grep -rn 来路不明 ui/web/src app` 为空）。在上传对话框里加一行常驻提示：「只分析你自己的数据。不要加载来路不明的 CSV：表里的内容会被模型读到。」不做成弹窗，也不做「不再提示」开关。
3. 安装说明（README 加「安装」一节）写明产品定位是「只分析自己的数据」，不写「可安全打开别人给的数据」。

**验收**：vitest 断言首次进入时落在设置页，并且上传对话框里有这行提示；e2e 加一条首次启动的用例（fake 项目，文件名按 f[34]* 的规则）。

## D1/D2 实现与偏离（10-26，DEVLOG [69]）

- §2 第 2 条：导航地址多带一个 `&shell=desktop`，给前端做能力探测（`ui/web/src/desktop.ts`）。`takeToken` 只抹 token，这个标记留在 fragment 里。
- §2 第 4 条：错误页**只显示退出码和 server.log 的路径，不显示日志内容**。T11 的打码函数在 Python 里，壳是 Rust，重写一遍打码规则容易漏，宁可不显示。要看日志就按路径打开。
- §2 第 4 条「重新启动」：不用 IPC。错误页和前端失效页都跳到 `http://restart.datachat.invalid/`，壳的 `on_navigation` 拦下（返回 false）后重启 sidecar。`.invalid` 保证真去解析也解析不到。
- §2 第 6 条：`blob:` / `data:` / `about:` 放行（导出 PNG 的下载链接是 blob:）。外链只放行 http / https / mailto 交给系统浏览器，其他协议直接丢弃。
- §2 第 8 条（代理）：CI 的 `--smoke` 用 Rust 直连 127.0.0.1，测不到 WebView2 的代理行为，没有在 runner 上做。改由 S 本机验收（S 的机器本来就配了系统代理）。
- §3 第 1 条：首次启动落在设置页是现状（Shell.tsx：没 Key 时初始视图就是设置），只改了引导文案。
- §3 验收「e2e 首次启动用例」：放在 f0.spec.ts（nokey 项目），不放 f[34]*。fake 项目已经配了 Key，测不了「没有 Key」。
- 卸载页「删除应用数据」：Tauri 自带的勾选框只删 `%LOCALAPPDATA%\<identifier>`，而数据目录是 `%LOCALAPPDATA%\datachat`（和浏览器模式共用），所以用 `hooks.nsh` 的 POSTUNINSTALL 补删；默认不勾，静默卸载不删。钥匙串里的 Key 不删（README「安装」写了怎么手动删）。
- 图标是临时的（蓝底白柱，PIL 生成），对外分发前再换。
- S 10-27 本机试装后的修改（DEVLOG [70]）：
  - 导出 PNG 在桌面模式下改由后端写进「下载」文件夹：`POST /exports/png`，只在 `--desktop` 时开放。这样 §2 第 6 条放行 `blob:` / `data:` 的规则就不再承担下载。
  - `GET /settings` 新增 `sources`，设置页显示每一项值的来源，并注明桌面版不读取 `.env`。
- **遗留（D3 之前处理）**：安装目录 `%LOCALAPPDATA%\DataChat` 和数据目录 `%LOCALAPPDATA%\datachat` 在 NTFS 上其实是同一个目录。目前不会出错，因为卸载时只删自己装的文件，删目录用的是不递归的 RMDir。但做自动更新之前必须把两者分开，有两种办法：一是改安装目录（NSIS 模板或 productName），二是改数据目录（要迁移数据，还会影响浏览器模式共用同一份数据）。

## 4. D3 自动更新

1. `tauri-plugin-updater`，endpoint 指向 GitHub Releases 的 `latest.json`。启动 10 s 后检查一次：有新版本就在顶栏提示「有新版本 x.y.z」，用户点了才下载、安装、重启，不静默更新。
2. 更新包用 Tauri 的更新签名（minisign）校验，**和 Authenticode 代码签名无关**，没有代码签名证书也能做。私钥放进 GitHub Secret `TAURI_SIGNING_PRIVATE_KEY`：密钥对由我在沙箱里生成，私钥由 S 亲手粘贴进 Secrets，私钥本身不进仓库、不进对话。公钥写进 `tauri.conf.json`。
3. 版本号：`tauri.conf.json` 的 version 是唯一来源，打 tag `v0.x.y` 时触发 release 工作流，构建、签名、发 Release，并生成 latest.json。
4. 数据兼容：升级不碰数据目录。SQLite 迁移沿用现有做法（启动时补表，参见 v1 → feedback 表的 `test_v1_database_gains_feedback_table_without_touching_old_tables`）。之后每次改表都要带一条「旧库启动」的测试。

**验收**：CI 发两个版本（v0.1.0 → v0.1.1 的测试 Release，标为 pre-release），在 runner 上装旧版 → 让它检查更新 → 装上新版 → 版本号变了、旧会话还在。S 本机手动验证一次。

## 5. D4 依赖许可证审计

1. 三套依赖各用一个工具：Python 用 `pip-licenses`（只扫 requirements.txt 的运行依赖，不扫 dev），前端用 `license-checker`（只扫 production），Rust 用 `cargo-about`。产出 `THIRD_PARTY_NOTICES.txt`，打进安装包，在设置页「关于」里能打开。
2. CI 闸门：出现 GPL / AGPL / LGPL / SSPL / 未知许可证就红，例外要逐条写进白名单并说明理由。已知的一条：PyInstaller 本体是 GPL，但带 bootloader 例外，打出来的程序不受 GPL 约束，写进白名单。
3. 我先跑一遍出结果，有问题的依赖在方案评审时一并处理。

## 6. D5 代码签名（前置事项，S 或有主体的一方办）

**先更正 phase5 F5 末尾的一句话**：那里写的是「EV 对 SmartScreen 立刻生效」。这个说法 2024 年起就不成立了。微软 2024 年 8 月从 Trusted Root Program 里去掉了 EV 代码签名 OID，现在 OV 和 EV 一样，SmartScreen 信誉都要靠时间和下载量慢慢积累，没有哪种证书能立刻免掉提示（Microsoft Learn「SmartScreen reputation for Windows app developers」和「Code signing options for Windows app developers」，2026）。所以 plan.md 的验收「SmartScreen 不拦」要改写成：**签名后显示已验证的发布者名称，不再显示「未知发布者」；SmartScreen 提示随信誉积累逐渐消失**。

| 路线 | 费用 | 能不能办 | 备注 |
|---|---|---|---|
| Azure Artifact Signing（原 Trusted Signing） | 9.99 美元/月 | **目前不行**：公共信任证书只开放给部分国家的组织和美加的个人，中国不在列表里 | 微软推荐的路线；以后开放了再看 |
| OV 证书（DigiCert、Sectigo 等） | 每年 150~300 美元 | 需要营业执照（组织）；私钥必须放在硬件 token 或云 HSM 里（CA/B 论坛 2023 年 6 月起的要求） | 国内有主体时最现实；云 HSM 版本可以在 CI 里签 |
| 个人代码签名证书（例如 Certum 的个人证书或开源证书） | 每年几十欧元起 | 要以个人身份做实名验证，证书上写个人姓名 | 价格和是否接受中国个人，以 CA 官网为准，申请前再核实 |
| SignPath Foundation（开源项目免费） | 免费 | 前提是 OSI 许可证 + 公开仓库 + 可复现的 CI 构建 | 取决于 §1 第 6 条许可证怎么定 |
| 不签名 | 0 | 可以 | 只适合 S 自己用和小范围内测；每个用户都会看到「未知发布者」 |

**已定待评审**：阶段 6 的 D1~D4 全部按**未签名**做完、验收完，签名不阻塞开发。CI 里预留签名步骤：Secret 存在就签，不存在就跳过并在工件名里标 `unsigned`。对外分发（给 S 以外的人）之前，必须办好签名，并且在 THREAT_MODEL 里重新确认 (a)。

材料（以 OV 为例，具体以 CA 要求为准）：营业执照、对公电话（CA 会回访）、申请人身份证明、域名或邮箱验证；云 HSM 版本还要开 CA 的签名账号。

## 7. 顺序和工作量

| 步 | 内容 | PR | S 要做的 |
|---|---|---|---|
| D0 | 本方案 + §1 的 6 个决定 | 本 PR | 评审 |
| D1 | 壳 spike → 实现 + CI 安装冒烟 | 实现 PR 1 | 本机装一次，走 ①② |
| D2 | 首次启动 + (a) 提示 + README 安装一节 | 并进实现 PR 1 | 同上 |
| D3 | 自动更新 + release 工作流 | 实现 PR 2 | 粘贴 Secret；本机验一次升级 |
| D4 | 许可证审计 + 关于页 | 并进实现 PR 2 | 看一眼白名单 |
| D5 | 签名 | 等主体 | 申请证书 |

工作方式的偏离：沙箱是 aarch64 Linux，**Windows 的 Tauri 打包只能在 CI 上跑**，所以每改一次壳都要等一轮 windows-latest 构建，预计 10~15 分钟（Rust 首次编译慢，之后靠 cache）。Rust 部分我本地只能做 `cargo check` 级别的检查。

## 8. 不做

- macOS / Linux 安装包；离线 WebView2 包；静默自动更新；托盘常驻；开机自启。
- 把前端打进壳、绕过 sidecar 托管（会破坏「换壳不改前端」和 CSP 只有一份来源的前提）。
- THREAT_MODEL (b)：OS 级隔离仍然放在阶段 8；选了 (a)，就不对外宣传能打开别人给的数据。
