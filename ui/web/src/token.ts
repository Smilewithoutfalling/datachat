// token 流转（阶段 5 方案 §1）：后端 --open 打开 http://127.0.0.1:端口/#token=…。
// fragment 不发给服务器、不进访问日志。顺序：先存 sessionStorage（关标签页即失效），再在任何 await 之前
// 同步 replaceState 把它从地址栏和历史记录里抹掉。存失败（配额、隐私设置）不抛：token 只留在内存里，
// 这一页照常可用；地址栏照样抹（T7'：token 不进历史），之后刷新会进"会话已失效"页，与新标签页一致。
export const TOKEN_KEY = "datachat.token";

export function takeToken(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  hist: Pick<History, "replaceState"> = window.history,
  store: Pick<Storage, "getItem" | "setItem"> = window.sessionStorage,
): string | null {
  const params = new URLSearchParams(loc.hash.replace(/^#/, ""));
  const fromHash = params.get("token");
  if (fromHash) {
    try {
      store.setItem(TOKEN_KEY, fromHash);
    } catch {
      /* 存不进就只放内存 */
    }
  }
  if (params.has("token")) {
    params.delete("token");
    const rest = params.toString();
    hist.replaceState(null, "", loc.pathname + loc.search + (rest ? `#${rest}` : ""));
  }
  if (fromHash) return fromHash;
  try {
    return store.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
