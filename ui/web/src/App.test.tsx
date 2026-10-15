import { render, screen } from "@testing-library/react";
import App from "./App";
import { Api } from "./api";

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
  render(<App api={new Api("ok", async () => res({ configured: true, source: "keyring" }))} />);
  expect(await screen.findByTestId("ready")).toBeTruthy();
});
