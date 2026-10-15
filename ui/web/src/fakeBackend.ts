// 测试用的假后端：按 "METHOD path" 路由，记录每次请求
export type Call = { method: string; path: string; body: unknown };
type Handler = (body: unknown, path: string) => unknown;

export function fakeBackend(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  const fetchImpl = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://x");
    const method = (init.method ?? "GET").toUpperCase();
    const raw = init.body;
    const body = typeof raw === "string" ? JSON.parse(raw) : raw;
    calls.push({ method, path: url.pathname + url.search, body });
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.split(" ");
      return m === method && (p === url.pathname || p === url.pathname + url.search);
    });
    if (!key) return new Response(JSON.stringify({ detail: `no route ${method} ${url.pathname}` }), { status: 404 });
    const h = routes[key];
    const out = typeof h === "function" ? (h as Handler)(body, url.pathname) : h;
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { fetchImpl: fetchImpl as typeof fetch, calls };
}
