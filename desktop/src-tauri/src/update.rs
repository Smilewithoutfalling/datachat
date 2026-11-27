//! 自动更新（阶段 6 D3，docs/roadmap/phase6-desktop.md §4，issue #149）。
//!
//! 流程（不用 Tauri IPC，和「重新启动」同一个模式）：
//! 1. sidecar 起来 10 秒后，壳用 tauri-plugin-updater 读 GitHub Releases 的 latest.json；
//! 2. 有新版本：存下 `Update`，并把版本号 PUT 给后端 `/desktop/update`；前端每分钟问一次后端，顶部提示「更新并重启」；
//! 3. 用户点了 → 前端跳到 `http://update.datachat.invalid/` → 壳的 on_navigation 拦下 → 窗口换成 updating.html，
//!    下载、用 tauri.conf.json 里的公钥（minisign）校验、先正常停掉 sidecar，再以 passive 模式运行新安装包；
//!    安装包带 `/UPDATE`：跳过数据文件夹页、沿用原安装目录与数据文件夹（installer.nsi，#148）。装完自动重启。
//! 不静默更新：用户不点就不下载（S 11-27 确认「提示后点一下」）。
//!
//! 公钥为空（还没生成密钥）时整个流程跳过。`DATACHAT_UPDATE_ENDPOINT` 可以覆盖 latest.json 的地址，
//! 只给 CI 的升级验收用（pre-release 不是 GitHub 的 latest）；签名照样用内置公钥校验，覆盖地址换不了包。

use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, Runtime, Url};
use tauri_plugin_updater::{Update, UpdaterExt};

pub const UPDATE_HOST: &str = "update.datachat.invalid";
pub const CHECK_DELAY: Duration = Duration::from_secs(10);
pub const ENDPOINT_ENV: &str = "DATACHAT_UPDATE_ENDPOINT";

#[derive(Default)]
pub struct Pending(pub Mutex<Option<Update>>);

/// tauri.conf.json 的 plugins.updater.pubkey 是否已填。
pub fn configured<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|v| v.get("pubkey"))
        .and_then(|v| v.as_str())
        .is_some_and(|s| !s.trim().is_empty())
}

fn endpoint_override() -> Option<Url> {
    std::env::var(ENDPOINT_ENV).ok().and_then(|s| Url::parse(s.trim()).ok()).filter(|u| u.scheme() == "https")
}

/// 查一次更新。`on_before_exit` 在 Windows 安装器接管前调用（这里用来正常停掉 sidecar，让 SQLite 落盘）。
pub async fn check<R: Runtime>(
    app: &AppHandle<R>,
    on_before_exit: impl Fn() + Send + Sync + 'static,
) -> Result<Option<Update>, String> {
    let mut b = app.updater_builder().on_before_exit(on_before_exit);
    if let Some(u) = endpoint_override() {
        b = b.endpoints(vec![u]).map_err(|e| e.to_string())?;
    }
    b.build().map_err(|e| e.to_string())?.check().await.map_err(|e| e.to_string())
}

/// 把查到的版本告诉后端（前端从后端读）。`notes` 截到 4000 字以内，和后端的上限一致。
pub fn announce(port: u16, token: &str, u: &Update) -> bool {
    let notes: String = u.body.clone().unwrap_or_default().chars().take(4000).collect();
    let body = serde_json::json!({"version": u.version, "notes": notes});
    crate::sidecar::request_json(port, "PUT", "/desktop/update", Some(token), &body) == Some(200)
}

/// `--smoke-update <out.json>`：CI 升级验收用。不开窗口、不起 sidecar：查更新 → 写 JSON → 有就下载安装
/// （安装器接管后本进程退出，装完不自动重启，由 CI 检查安装结果）。退出码：0 已交给安装器；2 没有更新；1 出错。
pub fn smoke(out: &Path, ctx: tauri::Context<tauri::Wry>) -> ! {
    let out = out.to_path_buf();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .build(ctx)
        .expect("DataChat 启动失败");
    let handle = app.handle().clone();
    let code = tauri::async_runtime::block_on(async move {
        let mut rep = serde_json::json!({
            "configured": configured(&handle),
            "current_version": handle.package_info().version.to_string(),
            "endpoint_override": endpoint_override().map(|u| u.to_string()),
        });
        let write = |rep: &serde_json::Value| {
            let _ = std::fs::write(&out, serde_json::to_vec_pretty(rep).unwrap_or_default());
        };
        if !configured(&handle) {
            rep["error"] = "tauri.conf.json 没有更新公钥".into();
            write(&rep);
            return 1;
        }
        match check(&handle, || {}).await {
            Err(e) => {
                rep["error"] = e.into();
                write(&rep);
                1
            }
            Ok(None) => {
                rep["found"] = false.into();
                write(&rep);
                2
            }
            Ok(Some(u)) => {
                rep["found"] = true.into();
                rep["version"] = u.version.clone().into();
                write(&rep);
                let u = u.restart_after_install(false);
                match u.download_and_install(|_, _| {}, || {}).await {
                    Ok(()) => 0, // Windows 上走不到这里：安装器接管后进程已退出
                    Err(e) => {
                        rep["error"] = e.to_string().into();
                        write(&rep);
                        1
                    }
                }
            }
        }
    });
    std::process::exit(code);
}

/// sidecar 起来后调用一次：等 10 秒，查更新，查到就存下并告诉后端。查不到或出错只记日志，不打扰用户。
pub fn spawn_check<R: Runtime>(app: &AppHandle<R>, port: u16, token: String, stop_sidecar: impl Fn() + Send + Sync + 'static) {
    if !configured(app) {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio_sleep(CHECK_DELAY).await;
        match check(&app, stop_sidecar).await {
            Ok(Some(u)) => {
                announce(port, &token, &u);
                *app.state::<Pending>().0.lock().unwrap() = Some(u);
            }
            Ok(None) => {}
            Err(e) => eprintln!("检查更新失败：{e}"),
        }
    });
}

async fn tokio_sleep(d: Duration) {
    // 不为一个 sleep 引入 tokio 依赖：放到阻塞线程里睡
    let _ = tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await;
}

/// 用户点了「更新并重启」：下载并安装。成功时（Windows）进程由安装器接管后退出；失败返回中文原因。
pub async fn install<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let u = app.state::<Pending>().0.lock().unwrap().take().ok_or("没有待安装的更新，请重启 DataChat 后再试")?;
    u.download_and_install(|_, _| {}, || {}).await.map_err(|e| format!("更新失败：{e}"))
}
