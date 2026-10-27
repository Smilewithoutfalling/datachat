import { Api } from "../api";
import { client } from "../client";
import { dataUrlBytes } from "./pngSaver";

test("dataUrlBytes：base64 PNG data URL 还原成原字节；不是 PNG data URL 抛错", () => {
  const bytes = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff];
  const url = `data:image/png;base64,${btoa(String.fromCharCode(...bytes))}`;
  expect(Array.from(dataUrlBytes(url))).toEqual(bytes);
  expect(() => dataUrlBytes("data:image/svg+xml;base64,AAAA")).toThrow();
  expect(() => dataUrlBytes("https://x/a.png")).toThrow();
});

test("savePng：POST /exports/png?filename=（编码），Bearer、image/png、请求体是字节；返回后端给的路径", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ path: "D:\\Downloads\\图 (1).png" }), { status: 200 });
  }) as unknown as typeof fetch;
  const c = client(new Api("tok", fetchImpl));
  const url = `data:image/png;base64,${btoa("\x89PNG\r\n\x1a\n")}`;
  expect(await c.savePng(url, "图 #1?.png")).toBe("D:\\Downloads\\图 (1).png");
  expect(calls[0].url).toBe(`/exports/png?filename=${encodeURIComponent("图 #1?.png")}`);
  const h = new Headers(calls[0].init.headers);
  expect(h.get("Authorization")).toBe("Bearer tok");
  expect(h.get("Content-Type")).toBe("image/png");
  expect(calls[0].init.method).toBe("POST");
  expect(Array.from(calls[0].init.body as Uint8Array).slice(0, 4)).toEqual([0x89, 0x50, 0x4e, 0x47]);
});
