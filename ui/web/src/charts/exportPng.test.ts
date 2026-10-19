// F3 第六步：exportPng 的契约（phase5-frontend.md「F3 第六步」第 1 条）。init 换成记录参数的替身：主题名、尺寸、
// setOption 收到的 option = prepare(spec, ui, theme) + animation:false、getDataURL 的参数、dispose 一定被调用（含抛错时）。
import fixtures from "../generated/chart_fixtures.json";
import { exportPng, download, EXPORT_PIXEL_RATIO } from "./exportPng";
import { type ChartInput, DEFAULT_UI, prepare, type UiState } from "./prepare";
import { DEFAULT_SWITCHES, SWITCHES, SWITCH_VALUES, type Switches } from "./switches";
import { THEME_NAMES } from "./themes";

const { fake } = vi.hoisted(() => ({
  fake: {
    initArgs: [] as unknown[][],
    order: [] as string[],
    setOption: vi.fn(),
    getDataURL: vi.fn((): string => "data:image/png;base64,AAAA"),
    dispose: vi.fn(),
  },
}));
vi.mock("echarts/core", async (orig) => ({
  ...(await orig<typeof import("echarts/core")>()),
  init: vi.fn((...a: unknown[]) => {
    fake.order.push("init");
    fake.initArgs.push(a);
    return { setOption: fake.setOption, getDataURL: fake.getDataURL, dispose: fake.dispose };
  }),
}));
vi.mock("./register", async (orig) => {
  const real = await orig<typeof import("./register")>();
  return { ...real, registerCharts: vi.fn(() => { fake.order.push("register"); real.registerCharts(); }) };
});
beforeEach(() => {
  fake.order.length = 0;
  fake.initArgs.length = 0;
  fake.setOption.mockClear();
  fake.getDataURL.mockClear();
  fake.dispose.mockClear();
});

const spec = (id: string) => fixtures.fixtures.find((f) => f.id === id)!.spec as unknown as ChartInput;
const ON = Object.fromEntries(SWITCHES.map((s) => [s, SWITCH_VALUES[s][1]])) as Switches;

test("离屏 init（不挂 DOM 的 div、canvas、给定尺寸）→ prepare + animation:false → getDataURL(png, 2x) → dispose", () => {
  const ui: UiState = { kind: null, sw: { ...DEFAULT_SWITCHES, zoom: true }, view: { zoom: { start: 10, end: 60 }, hidden: [] } };
  const url = exportPng(spec("bar"), ui, "soft", { width: 640, height: 360 });
  expect(url).toBe("data:image/png;base64,AAAA");
  const [el, theme, opts] = fake.initArgs[0] as [HTMLElement, string, object];
  expect(el.isConnected).toBe(false);
  expect(theme).toBe("soft");
  expect(opts).toEqual({ renderer: "canvas", width: 640, height: 360 });
  expect(fake.setOption).toHaveBeenCalledWith({ ...prepare(spec("bar"), ui, "soft"), animation: false }, { notMerge: true });
  expect(fake.getDataURL).toHaveBeenCalledWith({ type: "png", pixelRatio: EXPORT_PIXEL_RATIO });
  expect(EXPORT_PIXEL_RATIO).toBe(2);
  expect(fake.dispose).toHaveBeenCalledTimes(1);
});

test("getDataURL 抛错：dispose 仍被调用，错误照常抛给调用方（UI 显示导出失败）", () => {
  fake.getDataURL.mockImplementationOnce(() => { throw new Error("boom"); });
  expect(() => exportPng(spec("bar"), DEFAULT_UI, "classic", { width: 100, height: 100 })).toThrow("boom");
  expect(fake.dispose).toHaveBeenCalledTimes(1);
});

test("init 之前已注册（主题模块级注册、不依赖屏幕上的 EChart 先挂载；没注册的主题名会被 init 静默回退成默认主题）", () => {
  exportPng(spec("bar"), DEFAULT_UI, "darkCanvas", { width: 100, height: 100 });
  expect(fake.order.slice(0, 2)).toEqual(["register", "init"]);
});

test("尺寸为 0 或非有限数（容器 display:none）：抛错，不建实例、不出图", () => {
  for (const size of [{ width: 0, height: 300 }, { width: 400, height: 0 }, { width: NaN, height: 300 }, { width: -1, height: 1 }]) {
    expect(() => exportPng(spec("bar"), DEFAULT_UI, "classic", size)).toThrow(/export size/);
  }
  expect(fake.initArgs).toHaveLength(0);
  expect(fake.getDataURL).not.toHaveBeenCalled();
});

test("animation 只写在导出路径：prepare 的产物里没有 animation（屏幕上的图不受影响）", () => {
  for (const id of ["bar", "pie", "line-wide"]) expect("animation" in prepare(spec(id), { kind: null, sw: ON }, "classic")).toBe(false);
});

test("4 套主题 × 全部夹具 × 开关全开 × 带 view：导出的 option 不含被禁键，tooltip.renderMode 是 richText", async () => {
  const banned = new Set((await import("../generated/banned_keys.json")).banned_keys);
  const walk = (v: unknown, path: string, bad: string[]) => {
    if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`, bad));
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) {
      if (banned.has(k) && !(k === "renderMode" && path === "tooltip" && x === "richText")) bad.push(`${path}.${k}`);
      walk(x, path ? `${path}.${k}` : k, bad);
    }
  };
  const bad: string[] = [];
  for (const theme of THEME_NAMES) for (const f of fixtures.fixtures) {
    exportPng(f.spec as unknown as ChartInput, { kind: null, sw: ON, view: { zoom: { start: 5, end: 95 }, hidden: [0, 1] } }, theme, { width: 400, height: 300 });
    const o = fake.setOption.mock.calls.at(-1)![0] as Record<string, { renderMode?: string }>;
    walk(o, "", bad);
    if (o.tooltip.renderMode !== "richText") bad.push(`${f.id} tooltip.renderMode`);
  }
  expect(bad).toEqual([]);
});

test("download：a.href = data URL、a.download = 文件名、click；a 不挂进 DOM", () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.isConnected).toBe(false);
    expect(this.getAttribute("href")).toBe("data:image/png;base64,AAAA");
    expect(this.download).toBe("各城市销量.png");
  });
  download("data:image/png;base64,AAAA", "各城市销量.png");
  expect(click).toHaveBeenCalledTimes(1);
  click.mockRestore();
});
