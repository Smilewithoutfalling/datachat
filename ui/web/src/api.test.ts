import { Api, ApiError, Unauthorized } from "./api";

const ok = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("带 Bearer 头，不带 cookie", async () => {
  const seen: RequestInit[] = [];
  const api = new Api("tok", async (_p, init) => (seen.push(init!), ok({ a: 1 })));
  expect(await api.json("/x")).toEqual({ a: 1 });
  expect(new Headers(seen[0].headers).get("Authorization")).toBe("Bearer tok");
  expect(seen[0].credentials).toBe("omit");
});

test("401 → 通知监听者并抛 Unauthorized", async () => {
  const api = new Api("tok", async () => ok({ detail: "token 无效" }, 401));
  const hit = vi.fn();
  api.onUnauthorized(hit);
  await expect(api.json("/x")).rejects.toBeInstanceOf(Unauthorized);
  expect(hit).toHaveBeenCalledOnce();
});

test("没有 token：不发请求，直接按失效处理", async () => {
  const f = vi.fn();
  const api = new Api(null, f);
  const hit = vi.fn();
  api.onUnauthorized(hit);
  await expect(api.request("/x")).rejects.toBeInstanceOf(Unauthorized);
  expect(f).not.toHaveBeenCalled();
  expect(hit).toHaveBeenCalledOnce();
});

test("其他错误码带上后端的 detail", async () => {
  const api = new Api("tok", async () => ok({ detail: "这个会话还有一条消息在分析中" }, 409));
  await expect(api.json("/x")).rejects.toEqual(new ApiError(409, "这个会话还有一条消息在分析中"));
});
