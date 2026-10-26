// V2d §2e：卡片头部显示本轮 token。真数照写；有估算时加「≈」和说明；一次调用都没有（reported 为 null）不显示；分析中不显示。
import { render, screen } from "@testing-library/react";
import { type Turn, turnTokens } from "../turn";
import { TurnView } from "./TurnView";

const OK = { ok: true, answer: "结论", error: null, error_kind: null, warnings: [], charts: [], timings: { total: 3.2 } };
const turn = (status: string, result: Record<string, unknown> | null): Turn =>
  ({ status, events: [], result, live: false }) as unknown as Turn;
const usage = (u: Record<string, unknown>) => ({ ...OK, usage: { calls: 3, total_tokens: 0, estimated_tokens: 0, estimated: false, reported: true, ...u } });

describe("turnTokens", () => {
  test("真数 + 估算相加，estimated 跟随", () => {
    expect(turnTokens(turn("ok", usage({ total_tokens: 1200 })))).toEqual({ n: 1200, estimated: false });
    expect(turnTokens(turn("ok", usage({ total_tokens: 100, estimated_tokens: 50, estimated: true, reported: false })))).toEqual({
      n: 150,
      estimated: true,
    });
  });
  test("零调用 / 没有 usage / 没有结果 → null", () => {
    expect(turnTokens(turn("error", usage({ calls: 0, reported: null })))).toBeNull();
    expect(turnTokens(turn("ok", OK))).toBeNull();
    expect(turnTokens(turn("running", null))).toBeNull();
  });
});

describe("卡片头部", () => {
  test("用时旁显示 tokens，千分位", () => {
    render(<TurnView turn={turn("ok", usage({ total_tokens: 140010 }))} />);
    const el = screen.getByTestId("turn-tokens");
    expect(el.textContent).toBe(" · 140,010 tokens");
    expect(el.getAttribute("title")).toBeNull();
  });
  test("估算：≈ + title 说明", () => {
    render(<TurnView turn={turn("ok", usage({ estimated_tokens: 900, estimated: true, reported: false }))} />);
    const el = screen.getByTestId("turn-tokens");
    expect(el.textContent).toBe(" · ≈900 tokens");
    expect(el.getAttribute("title")).toBe("服务商未返回用量，按字数估算");
  });
  test("零调用的失败轮不显示", () => {
    render(<TurnView turn={turn("error", { ...usage({ calls: 0, reported: null }), ok: false, error: "x", error_kind: "dataset" })} />);
    expect(screen.queryByTestId("turn-tokens")).toBeNull();
  });
});
