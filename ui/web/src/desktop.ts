// 桌面壳能力探测（阶段 6 D1，phase6-desktop.md「范围」：网页端保留，壳专属功能不能让浏览器模式坏掉）。
// 壳打开前端时用 http://127.0.0.1:端口/#token=…&shell=desktop。takeToken 只抹 token，shell 留在 fragment 里，
// 刷新后仍可读到；另存一份 sessionStorage，防止以后别处改了 fragment。不看 UA：WebView2 的 UA 和 Edge 一样。
export const SHELL_KEY = "datachat.shell";

/** 壳拦截这个地址（on_navigation 返回 false）并重启 sidecar；浏览器里永远不会用到它。.invalid 保证不会解析到真实主机。 */
export const RESTART_URL = "http://restart.datachat.invalid/";

export function inDesktopShell(
  loc: Pick<Location, "hash"> = window.location,
  store: Pick<Storage, "getItem" | "setItem"> = window.sessionStorage,
): boolean {
  const hit = new URLSearchParams(loc.hash.replace(/^#/, "")).get("shell") === "desktop";
  try {
    if (hit) store.setItem(SHELL_KEY, "desktop");
    return hit || store.getItem(SHELL_KEY) === "desktop";
  } catch {
    return hit;
  }
}
