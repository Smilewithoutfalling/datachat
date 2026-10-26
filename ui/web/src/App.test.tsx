import { fireEvent, render, screen } from "@testing-library/react";
import App, { ExpiredPage } from "./App";
import { RESTART_URL } from "./desktop";
import { Api } from "./api";
import { fakeBackend } from "./fakeBackend";

const res = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("token 失效 → 会话已失效页", async () => {
  render(<App api={new Api("bad", async () => res({ detail: "token 无效" }, 401))} />);
  expect(await screen.findByText("会话已失效")).toBeTruthy();
});

test("没有 token → 会话已失效页", async () => {
  render(<App api={new Api(null)} />);
  expect(await screen.findByText("会话已失效")).toBeTruthy();
});

test("token 有效 → 已连接", async () => {
  const { fetchImpl } = fakeBackend({
    "GET /settings/api-key": { configured: true, source: "keyring" },
    "GET /datasets": [],
    "GET /sessions": [],
  });
  render(<App api={new Api("ok", fetchImpl)} />);
  expect(await screen.findByTestId("ready")).toBeTruthy();
});

test("失效页：浏览器模式给命令，不给「重新启动」（网页端保留）", () => {
  render(<ExpiredPage desktop={false} />);
  expect(screen.getByText("python -m app.server --open")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "重新启动 DataChat" })).toBeNull();
});

test("失效页：桌面壳里不给命令，「重新启动 DataChat」跳到壳拦截的地址（P1-16）", () => {
  const assign = vi.fn();
  const orig = window.location;
  Object.defineProperty(window, "location", { configurable: true, value: { ...orig, assign } });
  try {
    render(<ExpiredPage desktop onRetry={async () => null} />);
    expect(screen.queryByText("python -m app.server --open")).toBeNull();
    expect(screen.getByRole("button", { name: "重试连接" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重新启动 DataChat" }));
    expect(assign).toHaveBeenCalledWith(RESTART_URL);
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: orig });
  }
});
