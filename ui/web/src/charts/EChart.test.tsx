// EChart 组件：挂载 / 卸载配对、resize 由 ResizeObserver 触发；TurnView 截断夹具：图和后端截断警告同时出现（单一来源）。
// jsdom 没有 canvas，测试里把 init 换成真 init + SVG renderer + 固定尺寸，其余（setOption、dispose、getInstanceByDom）都是真 ECharts。
import { render, screen } from "@testing-library/react";
import * as core from "echarts/core";
import fixtures from "../generated/chart_fixtures.json";
import type { Turn } from "../turn";
import { TurnView } from "../views/TurnView";
import { EChart, type ChartSpec } from "./EChart";

const { created } = vi.hoisted(() => ({ created: [] as import("echarts/core").ECharts[] }));
vi.mock("echarts/core", async (orig) => {
  const real = await orig<typeof import("echarts/core")>();
  real.use([(await import("echarts/renderers")).SVGRenderer]);
  return {
    ...real,
    init: vi.fn((el: HTMLElement, theme: unknown, opts: Record<string, unknown>) => {
      expect(opts.renderer).toBe("canvas"); // 产品代码要的是 canvas
      const c = real.init(el, theme as null, { ...opts, renderer: "svg", width: 400, height: 300 });
      created.push(c);
      return c;
    }),
  };
});

const observers: { cb: ResizeObserverCallback; disconnected: boolean }[] = [];
beforeAll(() => {
  globalThis.ResizeObserver = class {
    private rec: { cb: ResizeObserverCallback; disconnected: boolean };
    constructor(cb: ResizeObserverCallback) {
      this.rec = { cb, disconnected: false };
      observers.push(this.rec);
    }
    observe() {}
    unobserve() {}
    disconnect() {
      this.rec.disconnected = true;
    }
  } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  created.length = 0;
  observers.length = 0;
});

const spec = (id: string) => fixtures.fixtures.find((f) => f.id === id)!.spec as unknown as ChartSpec;

test("4 张图：挂载 4 次 init、卸载后 4 次 dispose，DOM 上不留实例，observer 全部断开", () => {
  const ids = ["bar", "line", "pie", "scatter"];
  const { unmount } = render(<>{ids.map((id) => <EChart key={id} spec={spec(id)} />)}</>);
  const els = screen.getAllByTestId("echart");
  expect(els).toHaveLength(4);
  expect(created).toHaveLength(4);
  els.forEach((el) => expect(core.getInstanceByDom(el)).toBeDefined());
  const disposes = created.map((c) => vi.spyOn(c, "dispose"));
  unmount();
  disposes.forEach((d) => expect(d).toHaveBeenCalledTimes(1));
  expect(created.every((c) => c.isDisposed())).toBe(true);
  els.forEach((el) => expect(core.getInstanceByDom(el)).toBeUndefined());
  expect(observers.every((o) => o.disconnected)).toBe(true);
});

test("resize 由 ResizeObserver 触发；option 变了整体重设（notMerge）", () => {
  const { rerender } = render(<EChart spec={spec("bar")} />);
  const c = created[0];
  const resize = vi.spyOn(c, "resize");
  observers[0].cb([], {} as ResizeObserver);
  expect(resize).toHaveBeenCalledTimes(1);
  const setOption = vi.spyOn(c, "setOption");
  rerender(<EChart spec={spec("line")} />);
  expect(setOption).toHaveBeenCalledWith(expect.objectContaining({ series: expect.any(Array) }), { notMerge: true });
  expect(created).toHaveLength(1); // 换 option 不重建实例
});

test("TurnView：5001 夹具 → 图和后端给的截断警告同时出现，前端不另拼提示", () => {
  const big = spec("bar-5001");
  expect(big.truncated).toBe(true);
  const warning = "图表「截断柱图」数据点超过 5000，只显示了前面的部分"; // 后端 accept_worker_charts 的文案
  const turn = {
    status: "ok",
    events: [],
    result: { ok: true, answer: "好了", error: null, error_kind: null, warnings: [warning], charts: [{ png: null, option: big }] },
  } as unknown as Turn;
  render(<TurnView turn={turn} />);
  expect(screen.getAllByTestId("echart")).toHaveLength(1);
  expect(screen.getAllByText(warning)).toHaveLength(1);
  expect(screen.queryByText(/数据点超过/, { selector: ":not(li)" })).toBeNull();
});

test("TurnView：png 项走 chartSrc（同源 /charts/<name>?token=），给不出地址就不画", () => {
  const turn = {
    status: "ok",
    events: [],
    result: { ok: true, answer: "", error: null, error_kind: null, warnings: [],
      charts: [{ png: null, option: spec("pie") }, { png: "/charts/a.png", option: null }] },
  } as unknown as Turn;
  const { unmount } = render(<TurnView turn={turn} chartSrc={(p) => `${p}?token=t`} />);
  expect(screen.getByAltText("图表").getAttribute("src")).toBe("/charts/a.png?token=t");
  unmount();
  render(<TurnView turn={turn} chartSrc={() => null} />);
  expect(screen.queryByAltText("图表")).toBeNull();
  expect(screen.getAllByTestId("echart")).toHaveLength(1);
});
