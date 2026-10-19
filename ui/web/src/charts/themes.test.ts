// F3 第四步：主题对象的结构、安全和对比度断言（纯计算），以及主题真的生效（SSR）、切换、未知名字回退、历史 color 被删。
import { init, registerTheme, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import schema from "../generated/chart_schema.json";
import { BANNED_KEYS, prepare } from "./prepare";
import { productExtensions } from "./register";
import { DEFAULT_THEME, getChartTheme, reloadChartThemeForTest, resolveTheme, setChartTheme, STORAGE_KEY, THEME_NAMES, THEMES, type Theme } from "./themes";

type Spec = { kind: string; option: Record<string, unknown> };
const FIX = fixtures.fixtures as { id: string; spec: Spec }[];
installEcharts([...productExtensions(), SVGRenderer]);
for (const [n, { theme }] of Object.entries(THEMES)) registerTheme(n, theme);

// ---- 颜色计算（WCAG 2.x 相对亮度；CIEDE2000，kL=kC=kH=1，sRGB D65）
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (h: string) => {
  const [r, g, b] = hex(h).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => p - q);
  return (y + 0.05) / (x + 0.05);
};
function lab(h: string) {
  const [r, g, b] = hex(h).map(lin);
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const X = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047, Y = r * 0.2126 + g * 0.7152 + b * 0.0722, Z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
  return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
}
const rad = (d: number) => (d * Math.PI) / 180;
export function de2000(p: string, q: string) {
  const [L1, a1, b1] = lab(p), [L2, a2, b2] = lab(q);
  const Cb = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
  const a1p = (1 + G) * a1, a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2);
  const h1 = ((Math.atan2(b1, a1p) * 180) / Math.PI + 360) % 360, h2 = ((Math.atan2(b2, a2p) * 180) / Math.PI + 360) % 360;
  let dh = h2 - h1;
  if (C1p * C2p === 0) dh = 0;
  else if (dh > 180) dh -= 360;
  else if (dh < -180) dh += 360;
  const dL = L2 - L1, dC = C2p - C1p, dH = 2 * Math.sqrt(C1p * C2p) * Math.sin(rad(dh / 2));
  const Lb = (L1 + L2) / 2, Cbp = (C1p + C2p) / 2;
  const hb = C1p * C2p === 0 ? h1 + h2 : Math.abs(h1 - h2) <= 180 ? (h1 + h2) / 2 : h1 + h2 < 360 ? (h1 + h2 + 360) / 2 : (h1 + h2 - 360) / 2;
  const T = 1 - 0.17 * Math.cos(rad(hb - 30)) + 0.24 * Math.cos(rad(2 * hb)) + 0.32 * Math.cos(rad(3 * hb + 6)) - 0.2 * Math.cos(rad(4 * hb - 63));
  const dth = 30 * Math.exp(-(((hb - 275) / 25) ** 2)), RC = 2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7));
  const SL = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2), SC = 1 + 0.045 * Cbp, SH = 1 + 0.015 * Cbp * T;
  const RT = -Math.sin(rad(2 * dth)) * RC;
  return Math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * (dC / SC) * (dH / SH));
}

// 阈值：外部标准，不是本仓库实测的最小值——别当快照去改（S 10-19）。
// ΔE00 ≈ 2.3 是 JND，5–10 "能看出不同"，20 "不同色系"。
const TEXT_MIN = 4.5; //   WCAG 1.4.3 正文文本
const SERIES_MIN = 3.0; // WCAG 1.4.11 非文本图形
const ADJ_DE_MIN = 20;
// 余量：本步新引入的颜色 ≥ 阈值 × 1.1，吸收实现差异（kL、换库、色域处理）。PALETTE 里沿用的旧色不在此列。
// #CD7D28 对 #C0392B 25.0：暖色带里"白底 ≥3:1"与"离红 ≥24"几乎互斥，25 左右是这一带的上限。
const NEW_DE_MIN = ADJ_DE_MIN * 1.1;
// 豁免按 (主题, 色值) 二元组（PR #48 评审第六条）：只有 classic 沿用的 5 个旧色互相之间按 20 判。别的主题复用同一个色值时
// 仍按新色 ≥ 22 判——那是它新引入的配对，不该搭 classic 的便车。
const LEGACY = new Set(["#1F6FB2", "#159A8C", "#C0392B", "#7E57C2", "#3A7D44"].map((h) => `classic:${h}`));
const isLegacy = (theme: string, hex: string) => LEGACY.has(`${theme}:${hex.toUpperCase()}`);

// 逐键：漏一个就红（不设 backgroundColor 画布透明，暗色画布会透出白页面；深底上不改轴线 / 文字色会黑叠黑）
const AXIS = ["axisLine.lineStyle.color", "axisTick.lineStyle.color", "axisLabel.color", "splitLine.lineStyle.color", "nameTextStyle.color"];
const REQUIRED_PATHS = [
  "backgroundColor", "textStyle.color", "title.textStyle.color", "legend.textStyle.color", "legend.pageTextStyle.color", "legend.inactiveColor",
  "tooltip.backgroundColor", "tooltip.borderColor", "tooltip.textStyle.color", "pie.itemStyle.borderColor",
  ...["categoryAxis", "valueAxis", "timeAxis"].flatMap((a) => AXIS.map((k) => `${a}.${k}`)),
];
const get = (o: unknown, path: string) => path.split(".").reduce<unknown>((n, k) => (n && typeof n === "object" ? (n as Record<string, unknown>)[k] : undefined), o);
const TEXT_PATHS = ["textStyle.color", "title.textStyle.color", "legend.textStyle.color", "legend.pageTextStyle.color",
  ...["categoryAxis", "valueAxis", "timeAxis"].flatMap((a) => [`${a}.axisLabel.color`, `${a}.nameTextStyle.color`])];

describe.each(THEME_NAMES.map((n) => [n, THEMES[n].theme] as const))("主题 %s", (name, theme: Theme) => {
  test("纯 JSON（无函数），递归不含 BANNED_KEYS / rich / formatter", () => {
    expect(JSON.parse(JSON.stringify(theme))).toEqual(theme);
    const bad: string[] = [];
    const visit = (n: unknown, p: string) => {
      if (Array.isArray(n)) n.forEach((x, i) => visit(x, `${p}.${i}`));
      else if (n && typeof n === "object")
        for (const [k, v] of Object.entries(n)) {
          if (BANNED_KEYS.has(k) || k === "rich" || k === "formatter") bad.push(`${p}.${k}`);
          visit(v, `${p}.${k}`);
        }
    };
    visit(theme, name);
    expect(bad).toEqual([]);
  });
  test("必需键齐全，颜色都是 #RRGGBB", () => {
    for (const p of REQUIRED_PATHS) expect([p, /^#[0-9A-F]{6}$/i.test(String(get(theme, p)))]).toEqual([p, true]);
    for (const c of theme.color) expect(c).toMatch(/^#[0-9A-F]{6}$/i);
  });
  test(`文字对背景 ≥ ${TEXT_MIN}（tooltip 文字对 tooltip 背景）`, () => {
    for (const p of TEXT_PATHS) expect([p, contrast(get(theme, p) as string, theme.backgroundColor)]).toEqual([p, expect.any(Number)]);
    const low = TEXT_PATHS.filter((p) => contrast(get(theme, p) as string, theme.backgroundColor) < TEXT_MIN);
    expect(low).toEqual([]);
    expect(contrast(theme.tooltip.textStyle.color, theme.tooltip.backgroundColor)).toBeGreaterThanOrEqual(TEXT_MIN);
  });
  test(`系列色对背景 ≥ ${SERIES_MIN}；相邻（含首尾）ΔE00 ≥ ${ADJ_DE_MIN}，新色 ≥ ${NEW_DE_MIN.toFixed(0)}`, () => {
    const c = theme.color;
    expect(c.filter((x) => contrast(x, theme.backgroundColor) < SERIES_MIN)).toEqual([]);
    c.forEach((x, i) => {
      const y = c[(i + 1) % c.length];
      const min = isLegacy(name, x) && isLegacy(name, y) ? ADJ_DE_MIN : NEW_DE_MIN;
      expect([x, y, de2000(x, y) >= min]).toEqual([x, y, true]);
    });
  });
});

test("ΔE00 实现自检：PALETTE 相邻对与 S 独立实现逐位一致（31.0 / 46.6 / …），#CD7D28↔#C0392B 25.0", () => {
  const old = ["#1F6FB2", "#159A8C", "#E2843B", "#C0392B", "#7E57C2", "#3A7D44"];
  expect(old.map((x, i) => de2000(x, old[(i + 1) % 6]).toFixed(1))).toEqual(["31.0", "46.6", "24.5", "38.2", "46.9", "43.5"]);
  expect(de2000("#CD7D28", "#C0392B").toFixed(1)).toBe("25.0");
  expect(contrast("#E2843B", "#FFFFFF").toFixed(2)).toBe("2.76");
  expect(contrast("#CD7D28", "#FFFFFF").toFixed(2)).toBe("3.20");
});

test("默认主题的 color 就是 chart_schema.json 的 palette（与 matplotlib 同一套，后端测试钉住两份相等）", () => {
  expect(DEFAULT_THEME).toBe("classic");
  expect(THEMES.classic.theme.color).toEqual(schema.palette);
});

test("暗色画布：bg 不亮于 #1B1F24（PALETTE 最弱色在其上 ≥ 3.0 的边界）", () => {
  expect(lum(THEMES.darkCanvas.theme.backgroundColor)).toBeLessThanOrEqual(lum("#1B1F24"));
  expect(Math.min(...schema.palette.map((c) => contrast(c, "#1B1F24")))).toBeGreaterThanOrEqual(SERIES_MIN);
  expect(Math.min(...schema.palette.map((c) => contrast(c, "#20242A")))).toBeLessThan(SERIES_MIN); // 再亮一档就破线
});

// ---- 主题真的生效：每套主题 × 全部夹具，零 [ECharts] log，第一个系列的颜色 = 主题 color[0]（没被 option 压住）
function seriesColor0(c: ReturnType<typeof init>) {
  const m = (c as unknown as { getModel(): { getSeriesByIndex(i: number): { getData(): { getVisual(k: string): unknown } } } }).getModel();
  return String(m.getSeriesByIndex(0).getData().getVisual("style") && (m.getSeriesByIndex(0).getData().getVisual("style") as { fill?: string }).fill);
}
describe.each(THEME_NAMES)("主题 %s × 全部夹具", (name) => {
  test.each(FIX.map((f) => [f.id, f.spec] as const))("%s", (_id, spec) => {
    const spies = (["warn", "error", "log"] as const).map((k) => vi.spyOn(console, k));
    const c = init(null, name, { renderer: "svg", ssr: true, width: 640, height: 400 });
    try {
      c.setOption(prepare(spec), { notMerge: true });
      c.renderToSVGString();
      const want = THEMES[name].theme.color[0].toLowerCase();
      if (spec.kind !== "pie") expect(seriesColor0(c).toLowerCase()).toBe(want);
      expect(spies[0]).not.toHaveBeenCalled();
      expect(spies[1]).not.toHaveBeenCalled();
      expect(spies[2].mock.calls.filter((a) => String(a[0]).startsWith("[ECharts]"))).toEqual([]);
    } finally {
      c.dispose();
      spies.forEach((s) => s.mockRestore());
    }
  });
});

test("历史 spec 里的 color 被 prepare 删掉，主题配色生效（第四步之前存进库的图）", () => {
  const spec = FIX.find((f) => f.id === "bar")!.spec;
  const old = { ...JSON.parse(JSON.stringify(spec.option)), color: ["#E2843B"] };
  expect("color" in prepare({ kind: "bar", option: old })).toBe(false);
  const c = init(null, "soft", { renderer: "svg", ssr: true, width: 640, height: 400 });
  c.setOption(prepare({ kind: "bar", option: old }), { notMerge: true });
  expect(seriesColor0(c).toLowerCase()).toBe(THEMES.soft.theme.color[0].toLowerCase());
  c.dispose();
});

test("setTheme 切换不重设 option：配色换掉，系列数不变", () => {
  const spec = FIX.find((f) => f.id === "line-wide")!.spec;
  const c = init(null, "classic", { renderer: "svg", ssr: true, width: 640, height: 400 });
  c.setOption(prepare(spec), { notMerge: true });
  c.setTheme("darkCanvas");
  const m = (c as unknown as { getModel(): { getSeries(): unknown[] } }).getModel();
  expect(m.getSeries().length).toBe((spec.option.series as unknown[]).length);
  expect(seriesColor0(c).toLowerCase()).toBe(THEMES.darkCanvas.theme.color[0].toLowerCase());
  // 背景真的换了：画布背景色 = 主题 backgroundColor
  expect((c.getOption() as { backgroundColor?: string }).backgroundColor).toBe(THEMES.darkCanvas.theme.backgroundColor);
  c.dispose();
});

test("后端给 yAxis.nameTextStyle 设了 align，轴名颜色仍取主题的 nameTextStyle.color（深合并，不被整块覆盖）", () => {
  const spec = FIX.find((f) => f.id === "bar")!.spec;
  for (const name of THEME_NAMES) {
    const c = init(null, name, { renderer: "svg", ssr: true, width: 640, height: 400 });
    c.setOption(prepare(spec), { notMerge: true });
    const o = c.getOption() as { yAxis: { nameTextStyle: { color?: string; align?: string } }[] };
    expect([name, o.yAxis[0].nameTextStyle]).toEqual([name, expect.objectContaining({ align: "left", color: THEMES[name].theme.valueAxis.nameTextStyle.color })]);
    c.dispose();
  }
});

describe("主题选择的持久化", () => {
  afterEach(() => localStorage.clear());
  test("不认识的名字（改名 / 删除 / 手改）回退默认", () => {
    expect(resolveTheme("macarons")).toBe(DEFAULT_THEME);
    expect(resolveTheme(null)).toBe(DEFAULT_THEME);
    expect(resolveTheme("toString")).toBe(DEFAULT_THEME); // 原型链上的键不算
    localStorage.setItem(STORAGE_KEY, "old-name");
    reloadChartThemeForTest();
    expect(getChartTheme()).toBe(DEFAULT_THEME);
  });
  test("设置后写入 localStorage，重新读取保持", () => {
    setChartTheme("business");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("business");
    reloadChartThemeForTest();
    expect(getChartTheme()).toBe("business");
    setChartTheme("nope");
    expect(getChartTheme()).toBe(DEFAULT_THEME);
  });
});

test("LEGACY 豁免按 (主题, 色值)：同一个旧色值放在别的主题里不豁免", () => {
  expect(isLegacy("classic", "#1f6fb2")).toBe(true);
  expect(isLegacy("soft", "#1F6FB2")).toBe(false);
  expect(isLegacy("classic", "#CD7D28")).toBe(false); // 第四步新色本身也不豁免
});
