import { takeToken, TOKEN_KEY } from "./token";

function fakes(hash: string, stored: string | null = null) {
  const data = new Map<string, string>(stored ? [[TOKEN_KEY, stored]] : []);
  const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  const calls: string[] = [];
  const hist = { replaceState: (_s: unknown, _t: string, url?: string | URL | null) => void calls.push(String(url)) };
  return { loc: { hash, pathname: "/", search: "" }, hist, store, data, calls };
}

test("fragment 里的 token：存进 sessionStorage，并同步从地址栏抹掉", () => {
  const f = fakes("#token=abc-123");
  expect(takeToken(f.loc, f.hist, f.store)).toBe("abc-123");
  expect(f.data.get(TOKEN_KEY)).toBe("abc-123");
  expect(f.calls).toEqual(["/"]);
});

test("fragment 里其他参数保留，只去掉 token", () => {
  const f = fakes("#x=1&token=t");
  expect(takeToken(f.loc, f.hist, f.store)).toBe("t");
  expect(f.calls).toEqual(["/#x=1"]);
});

test("没有 fragment：用 sessionStorage 里的（刷新页面）", () => {
  const f = fakes("", "old");
  expect(takeToken(f.loc, f.hist, f.store)).toBe("old");
  expect(f.calls).toEqual([]);
});

test("都没有：返回 null（App 显示会话已失效）", () => {
  const f = fakes("");
  expect(takeToken(f.loc, f.hist, f.store)).toBeNull();
});

test("新 token 覆盖旧的（后端重启后重新 --open）", () => {
  const f = fakes("#token=new", "old");
  expect(takeToken(f.loc, f.hist, f.store)).toBe("new");
  expect(f.data.get(TOKEN_KEY)).toBe("new");
});

test("sessionStorage 写入抛异常：仍返回 token（只在内存），地址栏照样抹掉，不冒到顶层", () => {
  const calls: string[] = [];
  const loc = { hash: "#token=mem-only", pathname: "/", search: "" };
  const hist = { replaceState: (_s: unknown, _t: string, url?: string | URL | null) => void calls.push(String(url)) };
  const store = {
    getItem: () => null,
    setItem: () => {
      throw new DOMException("quota", "QuotaExceededError");
    },
  };
  expect(takeToken(loc, hist, store)).toBe("mem-only");
  expect(calls).toEqual(["/"]);
});

test("先存后抹：replaceState 时 token 已经在 sessionStorage 里", () => {
  const data = new Map<string, string>();
  let storedAtReplace: string | undefined;
  const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  const hist = { replaceState: () => void (storedAtReplace = data.get(TOKEN_KEY)) };
  takeToken({ hash: "#token=t1", pathname: "/", search: "" }, hist, store);
  expect(storedAtReplace).toBe("t1");
});
