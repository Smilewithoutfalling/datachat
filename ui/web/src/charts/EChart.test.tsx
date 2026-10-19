// EChart 组件：挂载 / 卸载配对、resize 由 ResizeObserver 触发；TurnView 截断夹具：图和后端截断警告同时出现（单一来源）。
// jsdom 没有 canvas，测试里把 init 换成真 init + SVG renderer + 固定尺寸，其余（setOption、dispose、getInstanceByDom）都是真 ECharts。
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import * as core from "echarts/core";
import fixtures from "../generated/chart_fixtures.json";
import type { Turn } from "../turn";
import { TurnView } from "../views/TurnView";
import { EChart, type ChartSpec } from "./EChart";
import * as exp from "./exportPng";
import { DEFAULT_SWITCHES } from "./switches";
import { setChartTheme, THEMES } from "./themes";
import { resetPrefsForTest, setPrefs } from "./uiPrefs";

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

// 导出：保留真实现（走真 prepare + 离屏 init），只把下载换掉、把 exportPng 包一层看参数
vi.mock("./exportPng", async (orig) => {
  const real = await orig<typeof import("./exportPng")>();
  return { ...real, exportPng: vi.fn(real.exportPng), download: vi.fn() };
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
  // F3 第六步：静态图没有导出按钮，标注出来（S 10-19）；交互图有按钮
  expect(screen.getByTestId("chart-static").textContent).toBe("静态图（由 matplotlib 生成），可右键另存为");
  expect(screen.getAllByRole("button", { name: "导出 PNG" })).toHaveLength(1);
  unmount();
  render(<TurnView turn={turn} chartSrc={() => null} />);
  expect(screen.queryByAltText("图表")).toBeNull();
  expect(screen.getAllByTestId("echart")).toHaveLength(1);
});

// ---- F3 第五步：图型 / 开关 / 主题任一变化整体重算；实例不重建；双击空白还原缩放；偏好按图型共享
describe("F3 第五步：EChart 的开关与换图型", () => {
  afterEach(() => {
    localStorage.clear();
    resetPrefsForTest();
    act(() => setChartTheme("classic"));
  });
  const lastOption = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.at(-1)![0] as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

  test("切主题：先 setTheme 再整体 setOption(notMerge)；开着渐变时色值跟着主题变；实例不重建", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, gradient: true });
    render(<EChart spec={spec("bar")} />);
    const c = created[0];
    const setTheme = vi.spyOn(c, "setTheme");
    const setOption = vi.spyOn(c, "setOption");
    act(() => setChartTheme("darkCanvas"));
    expect(setTheme).toHaveBeenCalledWith("darkCanvas");
    expect(setTheme.mock.invocationCallOrder[0]).toBeLessThan(setOption.mock.invocationCallOrder[0]);
    expect(setOption.mock.calls.at(-1)![1]).toEqual({ notMerge: true });
    expect(lastOption(setOption).series[0].itemStyle.color.colorStops[0].color).toBe(THEMES.darkCanvas.theme.color[0]);
    expect(created).toHaveLength(1);
  });

  test("开关：勾上即重设 option，偏好写进 datachat.chartUi:<kind>，同图型的另一张图立即跟着变", () => {
    render(<><EChart spec={spec("bar")} /><EChart spec={spec("bar-untitled")} /></>);
    const spies = created.map((c) => vi.spyOn(c, "setOption"));
    const box = screen.getAllByRole("checkbox", { name: "数值标签" })[0];
    fireEvent.click(box);
    expect(JSON.parse(localStorage.getItem("datachat.chartUi:bar")!).label).toBe(true);
    for (const s of spies) expect(lastOption(s).series[0].label).toEqual({ show: true, position: "top" });
    expect(created).toHaveLength(2);
  });

  test("不兼容的开关 disabled，悬停有原因；单系列柱图的堆叠置灰", () => {
    render(<EChart spec={spec("bar")} />);
    const stack = screen.getByRole("checkbox", { name: "堆叠" });
    expect((stack as HTMLInputElement).disabled).toBe(true);
    expect(stack.closest("label")!.getAttribute("title")).toBe("只有一个系列");
    expect((screen.getByRole("checkbox", { name: "平滑" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("checkbox", { name: "圆角" }) as HTMLInputElement).disabled).toBe(false);
  });

  test("换图型：选饼图后 option 是饼图、spec.kind 不变；有空值的图饼图选项置灰；刷新（重挂载）回到后端图型", () => {
    const { unmount } = render(<EChart spec={spec("bar")} />);
    const setOption = vi.spyOn(created[0], "setOption");
    fireEvent.change(screen.getByRole("combobox", { name: "图型" }), { target: { value: "pie" } });
    expect(lastOption(setOption).series[0].type).toBe("pie");
    expect(screen.getByTestId("echart").getAttribute("data-kind")).toBe("bar");
    expect(screen.getByTestId("echart").getAttribute("data-shown-kind")).toBe("pie");
    unmount();
    render(<EChart spec={spec("bar")} />);
    expect(screen.getByTestId("echart").getAttribute("data-shown-kind")).toBe("bar");
    cleanup();
    render(<EChart spec={spec("bar-missing")} />);
    const pie = screen.getByRole("option", { name: "饼图" }) as HTMLOptionElement;
    expect(pie.disabled).toBe(true);
    expect(pie.title).toBe("有空值，不能换成饼图");
  });

  test("缩放开着：不按 Shift 的滚轮在容器 capture 阶段拦下（到不了 ECharts），按 Shift 的放行；缩放关着不拦", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, zoom: true });
    render(<EChart spec={spec("bar")} />);
    const inner = screen.getByTestId("echart").firstElementChild as HTMLElement; // zrender 的视口 div，监听器挂在这一层
    const seen: boolean[] = [];
    inner.addEventListener("wheel", (e) => seen.push((e as WheelEvent).shiftKey));
    inner.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true }));
    inner.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true, shiftKey: true }));
    expect(seen).toEqual([true]);
    fireEvent.click(screen.getByRole("checkbox", { name: "缩放" }));
    inner.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true }));
    expect(seen).toEqual([true, false]);
  });

  test("缩放开着：zr 层双击空白处还原，双击命中元素（图例、柱子）不还原；关掉后解绑", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, zoom: true });
    render(<EChart spec={spec("bar")} />);
    const c = created[0];
    const dispatch = vi.spyOn(c, "dispatchAction");
    const zr = c.getZr();
    act(() => zr.trigger("dblclick", { target: { id: 1 } }));
    expect(dispatch).not.toHaveBeenCalled();
    act(() => zr.trigger("dblclick", { target: undefined }));
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: "dataZoom", start: 0, end: 100 })); // echarts 往 payload 里塞内部标记
    expect(screen.getByText("Shift + 滚轮缩放，拖动平移，双击空白处还原")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "缩放" }));
    dispatch.mockClear();
    act(() => zr.trigger("dblclick", { target: undefined }));
    expect(dispatch).not.toHaveBeenCalled();
  });
});

// ---- F3 第六步：导出 PNG；交互态在事件发生时写进 view，导出和下一次重算都带上它 ------------------------------------
describe("F3 第六步：导出与交互态", () => {
  const exportSpy = vi.mocked(exp.exportPng);
  const downloadSpy = vi.mocked(exp.download);
  let size = { w: 800, h: 450 }; // jsdom 不做布局，clientWidth / clientHeight 恒为 0：这里给容器一个尺寸
  beforeEach(() => {
    exportSpy.mockClear();
    downloadSpy.mockClear();
    size = { w: 800, h: 450 };
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => size.w);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(() => size.h);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    resetPrefsForTest();
    act(() => setChartTheme("classic"));
  });
  const exportArgs = () => exportSpy.mock.calls.at(-1)!;
  const clickExport = () => fireEvent.click(screen.getByRole("button", { name: "导出 PNG" }));

  test("点导出：走 exportPng(spec, ui, 当前主题, 容器尺寸)，下载文件名是清洗过的标题；离屏实例用完即释放", () => {
    render(<EChart spec={spec("bar")} />);
    clickExport();
    const [s, ui, theme, size] = exportArgs();
    expect(s).toBe(spec("bar"));
    expect(ui).toEqual({ kind: null, sw: DEFAULT_SWITCHES, view: { zoom: null, hidden: [] } });
    expect(theme).toBe("classic");
    expect(size).toEqual({ width: 800, height: 450 }); // 容器的 clientWidth × clientHeight，原样
    expect(downloadSpy).toHaveBeenCalledWith(expect.stringMatching(/^data:image\//), "各城市销量.png");
    expect(created).toHaveLength(2); // 屏幕 1 + 离屏 1
    expect(created[1].isDisposed()).toBe(true);
    expect(created[0].isDisposed()).toBeFalsy();
  });

  test("文件名：注入标题清洗；无标题回退到当前显示的图型名", () => {
    render(<><EChart spec={spec("inject-bar")} /><EChart spec={spec("bar-untitled")} /></>);
    const [a, b] = screen.getAllByRole("button", { name: "导出 PNG" });
    fireEvent.click(a);
    expect(downloadSpy.mock.calls.at(-1)![1]).toBe("_img src=x onerror=_window.__pwned=1__.png");
    fireEvent.click(b);
    expect(downloadSpy.mock.calls.at(-1)![1]).toBe("柱状图.png");
  });

  test("导出为浅色（经典配色）：只在暗色画布下出现；勾上用 classic，不勾用 darkCanvas；不持久化", () => {
    render(<EChart spec={spec("bar")} />);
    expect(screen.queryByRole("checkbox", { name: "导出为浅色（经典配色）" })).toBeNull();
    act(() => setChartTheme("darkCanvas"));
    clickExport();
    expect(exportArgs()[2]).toBe("darkCanvas");
    fireEvent.click(screen.getByRole("checkbox", { name: "导出为浅色（经典配色）" }));
    clickExport();
    expect(exportArgs()[2]).toBe("classic");
    expect(Object.keys(localStorage).some((k) => localStorage.getItem(k)?.includes("light"))).toBe(false);
  });

  test("导出抛错：按钮旁显示导出失败，屏幕上的图不受影响；再导出成功后提示消失", () => {
    render(<EChart spec={spec("bar")} />);
    const setOption = vi.spyOn(created[0], "setOption");
    exportSpy.mockImplementationOnce(() => { throw new Error("boom"); });
    clickExport();
    expect(screen.getByRole("alert").textContent).toBe("导出失败");
    expect(setOption).not.toHaveBeenCalled();
    expect(created[0].isDisposed()).toBeFalsy();
    clickExport();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("容器尺寸为 0（display:none）：不回退成默认尺寸，导出失败、不下载", () => {
    render(<EChart spec={spec("bar")} />);
    size = { w: 0, h: 0 };
    clickExport();
    expect(exportArgs()[3]).toEqual({ width: 0, height: 0 });
    expect(screen.getByRole("alert").textContent).toBe("导出失败");
    expect(downloadSpy).not.toHaveBeenCalled();
  });

  test("屏幕是真相源：缩放后关掉缩放开关再打开，窗口回到全量，不跳回旧区间（重算后从实例回读 view）", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, zoom: true });
    render(<EChart spec={spec("bar")} />);
    const c = created[0];
    act(() => { c.dispatchAction({ type: "dataZoom", start: 20, end: 70 }); });
    const box = () => screen.getByRole("checkbox", { name: "缩放" });
    fireEvent.click(box()); // 关
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: null, hidden: [] });
    fireEvent.click(box()); // 再开
    const dz = (c.getOption() as { dataZoom: { start: number; end: number }[] }).dataZoom[0];
    expect([dz.start, dz.end]).toEqual([0, 100]);
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: null, hidden: [] });
  });

  test("屏幕是真相源：图例点掉一项后重算，屏幕上仍隐藏、回读的 view 与屏幕一致", () => {
    render(<EChart spec={spec("inject-bar")} />);
    const c = created[0];
    const name = (spec("inject-bar").option.series as { name: string }[])[1].name;
    act(() => { c.dispatchAction({ type: "legendToggleSelect", name }); });
    act(() => setChartTheme("soft")); // 重算：带上 hidden，再回读
    const sel = (c.getOption() as { legend: { selected: Record<string, boolean> }[] }).legend[0].selected;
    expect(sel[name]).toBe(false);
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: null, hidden: [1] });
  });

  test("缩放：datazoom 写进 view（本身不触发 setOption）；导出和下一次重算都带上；双击空白还原后清空", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, zoom: true });
    render(<EChart spec={spec("bar")} />);
    const c = created[0];
    const setOption = vi.spyOn(c, "setOption");
    act(() => { c.dispatchAction({ type: "dataZoom", start: 20, end: 70 }); });
    expect(setOption).not.toHaveBeenCalled();
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: { start: 20, end: 70 }, hidden: [] });
    act(() => setChartTheme("soft"));
    expect((setOption.mock.calls.at(-1)![0] as { dataZoom: { start: number; end: number }[] }).dataZoom[0]).toMatchObject({ start: 20, end: 70 });
    act(() => c.getZr().trigger("dblclick", { target: undefined }));
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: null, hidden: [] });
  });

  test("图例显隐：legendselectchanged 的名字换成 index 存（view 里没有字符串）；导出带上", () => {
    render(<EChart spec={spec("inject-bar")} />);
    const c = created[0];
    const name = (spec("inject-bar").option.series as { name: string }[])[1].name;
    act(() => { c.dispatchAction({ type: "legendToggleSelect", name }); });
    clickExport();
    const view = exportArgs()[1].view!;
    expect(view).toEqual({ zoom: null, hidden: [1] });
    expect(JSON.stringify(view)).not.toMatch(/:"/); // 值里没有字符串
  });

  test("换图型、换 spec：view 清空", () => {
    setPrefs("bar", { ...DEFAULT_SWITCHES, zoom: true });
    setPrefs("line", { ...DEFAULT_SWITCHES, zoom: true });
    const { rerender } = render(<EChart spec={spec("bar")} />);
    act(() => { created[0].dispatchAction({ type: "dataZoom", start: 20, end: 70 }); });
    fireEvent.change(screen.getByRole("combobox", { name: "图型" }), { target: { value: "line" } });
    clickExport();
    expect(exportArgs()[1]).toMatchObject({ kind: "line", view: { zoom: null, hidden: [] } });
    act(() => { created[0].dispatchAction({ type: "dataZoom", start: 20, end: 70 }); });
    rerender(<EChart spec={spec("bar-untitled")} />);
    clickExport();
    expect(exportArgs()[1].view).toEqual({ zoom: null, hidden: [] });
  });
});
