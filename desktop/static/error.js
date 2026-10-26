// 壳导到这里时带 ?msg=…&log=…（只是文字，用 textContent，不当 HTML 解析）。
// 「重新启动」是一个普通链接，壳的 on_navigation 拦下后重启 sidecar；不走 IPC。
const q = new URLSearchParams(location.search);
if (q.get("msg")) document.getElementById("msg").textContent = q.get("msg");
if (q.get("log")) {
  document.getElementById("log").textContent = q.get("log");
  document.getElementById("log-row").hidden = false;
}
