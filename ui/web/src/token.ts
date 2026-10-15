// token 流转（阶段 5 方案 §1）：后端 --open 打开 http://127.0.0.1:端口/#token=…。
// fragment 不发给服务器、不进访问日志；这里读出后存 sessionStorage（关标签页即失效），
// 并在任何 await 之前同步 replaceState 把它从地址栏和历史记录里抹掉。
export const TOKEN_KEY = "datachat.token";

export function takeToken(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  hist: Pick<History, "replaceState"> = window.history,
  store: Pick<Storage, "getItem" | "setItem"> = window.sessionStorage,
): string | null {
  const params = new URLSearchParams(loc.hash.replace(/^#/, ""));
  const fromHash = params.get("token");
  if (params.has("token")) {
    params.delete("token");
    const rest = params.toString();
    hist.replaceState(null, "", loc.pathname + loc.search + (rest ? `#${rest}` : ""));
  }
  if (fromHash) {
    store.setItem(TOKEN_KEY, fromHash);
    return fromHash;
  }
  return store.getItem(TOKEN_KEY);
}
