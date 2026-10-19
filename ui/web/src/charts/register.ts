// F3：ECharts 按需注册（docs/roadmap/phase5-frontend.md「F3-ECharts 第一步」第 1–3 条）。
// 映射表的键 = 后端白名单（generated/chart_schema.json：_ALLOWED 顶层键 + _ENUMS 的每个取值），值 = 需要注册的组件。
// 不需要组件的项也显式写 NONE：后端新增任何键或枚举值，charts.test.ts 的双向比对就红，必须有人在这里确认过。
// 只从 echarts/core 按需引入（ESLint 禁止 import "echarts" 全量包）。产品只注册 CanvasRenderer；SVGRenderer 只在测试里注册。
import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { use as installEcharts, registerTheme } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { THEMES } from "./themes";

type Ext = Exclude<Parameters<typeof installEcharts>[0], readonly unknown[]>;
const NONE: Ext[] = [];

// _ALLOWED 的顶层键。xAxis / yAxis 由 GridComponent 提供（直角坐标系）；series 的组件按 series.type 定。
// color 不在其中（F3 第四步）：配色归主题，后端不再产出。
export const TOP_LEVEL: Record<string, Ext[]> = {
  title: [TitleComponent],
  tooltip: [TooltipComponent],
  legend: [LegendComponent],
  // grid 用 outerBounds（后端 F3 第三步替换了已弃用的 containLabel），GridComponent 自带，不需要 LegacyGridContainLabel。
  // containLabel 已从后端白名单删除，"option 里出现 containLabel"由 validate_spec 保证不会发生。
  grid: [GridComponent],
  xAxis: [GridComponent],
  yAxis: [GridComponent],
  series: NONE,
};

// _ENUMS 的每个取值。已核对 echarts 6.1.0：LegendComponent 的 install 同时装了 plain 和 scroll。
// 后端没有 time 轴：时间列走 category + ISO 字符串（charts.py），所以不注册 time 轴。
export const ENUMS: Record<string, Record<string, Ext[]>> = {
  "tooltip.trigger": { axis: NONE, item: NONE },
  "legend.type": { plain: [LegendComponent], scroll: [LegendComponent] },
  "legend.orient": { horizontal: NONE, vertical: NONE },
  "xAxis.type": { category: [GridComponent], value: [GridComponent] },
  "yAxis.type": { value: [GridComponent] },
  "series.type": { bar: [BarChart], line: [LineChart], pie: [PieChart], scatter: [ScatterChart] },
  "grid.outerBoundsMode": { same: NONE },
  "grid.outerBoundsContain": { all: NONE },
  "grid.outerBoundsClampWidth": { "25%": NONE },
  "grid.outerBoundsClampHeight": { "25%": NONE },
  "xAxis.nameLocation": { middle: NONE },
  "yAxis.nameTextStyle.align": { left: NONE },
};

export const RENDERER: Ext = CanvasRenderer;

export function productExtensions(): Ext[] {
  const all = [...Object.values(TOP_LEVEL).flat(), ...Object.values(ENUMS).flatMap((m) => Object.values(m).flat())];
  return [...new Set(all)];
}

let done = false;
export function registerCharts(): void {
  if (done) return;
  installEcharts([...productExtensions(), RENDERER]);
  for (const [name, { theme }] of Object.entries(THEMES)) registerTheme(name, theme);
  done = true;
}
