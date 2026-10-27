import { describe, expect, it } from "vitest";
import { inDesktopShell, SHELL_KEY } from "./desktop";

function mem(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

describe("inDesktopShell（阶段 6 D1 能力探测）", () => {
  it("fragment 带 shell=desktop 时为真，并记进 sessionStorage", () => {
    const s = mem();
    expect(inDesktopShell({ hash: "#shell=desktop" }, s)).toBe(true);
    expect(s.m.get(SHELL_KEY)).toBe("desktop");
  });
  it("fragment 没有、但本标签页记过时为真", () => {
    expect(inDesktopShell({ hash: "" }, mem({ [SHELL_KEY]: "desktop" }))).toBe(true);
  });
  it("浏览器模式（--open）为假", () => {
    expect(inDesktopShell({ hash: "" }, mem())).toBe(false);
    expect(inDesktopShell({ hash: "#shell=browser" }, mem())).toBe(false);
  });
  it("sessionStorage 抛错时只看 fragment", () => {
    const bad = { getItem: () => { throw new Error("x"); }, setItem: () => { throw new Error("x"); } };
    expect(inDesktopShell({ hash: "#shell=desktop" }, bad)).toBe(true);
    expect(inDesktopShell({ hash: "" }, bad)).toBe(false);
  });
});
