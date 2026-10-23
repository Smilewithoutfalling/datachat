// V2b B 组（phase5「阶段 5 收尾」B1–B4 的验收）：组头当前值、整组不可用的理由在组头、拨动开关、「完成」关卡、
// 按类目着色、标题输入（组件侧）、应用到所有同类图表 / 清除图型默认。纯函数部分在 layer1.test / title.test。
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import fixtures from "../generated/chart_fixtures.json";
import { EChart, type ChartSpec, resetMarksForTest } from "./EChart";
import * as exp from "./exportPng";
import { EDIT_PREFIX, KIND_EDIT_PREFIX, resetEditsForTest } from "./layer1";
import { setChartTheme, THEMES } from "./themes";
import { sanitizeTitle } from "./title";
import { resetPrefsForTest } from "./uiPrefs";

const { created } = vi.hoisted(() => ({ created: [] as import("echarts/core").ECharts[] }));
vi.mock("echarts/core", async (orig) => {
  const real = await orig<typeof import("echarts/core")>();
  real.use([(await import("echarts/renderers")).SVGRenderer]);
  return {
    ...real,
    init: vi.fn((el: HTMLElement, theme: unknown, opts: Record<string, unknown>) => {
      const c = real.init(el, theme as null, { ...opts, renderer: "svg", width: 400, height: 300 });
      created.push(c);
      return c;
    }),
  };
});
vi.mock("./exportPng", async (orig) => {
  const real = await orig<typeof import("./exportPng")>();
  return { ...real, exportPng: vi.fn(() => "data:image/png;base64,"), download: vi.fn() };
});

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  created.length = 0;
  resetMarksForTest();
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  resetPrefsForTest();
  resetEditsForTest();
  act(() => setChartTheme("classic"));
});

type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const spec = (id: string) => fixtures.fixtures.find((f) => f.id === id)!.spec as unknown as ChartSpec;
const opt = (i = -1) => created.at(i)!.getOption() as O;
const openCard = (i = 0) => {
  const btn = screen.getAllByRole("button", { name: "标记" })[i];
  if (btn.getAttribute("aria-expanded") !== "true") fireEvent.click(btn);
};
const head = (g: string) => screen.getByTestId("marks-card").querySelector(`.marks-ghead[data-group="${g}"]`) as HTMLButtonElement;
const val = (g: string) => screen.getByTestId(`marks-val-${g}`).textContent;
const expand = (g: string) => {
  if (head(g).getAttribute("aria-pressed") !== "true") fireEvent.click(head(g));
  return document.getElementById(head(g).getAttribute("aria-controls")!)!;
};
const C = THEMES.classic.theme.color;

describe("B1 组头与卡头", () => {
  test("组头当前值 5 组：默认值，改动后跟着变", () => {
    render(<EChart spec={spec("bar")} editKey="v:1" />);
    openCard();
    expect(["color", "label", "shape", "axis", "text"].map(val)).toEqual(["自动", "显示数值", "默认", "自动", "默认标题 · 中"]);
    fireEvent.click(within(expand("color")).getAllByRole("button", { name: /颜色 3$/ })[0]);
    fireEvent.click(within(expand("label")).getByRole("switch", { name: "数值标签" }));
    fireEvent.click(within(expand("shape")).getByRole("switch", { name: "圆角" }));
    const axis = expand("axis");
    fireEvent.change(within(axis).getByLabelText("y 轴最小值"), { target: { value: "1" } });
    fireEvent.change(within(axis).getByLabelText("y 轴最大值"), { target: { value: "9" } });
    const text = expand("text");
    fireEvent.change(within(text).getByLabelText("标题"), { target: { value: "我的标题" } });
    fireEvent.click(within(text).getByRole("button", { name: "大 16" }));
    expect(["color", "label", "shape", "axis", "text"].map(val)).toEqual(["已改 1 项", "不显示", "已改", "1～9", "我的标题 · 大"]);
  });
  test("组头是竖排的：每个组头后面紧跟自己的 region；整组不可用的组头仍在（不跳行）", () => {
    render(<EChart spec={spec("pie")} />);
    openCard();
    expand("text");
    const order = [...screen.getByRole("group", { name: "样式分组" }).querySelectorAll(".marks-ghead, [role=region]")]
      .map((e) => (e.classList.contains("marks-ghead") ? (e as HTMLElement).dataset.group : `region:${e.getAttribute("data-testid")}`));
    expect(order).toEqual(["color", "region:marks-color", "label", "shape", "axis", "text", "region:marks-text"]);
    expect(head("shape").getAttribute("aria-disabled")).toBe("true");
  });
  test("卡头「N 个图形元素」：单系列柱图 1、多系列按系列数、饼图按类目数", () => {
    const n = (id: string) => {
      render(<EChart spec={spec(id)} />);
      openCard();
      const t = screen.getByTestId("marks-count").textContent;
      cleanup();
      resetMarksForTest();
      return t;
    };
    expect(n("bar")).toBe("1 个图形元素");
    expect(n("inject-bar")).toBe(`${(spec("inject-bar").option.series as unknown[]).length} 个图形元素`);
    expect(n("pie")).toBe(`${((spec("pie").option.series as O[])[0].data as unknown[]).length} 个图形元素`);
  });
  test("开关是拨动开关：role=switch，可访问名不变，checked 跟状态走", () => {
    render(<EChart spec={spec("bar")} />);
    openCard();
    const sw = within(expand("label")).getByRole("switch", { name: "数值标签" }) as HTMLInputElement;
    expect([sw.type, sw.checked, sw.className]).toEqual(["checkbox", true, "switch"]);
    fireEvent.click(sw);
    expect(sw.checked).toBe(false);
  });
  test("「完成」关卡，和 Esc 同一个出口；底部提示在", () => {
    render(<EChart spec={spec("bar")} />);
    openCard();
    expect(screen.getByText("改动只作用于这张图，不改动原始数据。")).toBeTruthy();
    expect(screen.getByText("已单独改过的图保持不变")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(screen.queryByTestId("marks-card")).toBeNull();
    expect(screen.getByRole("button", { name: "标记" }).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("B2 按类目着色", () => {
  test("只在单系列柱图出现（多系列柱图、折线、饼图都没有）", () => {
    for (const [id, has] of [["bar", true], ["inject-bar", false], ["line", false], ["pie", false]] as const) {
      render(<EChart spec={spec(id)} />);
      openCard();
      expect([id, screen.queryByRole("combobox", { name: "按列着色" }) !== null]).toEqual([id, has]);
      cleanup();
      resetMarksForTest();
    }
  });
  test("选 x 轴名：写 series[0].colorBy = 'data'，颜色行换成类目；改第 3 类的色只包这一个数值点，值不变", () => {
    render(<EChart spec={spec("bar")} editKey="v:2" />);
    openCard();
    const xName = (spec("bar").option.xAxis as { name: string }).name;
    const cats = (spec("bar").option.xAxis as { data: string[] }).data;
    const vals = (spec("bar").option.series as { data: number[] }[])[0].data;
    const sel = screen.getByRole("combobox", { name: "按列着色" }) as HTMLSelectElement;
    expect([...sel.options].map((o) => o.textContent)).toEqual(["不按列（每个系列一色）", xName]);
    fireEvent.change(sel, { target: { value: "data" } });
    expect(opt().series[0].colorBy).toBe("data");
    expect(val("color")).toBe(`按${xName}`);
    expect(screen.getByTestId("marks-count").textContent).toBe(`${cats.length} 个图形元素`);
    const rows = within(expand("color")).getAllByRole("button", { name: /自动$/ }).map((b) => b.getAttribute("aria-label"));
    expect(rows).toEqual(cats.map((c) => `${c} 自动`));
    fireEvent.click(within(expand("color")).getByRole("button", { name: `${cats[2]} 颜色 5` }));
    const data = opt().series[0].data as unknown[];
    expect(data[2]).toEqual({ value: vals[2], itemStyle: { color: C[4] } });
    expect(data.filter((_, i) => i !== 2)).toEqual(vals.filter((_, i) => i !== 2));
    expect(JSON.parse(localStorage.getItem(EDIT_PREFIX + "v:2")!)).toEqual({ colorBy: "data", colors: { 2: 4 } });
    fireEvent.change(sel, { target: { value: "series" } }); // 换回去：按类目选的颜色清掉（index 含义变了）
    expect(opt().series[0].colorBy).not.toBe("data");
    expect(val("color")).toBe("自动");
  });
  test("类目多于色数：照饼图提示「N 类，多于 10 色，颜色会重复」", () => {
    const many = JSON.parse(JSON.stringify(spec("bar"))) as ChartSpec;
    const o = many.option as { xAxis: { data: string[] }; series: { data: number[] }[] };
    o.xAxis.data = Array.from({ length: 12 }, (_, i) => `c${i}`);
    o.series[0].data = o.xAxis.data.map((_, i) => i + 1);
    render(<EChart spec={many} />);
    openCard();
    expect(screen.queryByTestId("marks-repeat")).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "按列着色" }), { target: { value: "data" } });
    expect(screen.getByTestId("marks-repeat").textContent).toBe("12 类，多于 10 色，颜色会重复");
  });
});

describe("B3 标题（组件）", () => {
  const INJ = "{a|x}\n<img src=x onerror=window.__pwned=1>\u202e" + "长".repeat(120);
  test("输入写 title.text（清洗过）；组头当前值是文本节点，页面上不多出元素；留空回到后端标题", () => {
    render(<EChart spec={spec("bar")} editKey="v:3" />);
    openCard();
    const input = within(expand("text")).getByLabelText("标题") as HTMLInputElement;
    expect(input.placeholder).toBe((spec("bar").option.title as { text: string }).text);
    fireEvent.change(input, { target: { value: INJ } });
    const t = opt().title[0].text as string;
    expect(Array.from(t).length).toBe(100);
    // 单行 input 的 value 本来就去掉换行（浏览器和 jsdom 一样），剩下的按 sanitizeTitle 清
    expect(t).toBe(sanitizeTitle(INJ.replace(/\n/g, "")));
    expect(t.startsWith("\uff5ba|x\uff5d<img src=x onerror=window.__pwned=1> ")).toBe(true);
    expect(document.querySelectorAll("img").length).toBe(0);
    expect(val("text")).toBe(`${t} · 中`);
    expect(JSON.parse(localStorage.getItem(EDIT_PREFIX + "v:3")!).title).toBe(t);
    fireEvent.change(input, { target: { value: "  " } });
    expect(opt().title[0].text).toBe((spec("bar").option.title as { text: string }).text);
  });
  test("导出文件名取用户标题，不含 Bidi", () => {
    render(<EChart spec={spec("bar")} editKey="v:4" />);
    openCard();
    fireEvent.change(within(expand("text")).getByLabelText("标题"), { target: { value: "报表\u202egnp.exe" } });
    fireEvent.click(screen.getByRole("button", { name: "导出 PNG" }));
    expect(vi.mocked(exp.download).mock.calls.at(-1)![1]).toBe("报表 gnp.exe.png");
  });
});

describe("B4 应用到所有同类图表", () => {
  const font = (i: number) => { const t = opt(i).textStyle; return (Array.isArray(t) ? t[0] : t)?.fontSize; };
  test("迁移 colors / colorBy / font / other，不迁移 yMin / yMax / title；没改过的图跟着变，自己改过的字段保持", () => {
    localStorage.setItem(EDIT_PREFIX + "b:0", JSON.stringify({ font: "s" })); // 第三张图自己改过字号
    render(<><EChart spec={spec("bar")} editKey="a:0" /><EChart spec={spec("bar-untitled")} editKey="u:0" />
      <EChart spec={spec("bar-missing")} editKey="b:0" /></>);
    openCard(0);
    fireEvent.click(within(expand("color")).getAllByRole("button", { name: /颜色 3$/ })[0]);
    fireEvent.click(within(expand("text")).getByRole("button", { name: "大 16" }));
    fireEvent.change(within(expand("text")).getByLabelText("标题"), { target: { value: "只属于这张" } });
    fireEvent.change(within(expand("axis")).getByLabelText("y 轴最大值"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "应用到所有柱状图" }));
    expect(JSON.parse(localStorage.getItem(KIND_EDIT_PREFIX + "bar")!)).toEqual({ colors: { 0: 2 }, colorBy: "series", font: "l", other: false });
    // 第二张：没改过 → 颜色、字号跟着图型默认；标题、y 上限不跟
    expect([opt(1).series[0].itemStyle?.color, font(1), opt(1).title?.[0]?.text ?? null, opt(1).yAxis[0].max === 40]).toEqual([C[2], 16, null, false]);
    // 第三张：自己改过字号 → 字号保持 12，颜色跟着走
    expect([opt(2).series[0].itemStyle?.color, font(2)]).toEqual([C[2], 12]);
  });
  test("重置只清这张图自己的改动（回到图型默认）；「清除柱状图默认」后没单独改过的图回到原样", () => {
    localStorage.setItem(KIND_EDIT_PREFIX + "bar", JSON.stringify({ font: "l" }));
    localStorage.setItem(EDIT_PREFIX + "r:0", JSON.stringify({ font: "s" }));
    render(<><EChart spec={spec("bar")} editKey="r:0" /><EChart spec={spec("bar-untitled")} editKey="r:1" /></>);
    expect([font(0), font(1)]).toEqual([12, 16]);
    openCard(0);
    fireEvent.click(screen.getByRole("button", { name: "重置" }));
    expect([font(0), font(1)]).toEqual([16, 16]);
    expect(localStorage.getItem(EDIT_PREFIX + "r:0")).toBeNull();
    expect(localStorage.getItem(KIND_EDIT_PREFIX + "bar")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "清除柱状图默认" }));
    expect([font(0), font(1)]).toEqual([12, 12]); // 不写 textStyle 时 ECharts 的默认 12
    expect(localStorage.getItem(KIND_EDIT_PREFIX + "bar")).toBeNull();
    expect(screen.queryByRole("button", { name: "清除柱状图默认" })).toBeNull();
  });
  test("图型默认按图型分开：柱图的默认不影响折线图", () => {
    localStorage.setItem(KIND_EDIT_PREFIX + "bar", JSON.stringify({ font: "l" }));
    render(<><EChart spec={spec("bar")} /><EChart spec={spec("line")} /></>);
    expect([font(0), font(1)]).toEqual([16, 12]);
  });
});
