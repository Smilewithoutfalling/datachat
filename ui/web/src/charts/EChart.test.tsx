// EChart 组件：挂载 / 卸载配对、resize 由 ResizeObserver 触发；TurnView 截断夹具：图和后端截断警告同时出现（单一来源）。
// jsdom 没有 canvas，测试里把 init 换成真 init + SVG renderer + 固定尺寸，其余（setOption、dispose、getInstanceByDom）都是真 ECharts。
import { EDIT_PREFIX, EMPTY_EDIT, resetEditsForTest } from "./layer1";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import * as core from "echarts/core";
import fixtures from "../generated/chart_fixtures.json";
import type { Turn } from "../turn";
import { TurnView } from "../views/TurnView";
import { EChart, type ChartSpec, placeCard, resetMarksForTest } from "./EChart";
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
  resetMarksForTest();
});

// F4 迭代 V1：开关在标记卡的组里。打开第 i 张图的卡（已开不重复点），再展开组（已展开不重复点），返回该组区域。
function group(name: string, i = 0): HTMLElement {
  const btn = screen.getAllByRole("button", { name: "样式" })[i];
  if (btn.getAttribute("aria-expanded") !== "true") fireEvent.click(btn);
  const t = screen.getByRole("button", { name: new RegExp("^" + name) });
  if (t.getAttribute("aria-pressed") !== "true") fireEvent.click(t);
  return document.getElementById(t.getAttribute("aria-controls")!)!;
}

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
    const box = within(group("标签")).getByRole("checkbox", { name: "数值标签" });
    fireEvent.click(box);
    expect(JSON.parse(localStorage.getItem("datachat.chartUi:bar")!).label).toBe(true);
    for (const s of spies) expect(lastOption(s).series[0].label).toEqual({ show: true, position: "top" });
    expect(created).toHaveLength(2);
  });

  // F4 迭代 V1 第 2 条（判定表改动）：不兼容的开关从"disabled + title"改为不渲染；工具栏只剩图型 / 排序 / 样式 / 导出
  test("不兼容的开关不渲染：单系列柱图的形状组只有圆角；工具栏只有四个控件", () => {
    render(<EChart spec={spec("bar")} />);
    const ctl = screen.getByTestId("chart-controls");
    expect(within(ctl).queryAllByRole("checkbox")).toEqual([]);
    expect(within(ctl).getAllByRole("combobox").map((c) => c.getAttribute("aria-label"))).toEqual(["图型", "排序"]);
    const shape = group("形状");
    expect(within(shape).queryByRole("checkbox", { name: "堆叠" })).toBeNull();
    expect(within(shape).queryByRole("checkbox", { name: "平滑" })).toBeNull();
    expect((within(shape).getByRole("checkbox", { name: "圆角" }) as HTMLInputElement).disabled).toBe(false);
    expect(within(group("标签")).queryByRole("group", { name: "图例位置" })).toBeNull();
  });
  test("散点图：排序不渲染（不适用即隐藏，排序也一样）", () => {
    render(<EChart spec={spec("scatter")} />);
    expect(within(screen.getByTestId("chart-controls")).queryByRole("combobox", { name: "排序" })).toBeNull();
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
    fireEvent.click(within(group("轴")).getByRole("checkbox", { name: "缩放" }));
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
    fireEvent.click(within(group("轴")).getByRole("checkbox", { name: "缩放" }));
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
    // F4：UiState 多了 edit（层 1 改动），#49 多了 compact（矮画布），导出要带上它们才能和屏幕一致；这里是未改、450 高
    expect(ui).toEqual({ kind: null, sw: DEFAULT_SWITCHES, edit: EMPTY_EDIT, compact: false, view: { zoom: null, hidden: [] } });
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
    const box = () => within(group("轴")).getByRole("checkbox", { name: "缩放" });
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

describe("F4 层 1 面板（标记卡）", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    resetEditsForTest();
    act(() => setChartTheme("classic"));
  });
  const opt = () => created.at(-1)!.getOption() as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  const fontSize = () => { const t = opt().textStyle; return (Array.isArray(t) ? t[0] : t)?.fontSize; };
  const open = () => fireEvent.click(screen.getByRole("button", { name: "样式" }));
  const tile = (n: string) => screen.getByRole("button", { name: new RegExp("^" + n) });

  test("字号：点'大 16' → 渲染出 textStyle.fontSize 16，存进 localStorage；重置后删键", () => {
    render(<EChart spec={spec("bar")} editKey="m1:0" />);
    open();
    fireEvent.click(tile("文字"));
    fireEvent.click(screen.getByRole("button", { name: "大 16" }));
    expect(fontSize()).toBe(16);
    expect(localStorage.getItem(EDIT_PREFIX + "m1:0")).toContain('"font":"l"');
    fireEvent.click(screen.getByRole("button", { name: "重置" }));
    expect(localStorage.getItem(EDIT_PREFIX + "m1:0")).toBeNull();
  });
  test("轴范围：合法写进 yAxis；min ≥ max 报错且不生效", () => {
    render(<EChart spec={spec("bar")} editKey="m1:1" />);
    open();
    fireEvent.click(tile("轴"));
    fireEvent.change(screen.getByLabelText("y 轴最大值"), { target: { value: "40" } });
    expect(opt().yAxis[0].max).toBe(40);
    fireEvent.change(screen.getByLabelText("y 轴最小值"), { target: { value: "50" } });
    expect(screen.getByRole("alert").textContent).toBe("最小值要小于最大值");
    expect(opt().yAxis[0].min).not.toBe(50);
  });
  test("饼图：形状、轴 tile aria-disabled，理由行是『形状：饼图没有可调的形状 · 轴：饼图没有 y 轴』；展开颜色组后有合并 checkbox", () => {
    render(<EChart spec={spec("pie")} editKey="m1:2" />);
    open();
    const axis = tile("轴") as HTMLButtonElement;
    expect([axis.disabled, axis.getAttribute("aria-disabled")]).toEqual([false, "true"]);
    expect(tile("形状").getAttribute("aria-disabled")).toBe("true");
    const why = document.getElementById(axis.getAttribute("aria-describedby")!)!;
    expect(why.textContent).toBe("形状：饼图没有可调的形状 · 轴：饼图没有 y 轴");
    fireEvent.click(axis);
    expect(axis.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(tile("颜色"));
    expect(screen.getByRole("checkbox", { name: "合并为'其他'" })).toBeTruthy();
  });
  test("颜色：点色块写系列色；换主题跟着主题的同一 index", () => {
    render(<EChart spec={spec("bar")} editKey="m1:3" />);
    open();
    fireEvent.click(tile("颜色"));
    fireEvent.click(screen.getAllByRole("button", { name: /颜色 4$/ })[0]);
    expect(opt().series[0].itemStyle.color).toBe(THEMES.classic.theme.color[3]);
    act(() => setChartTheme("tableau"));
    expect(opt().series[0].itemStyle.color).toBe(THEMES.tableau.theme.color[3]);
  });
  test("TurnView 按 <message_id>:<图序号> 传存储键：读回之前存的改动", () => {
    localStorage.setItem(EDIT_PREFIX + "msg-9:0", JSON.stringify({ font: "s" }));
    const turn = { status: "ok", events: [],
      result: { ok: true, answer: "", error: null, error_kind: null, warnings: [], charts: [{ png: null, option: spec("bar") }] } } as unknown as Turn;
    render(<TurnView turn={turn} messageId="msg-9" />);
    expect(fontSize()).toBe(12);
  });
});

test("#49：ResizeObserver 量到容器矮于 300 → 紧凑几何（grid.top 36）；回到 360 → 恢复 60", () => {
  let h = 360;
  const spy = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(() => h);
  render(<EChart spec={spec("bar")} />);
  const top = () => ((created.at(-1)!.getOption() as { grid: { top: number }[] }).grid[0].top);
  const fire = () => act(() => observers.forEach((o) => o.cb([], {} as ResizeObserver)));
  fire();
  expect(top()).toBe(60);
  h = 220;
  fire();
  expect(top()).toBe(36);
  h = 360;
  fire();
  expect(top()).toBe(60);
  spy.mockRestore();
  cleanup();
});

// ---- F4 迭代 V1：标记卡浮层（phase5「F4 迭代 V1」第 3–8 条）--------------------------------------------------------
describe("F4 迭代 V1：标记卡", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    resetPrefsForTest();
    resetEditsForTest();
    act(() => setChartTheme("classic"));
  });
  const tiles = () => within(screen.getByRole("group", { name: "样式分组" })).getAllByRole("button");
  const pieN = (n: number): ChartSpec => {
    const s = JSON.parse(JSON.stringify(spec("pie-50"))) as ChartSpec;
    const ser = (s.option.series as { data: unknown[] }[])[0];
    ser.data = ser.data.slice(0, n);
    return s;
  };

  test("组多开：先后点颜色、轴，两个 region 都在、两个 tile 都 pressed；再点颜色只收起颜色组；没有 role=tab", () => {
    render(<EChart spec={spec("bar")} />);
    group("颜色");
    group("轴");
    const pressed = () => tiles().filter((t) => t.getAttribute("aria-pressed") === "true").map((t) => t.textContent!.slice(1));
    expect(pressed()).toEqual(["颜色", "轴"]);
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-labelledby")))
      .toEqual([tile("颜色").id, tile("轴").id]);
    fireEvent.click(tile("颜色"));
    expect(pressed()).toEqual(["轴"]);
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(screen.queryAllByRole("tab")).toEqual([]);
  });
  const tile = (n: string) => screen.getByRole("button", { name: new RegExp("^" + n) });

  test("工具栏控件集合：只有图型 / 排序（按 COMPAT）/ 样式 / 导出；排序只在单系列非时间柱图和饼图出现", () => {
    const want: Record<string, boolean> = {
      bar: true, "bar-series-20": false, line: false, "line-wide": false, "line-time": false,
      area: false, pie: true, scatter: false, "scatter-multi": false,
    };
    for (const [id, sort] of Object.entries(want)) {
      render(<EChart spec={spec(id)} />);
      const ctl = screen.getByTestId("chart-controls");
      expect([id, within(ctl).getAllByRole("combobox").map((c) => c.getAttribute("aria-label"))]).toEqual([id, sort ? ["图型", "排序"] : ["图型"]]);
      expect([id, within(ctl).getAllByRole("button").map((b) => b.textContent)]).toEqual([id, ["样式", "导出 PNG"]]);
      expect(within(ctl).queryAllByRole("checkbox")).toEqual([]);
      cleanup();
    }
  });

  test("隐藏不改变生效规则：单系列柱图上不渲染的堆叠 / 平滑即使偏好里是开的，option 也与关着相同", () => {
    render(<EChart spec={spec("bar")} />);
    const get = () => JSON.stringify(created.at(-1)!.getOption());
    const off = get();
    act(() => setPrefs("bar", { ...DEFAULT_SWITCHES, stack: true, smooth: true, legend: "top" }));
    expect(get()).toBe(off);
  });

  test("色块：aria-pressed 跟着选择走，'自动'默认按下", () => {
    render(<EChart spec={spec("bar")} editKey="m9:1" />);
    const c = group("颜色");
    const auto = within(c).getAllByRole("button", { name: /自动$/ })[0];
    expect(auto.getAttribute("aria-pressed")).toBe("true");
    const k3 = within(c).getAllByRole("button", { name: /颜色 3$/ })[0];
    fireEvent.click(k3);
    expect([auto.getAttribute("aria-pressed"), k3.getAttribute("aria-pressed")]).toEqual(["false", "true"]);
  });

  test("整页只开一张卡：打开第二张图的卡，第一张自动关", () => {
    render(<><EChart spec={spec("bar")} /><EChart spec={spec("bar-untitled")} /></>);
    const [a, b] = screen.getAllByRole("button", { name: "样式" });
    fireEvent.click(a);
    expect(screen.getAllByTestId("marks-card")).toHaveLength(1);
    fireEvent.click(b);
    expect(screen.getAllByTestId("marks-card")).toHaveLength(1);
    expect([a.getAttribute("aria-expanded"), b.getAttribute("aria-expanded")]).toEqual(["false", "true"]);
  });

  test("关闭：Esc、点卡外、再点样式按钮；点卡内不关", () => {
    render(<EChart spec={spec("bar")} />);
    const btn = screen.getByRole("button", { name: "样式" });
    fireEvent.click(btn);
    fireEvent.mouseDown(screen.getByTestId("marks-card"));
    expect(screen.queryByTestId("marks-card")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("marks-card")).toBeNull();
    fireEvent.click(btn);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId("marks-card")).toBeNull();
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(screen.queryByTestId("marks-card")).toBeNull();
  });

  test("浮层方向：上方可用 ≥ 160 向上；不足向下；maxHeight 不超过 420 和可用高度", () => {
    const r = (top: number, bottom: number) => ({ top, bottom } as DOMRect);
    expect(placeCard(r(600, 628), { top: 0, bottom: 900 })).toEqual({ dir: "up", maxHeight: 420 });
    expect(placeCard(r(200, 228), { top: 0, bottom: 900 })).toEqual({ dir: "up", maxHeight: 192 });
    expect(placeCard(r(167, 195), { top: 0, bottom: 900 })).toEqual({ dir: "down", maxHeight: 420 });
    expect(placeCard(r(100, 128), { top: 0, bottom: 400 })).toEqual({ dir: "down", maxHeight: 264 });
  });

  test("饼图类目多于调色板色数：10 类不提示，11 类提示（颜色 tile 有提示点）；合并'其他'后提示消失", () => {
    const n = THEMES.classic.theme.color.length;
    expect(n).toBe(10);
    render(<EChart spec={pieN(10)} />);
    expect(within(group("颜色")).queryByTestId("marks-repeat")).toBeNull();
    cleanup();
    resetMarksForTest();
    render(<EChart spec={pieN(11)} editKey="m9:0" />);
    const colors = group("颜色");
    expect(within(colors).getByTestId("marks-repeat").textContent).toBe(`11 类，多于 ${n} 色，颜色会重复`);
    expect(screen.getByLabelText("颜色会重复")).toBeTruthy();
    fireEvent.click(within(colors).getByRole("checkbox", { name: "合并为'其他'" }));
    expect(screen.queryByTestId("marks-repeat")).toBeNull();
  });

  test("散点图：标签组整组不可用，.marks-why 一行写理由", () => {
    render(<EChart spec={spec("scatter")} />);
    fireEvent.click(screen.getByRole("button", { name: "样式" }));
    const label = tiles().find((t) => t.textContent!.includes("标签"))!;
    expect(label.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByTestId("marks-why").textContent).toContain("标签：散点图不显示数值标签，单系列也没有图例");
  });
});
