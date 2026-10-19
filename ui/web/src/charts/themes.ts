// F3 第四步：4 套自研主题（docs/roadmap/phase5-frontend.md「F3 第四步」）。
// - 主题是 echarts 的"默认值层"：后端 option 管内容，主题管外观。option 不带 color（后端第四步摘掉），否则
//   mergeTheme 里 `name === 'color' && option.color` 会整条跳过主题配色。
// - 4 套只在"配色 + 背景"一个轴上区分；排版、线宽、网格不作为区分维度（免得看起来像同一套的两种深度）。
// - 每套逐键写全（themes.test.ts 断言 REQUIRED_PATHS 全在）；backgroundColor 必须显式设：不设画布透明，
//   暗色画布会透出白页面。
// - 不设 rich / formatter / renderMode，也不设任何 BANNED_KEYS：注入判定表不随主题变（判定表纪律③：哪天主题真配了 rich，
//   测试变红是对的，那时按纪律改期望值）。
// - 对比度（themes.test.ts 纯计算）：文字对背景 ≥ 4.5（WCAG 1.4.3）；系列色对背景 ≥ 3.0（WCAG 1.4.11），
//   相邻系列 CIEDE2000 ≥ 20（外部标准，不是本仓库实测最小值），本步新引入的颜色 ≥ 22（余量）。
import schema from "../generated/chart_schema.json";

type Text = { color: string };
type Line = { lineStyle: { color: string } };
type Axis = { axisLine: Line; axisTick: Line; axisLabel: Text; splitLine: Line; nameTextStyle: Text };
export type Theme = {
  color: string[];
  backgroundColor: string;
  textStyle: Text;
  title: { textStyle: Text };
  legend: { textStyle: Text; pageTextStyle: Text; inactiveColor: string };
  tooltip: { backgroundColor: string; borderColor: string; textStyle: Text };
  categoryAxis: Axis;
  valueAxis: Axis;
  timeAxis: Axis;
  pie: { itemStyle: { borderColor: string } };
};

type Tones = { bg: string; text: string; title: string; label: string; line: string; split: string; tipBg: string; tipBorder: string; inactive: string };

function build(color: readonly string[], t: Tones): Theme {
  const axis = (): Axis => ({
    axisLine: { lineStyle: { color: t.line } },
    axisTick: { lineStyle: { color: t.line } },
    axisLabel: { color: t.label },
    splitLine: { lineStyle: { color: t.split } },
    nameTextStyle: { color: t.label },
  });
  return {
    color: [...color],
    backgroundColor: t.bg,
    textStyle: { color: t.text },
    title: { textStyle: { color: t.title } },
    legend: { textStyle: { color: t.text }, pageTextStyle: { color: t.text }, inactiveColor: t.inactive },
    tooltip: { backgroundColor: t.tipBg, borderColor: t.tipBorder, textStyle: { color: t.text } },
    categoryAxis: axis(),
    valueAxis: axis(),
    timeAxis: axis(),
    pie: { itemStyle: { borderColor: t.bg } },
  };
}

// 浅色三套共用的文字与线条：echarts 默认轴标签灰 #6E7079 白底 4.93，勉强过；这里取 #5F6368（6.05）留余量。
const LIGHT: Tones = {
  bg: "#FFFFFF", text: "#3C4043", title: "#1F2328", label: "#5F6368", line: "#8C959F", split: "#E6E8EB",
  tipBg: "#FFFFFF", tipBorder: "#D0D7DE", inactive: "#B8BEC6",
};

// 暗色画布：bg 不得亮于 #1B1F24（PALETTE 中最弱的 #C0392B 在 #1B1F24 上 3.05、在 #20242A 上 2.87）。本主题用自己的提亮
// palette，不依赖这条边界，但 bg 仍取 #15181C。文字必须显式改：echarts 默认轴标签灰 #6E7079 在 #15181C 上只有 3.61。
const DARK: Tones = {
  bg: "#15181C", text: "#E6E8EB", title: "#F0F2F5", label: "#B0B7C0", line: "#59606B", split: "#2A2F36",
  tipBg: "#22262C", tipBorder: "#3A3F47", inactive: "#5C636E",
};

export const THEMES = {
  /** 经典（默认）：与 matplotlib 同一套主色，从 chart_schema.json 的 palette 读，不另抄一份。 */
  classic: { label: "经典", theme: build(schema.palette, LIGHT) },
  /** 柔和：低饱和配色。 */
  soft: { label: "柔和", theme: build(["#4E79A7", "#9C755F", "#59A14F", "#B07AA1", "#76716A", "#E15759"], LIGHT) },
  /** 商务蓝：藏青为主、冷色为辅（单一蓝色阶在白底 3:1 下相邻 ΔE00 到不了 20，所以不是纯色阶）。 */
  business: { label: "商务蓝", theme: build(["#1D3F72", "#2E86AB", "#8C6D1F", "#5B6B7A", "#8E3B46", "#1B7F79"], LIGHT) },
  /** 暗色画布：只有图是暗的，应用本身没有暗色模式——名字直说。 */
  darkCanvas: { label: "暗色画布", theme: build(["#5B9BD5", "#E5675A", "#3CC0AE", "#E39B4E", "#A887DB", "#6BB37A"], DARK) },
} as const satisfies Record<string, { label: string; theme: Theme }>;

export type ThemeName = keyof typeof THEMES;
export const DEFAULT_THEME: ThemeName = "classic";
export const THEME_NAMES = Object.keys(THEMES) as ThemeName[];

/** 不认识的名字（改名、删主题、手改 localStorage）回退默认。echarts 查不到主题名时会静默保持旧主题，所以必须先在这里收口。 */
export function resolveTheme(name: unknown): ThemeName {
  return typeof name === "string" && Object.prototype.hasOwnProperty.call(THEMES, name) ? (name as ThemeName) : DEFAULT_THEME;
}

// ---- 持久化 + 订阅（全局一个选择，所有图立即 setTheme；不做单图主题）
export const STORAGE_KEY = "datachat.chartTheme";
const listeners = new Set<() => void>();

function read(): ThemeName {
  try {
    return resolveTheme(localStorage.getItem(STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}
let current: ThemeName = read();

export function getChartTheme(): ThemeName {
  return current;
}
export function setChartTheme(name: string): void {
  current = resolveTheme(name);
  try {
    localStorage.setItem(STORAGE_KEY, current);
  } catch {
    /* 存不了就只在本页生效 */
  }
  for (const l of listeners) l();
}
export function subscribeChartTheme(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
/** 测试用：重新从 localStorage 读。 */
export function reloadChartThemeForTest(): void {
  current = read();
}
