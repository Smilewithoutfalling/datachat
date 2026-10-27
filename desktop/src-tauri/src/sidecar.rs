//! sidecar 进程管理（阶段 6 D1，docs/sidecar-contract.md、docs/roadmap/phase6-desktop.md §2）。
//!
//! 启动：`--port 0 --home <数据目录>` → 读 stdout 第一行 JSON {port, token, home} → 轮询 /health。
//! 退出：POST /shutdown（Bearer）→ 等 3 s → 强杀。壳崩溃或被强杀时，靠 Job Object 的
//! KILL_ON_JOB_CLOSE 由系统把 sidecar（和它的沙箱 worker）一起结束，不留孤儿进程占着 SQLite。
//! 只用标准库做 HTTP：只有 127.0.0.1 上的两三个请求，不值得引入 HTTP 客户端。

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub const START_TIMEOUT: Duration = Duration::from_secs(20);
pub const SHUTDOWN_GRACE: Duration = Duration::from_secs(3);

pub struct Running {
    pub child: Arc<Mutex<Child>>,
    pub port: u16,
    pub token: String,
    pub pid: u32,
    #[cfg(windows)]
    _job: Option<win32job::Job>,
}

/// sidecar 可执行文件：安装后在壳的旁边 `sidecar/datachat-sidecar.exe`（tauri.conf.json bundle.resources）。
/// `DATACHAT_SIDECAR` 可以覆盖（开发时指向源码环境的包装脚本或 CI 的 dist）。
pub fn exe_path() -> PathBuf {
    if let Ok(p) = std::env::var("DATACHAT_SIDECAR") {
        return PathBuf::from(p);
    }
    let dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_default();
    let name = if cfg!(windows) { "datachat-sidecar.exe" } else { "datachat-sidecar" };
    dir.join("sidecar").join(name)
}

/// 数据目录：和浏览器模式（python -m app.server --open）的默认值一致，两种打开方式共用同一份数据。
pub fn home_dir() -> PathBuf {
    if let Ok(p) = std::env::var("DATACHAT_HOME") {
        return PathBuf::from(p);
    }
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into_owned());
    PathBuf::from(base).join("datachat")
}

pub fn start(exe: &Path, home: &Path) -> Result<Running, String> {
    if !exe.exists() {
        return Err(format!("找不到后台服务程序：{}", exe.display()));
    }
    let mut cmd = Command::new(exe);
    cmd.arg("--port").arg("0").arg("--home").arg(home);
    cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null()); // 日志在 home/server.log
    cmd.env_remove("DATACHAT_TOKEN"); // token 每次随机生成（sidecar-contract.md）
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd.spawn().map_err(|e| format!("启动后台服务失败：{e}"))?;
    let pid = child.id();

    #[cfg(windows)]
    let job = match job_for(&child) {
        Ok(j) => Some(j),
        Err(e) => {
            let _ = child.kill();
            return Err(format!("创建进程组失败：{e}"));
        }
    };

    // 第一行 JSON；之后继续把 stdout 读空，免得管道写满把 sidecar 卡住。
    let stdout = child.stdout.take().ok_or("拿不到后台服务的输出")?;
    let (tx, rx) = mpsc::channel::<String>();
    std::thread::spawn(move || {
        let mut r = BufReader::new(stdout);
        let mut line = String::new();
        if r.read_line(&mut line).is_ok() {
            let _ = tx.send(line);
        }
        let _ = std::io::copy(&mut r, &mut std::io::sink());
    });
    let t0 = Instant::now();
    let line = match rx.recv_timeout(START_TIMEOUT) {
        Ok(l) if !l.trim().is_empty() => l,
        _ => {
            let code = child.try_wait().ok().flatten().and_then(|s| s.code());
            let _ = child.kill();
            return Err(match code {
                Some(c) => format!("后台服务启动后立即退出（退出码 {c}）"),
                None => "后台服务 20 秒内没有报告端口".into(),
            });
        }
    };
    let info: serde_json::Value = serde_json::from_str(line.trim()).map_err(|_| {
        let _ = child.kill();
        "后台服务的握手行不是 JSON".to_string()
    })?;
    let port = info["port"].as_u64().filter(|p| *p > 0 && *p < 65536).map(|p| p as u16);
    let token = info["token"].as_str().map(str::to_owned);
    let (Some(port), Some(token)) = (port, token) else {
        let _ = child.kill();
        return Err("后台服务的握手行缺少 port / token".into());
    };
    let left = START_TIMEOUT.saturating_sub(t0.elapsed());
    if !wait_health(port, left) {
        let _ = child.kill();
        return Err("后台服务没有在 20 秒内就绪".into());
    }
    Ok(Running {
        child: Arc::new(Mutex::new(child)),
        port,
        token,
        pid,
        #[cfg(windows)]
        _job: job,
    })
}

#[cfg(windows)]
fn job_for(child: &Child) -> Result<win32job::Job, String> {
    use std::os::windows::io::AsRawHandle;
    let job = win32job::Job::create().map_err(|e| e.to_string())?;
    let mut info = job.query_extended_limit_info().map_err(|e| e.to_string())?;
    info.limit_kill_on_job_close();
    job.set_extended_limit_info(&info).map_err(|e| e.to_string())?;
    job.assign_process(child.as_raw_handle() as isize).map_err(|e| e.to_string())?;
    Ok(job)
}

/// 发一个 HTTP/1.1 请求，返回状态码。Host 必须是 127.0.0.1:<port>（后端 TrustedHost 挡 DNS rebinding）。
pub fn request(port: u16, method: &str, path: &str, token: Option<&str>) -> Option<u16> {
    let mut s = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_secs(2)).ok()?;
    s.set_read_timeout(Some(Duration::from_secs(5))).ok()?;
    let auth = token.map(|t| format!("Authorization: Bearer {t}\r\n")).unwrap_or_default();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{auth}Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).ok()?;
    let mut head = [0u8; 12];
    s.read_exact(&mut head).ok()?;
    std::str::from_utf8(&head[9..12]).ok()?.parse().ok()
}

pub fn wait_health(port: u16, within: Duration) -> bool {
    let t0 = Instant::now();
    while t0.elapsed() < within {
        if request(port, "GET", "/health", None) == Some(200) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

/// 正常退出：先请后端自己退，3 s 内没退再强杀。返回 sidecar 的退出码（强杀时 None）。
pub fn stop(r: &Running) -> Option<i32> {
    let _ = request(r.port, "POST", "/shutdown", Some(&r.token));
    let t0 = Instant::now();
    loop {
        if let Ok(Some(st)) = r.child.lock().unwrap().try_wait() {
            return st.code();
        }
        if t0.elapsed() > SHUTDOWN_GRACE {
            let mut c = r.child.lock().unwrap();
            let _ = c.kill();
            let _ = c.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

/// `--smoke <out.json>`：不开窗口，走一遍壳的启动 → 请求首页 → 正常退出，结果写 JSON。CI 安装冒烟用。
pub fn smoke(out: &Path) -> i32 {
    let home = std::env::temp_dir().join(format!("datachat-smoke-{}", std::process::id()));
    let exe = exe_path();
    let t0 = Instant::now();
    let mut rep = serde_json::json!({"sidecar": exe.display().to_string()});
    let ok = match start(&exe, &home) {
        Err(e) => {
            rep["error"] = e.into();
            false
        }
        Ok(r) => {
            rep["start_ms"] = (t0.elapsed().as_millis() as u64).into();
            let index = request(r.port, "GET", "/", None);
            rep["index_status"] = index.map(u64::from).into();
            let t1 = Instant::now();
            let code = stop(&r);
            rep["shutdown_ms"] = (t1.elapsed().as_millis() as u64).into();
            rep["exit_code"] = code.into();
            index == Some(200) && code == Some(0)
        }
    };
    rep["ok"] = ok.into();
    let _ = std::fs::write(out, serde_json::to_vec_pretty(&rep).unwrap_or_default());
    let _ = std::fs::remove_dir_all(&home);
    if ok { 0 } else { 1 }
}

/// `--smoke-hold <pid.txt>`：起 sidecar，把它的 pid 写进文件后一直挂着。CI 用 taskkill /F 结束壳，
/// 再检查 sidecar 是否被 Job Object 一起带走。
pub fn smoke_hold(pid_file: &Path) -> ! {
    let home = std::env::temp_dir().join(format!("datachat-hold-{}", std::process::id()));
    match start(&exe_path(), &home) {
        Ok(r) => {
            let _ = std::fs::write(pid_file, r.pid.to_string());
            let _keep = r;
            loop {
                std::thread::sleep(Duration::from_secs(60));
            }
        }
        Err(e) => {
            let _ = std::fs::write(pid_file, format!("error: {e}"));
            std::process::exit(1)
        }
    }
}
