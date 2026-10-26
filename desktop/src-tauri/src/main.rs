//! DataChat 桌面壳（阶段 6 D1，docs/roadmap/phase6-desktop.md §2）。
//!
//! 壳只做三件事：管 sidecar 进程、开一个窗口、守导航边界。前端完全由 sidecar 托管，只走 HTTP / SSE，
//! 不用 Tauri IPC（M22）：本壳没有 capabilities，任何页面都拿不到 Tauri API。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;

use std::path::PathBuf;
use std::sync::atomic::{AtomicU16, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

/// 前端失效页「重新启动 DataChat」跳到这里（ui/web/src/desktop.ts RESTART_URL），由 on_navigation 拦下。
const RESTART_HOST: &str = "restart.datachat.invalid";

#[derive(Default)]
struct Sc {
    running: Mutex<Option<sidecar::Running>>,
    port: AtomicU16,
    /// 代际：每次启动 +1。监视线程只在代际没变时才把 sidecar 退出当成崩溃，主动停止和重启不算。
    gen: AtomicU64,
}

fn app_page(page: &str, query: &str) -> Url {
    // Tauri 2 在 Windows 上把打包进壳的静态页挂在 http://tauri.localhost/，其他平台是 tauri://localhost/
    let base = if cfg!(windows) { "http://tauri.localhost/" } else { "tauri://localhost/" };
    let mut u = Url::parse(base).unwrap().join(page).unwrap();
    if !query.is_empty() {
        u.set_query(Some(query));
    }
    u
}

fn enc(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

fn is_app_page(u: &Url) -> bool {
    (u.scheme() == "http" && u.host_str() == Some("tauri.localhost")) || u.scheme() == "tauri"
}

/// 启动（或重启）sidecar，成功后把窗口导到前端；失败导到错误页。在后台线程里调。
fn launch(app: &AppHandle) {
    let st = app.state::<Arc<Sc>>().inner().clone();
    let Some(win) = app.get_webview_window("main") else { return };
    let gen = st.gen.fetch_add(1, Ordering::SeqCst) + 1;
    let old = st.running.lock().unwrap().take(); // 先放锁再停，stop 最多等 3 s
    if let Some(old) = old {
        sidecar::stop(&old);
    }
    st.port.store(0, Ordering::SeqCst);
    let _ = win.navigate(app_page("loading.html", ""));
    match sidecar::start(&sidecar::exe_path(), &sidecar::home_dir()) {
        Err(e) => {
            let _ = win.navigate(app_page("error.html", &format!("msg={}", enc(&e))));
        }
        Ok(r) => {
            let url = format!("http://127.0.0.1:{}/#token={}&shell=desktop", r.port, r.token);
            st.port.store(r.port, Ordering::SeqCst);
            let child = r.child.clone();
            *st.running.lock().unwrap() = Some(r);
            let _ = win.navigate(Url::parse(&url).unwrap());
            // 监视：sidecar 中途退出 → 错误页（带退出码和日志位置），页上有「重新启动」
            let app2 = app.clone();
            let st2 = st.clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_millis(500));
                if st2.gen.load(Ordering::SeqCst) != gen {
                    return;
                }
                let code = match child.lock().unwrap().try_wait() {
                    Ok(Some(s)) => s.code(),
                    Ok(None) => continue,
                    Err(_) => None,
                };
                if st2.gen.load(Ordering::SeqCst) != gen {
                    return;
                }
                st2.port.store(0, Ordering::SeqCst);
                let log = sidecar::home_dir().join("server.log");
                let q = format!(
                    "msg={}&log={}",
                    enc(&match code {
                        Some(c) => format!("后台服务意外退出（退出码 {c}）"),
                        None => "后台服务意外退出".into(),
                    }),
                    enc(&log.display().to_string())
                );
                if let Some(w) = app2.get_webview_window("main") {
                    let _ = w.navigate(app_page("error.html", &q));
                }
                return;
            });
        }
    }
}

fn relaunch(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || launch(&app));
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--smoke") {
        let out = args.get(i + 1).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("smoke-shell.json"));
        std::process::exit(sidecar::smoke(&out));
    }
    if let Some(i) = args.iter().position(|a| a == "--smoke-hold") {
        let out = args.get(i + 1).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("sidecar.pid"));
        sidecar::smoke_hold(&out);
    }

    let st = Arc::new(Sc::default());
    tauri::Builder::default()
        // 单实例必须第一个注册：第二次打开只聚焦已有窗口，不起第二个 sidecar（两个进程写同一个 SQLite 会冲突）
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_opener::init())
        .manage(st.clone())
        .setup(move |app| {
            let handle = app.handle().clone();
            let st_nav = st.clone();
            let h_nav = handle.clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("loading.html".into()))
                .title("DataChat")
                .inner_size(1280.0, 800.0)
                .min_inner_size(1024.0, 640.0)
                .on_navigation(move |u| {
                    if is_app_page(u) || matches!(u.scheme(), "blob" | "data" | "about") {
                        return true; // blob: / data:：导出 PNG 的下载链接，同源内容
                    }
                    let port = st_nav.port.load(Ordering::SeqCst);
                    if u.scheme() == "http" && u.host_str() == Some("127.0.0.1") && port != 0 && u.port() == Some(port) {
                        return true;
                    }
                    if u.host_str() == Some(RESTART_HOST) {
                        relaunch(&h_nav);
                        return false;
                    }
                    open_outside(u);
                    false
                })
                .on_new_window(|u, _features| {
                    open_outside(&u);
                    NewWindowResponse::Deny
                })
                .build()?;
            relaunch(&handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("DataChat 启动失败")
        .run(|app, ev| {
            if let RunEvent::Exit = ev {
                let st = app.state::<Arc<Sc>>();
                st.gen.fetch_add(1, Ordering::SeqCst);
                let taken = st.running.lock().unwrap().take();
                if let Some(r) = taken {
                    sidecar::stop(&r);
                }
            }
        });
}

/// 壳外打开：只放行 http / https / mailto，交给系统默认程序；其他协议（file:、javascript: 等）直接丢弃。
fn open_outside(u: &Url) {
    if matches!(u.scheme(), "http" | "https" | "mailto") {
        let _ = tauri_plugin_opener::open_url(u.as_str(), None::<&str>);
    }
}
