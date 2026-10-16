// 测试用的假后端：按 "METHOD path" 路由，记录每次请求
export type Call = { method: string; path: string; body: unknown };
type Handler = (body: unknown, path: string) => unknown;

/** 可控的 SSE 响应：push 一个事件、end 结束。 */
export function sseStream(messageId: string) {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) });
  let seq = 0;
  return {
    response: () =>
      new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream", "X-Message-Id": messageId } }),
    push: (type: string, data: unknown) => {
      const ev = { type, trace_id: messageId, seq: seq++, ts: 0, data };
      ctrl.enqueue(enc.encode(`id: ${ev.seq}\nevent: ${type}\ndata: ${JSON.stringify(ev)}\n\n`));
    },
    end: () => ctrl.close(),
  };
}

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
    if (out instanceof Response) return out; // SSE 等：测试自己构造响应
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { fetchImpl: fetchImpl as typeof fetch, calls };
}
