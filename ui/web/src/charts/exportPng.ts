// F3 第六步：导出 PNG（docs/roadmap/phase5-frontend.md「F3 第六步」）。
// - 离屏实例：不挂 DOM 的 div，init 时给 width / height（实测可用，每张约 22 ms）。和屏幕走同一条 prepare，
//   导出结果只由 (spec, ui, theme, size) 决定；交互态在 ui.view 里，不从屏幕实例捞（S 10-19）。
// - animation: false 只在这里写、不进 prepare：setOption 后立刻 getDataURL 会拍到入场动画的半成品
//   （实测同一张 bar：保留动画非背景像素 21,921，关掉 365,183）。它不是开关产物，不进 FRONTEND_KEYS。
// - 背景来自主题；getDataURL 的 backgroundColor 参数盖不过不透明的主题背景（实测），所以"导出为浅色（经典配色）"
//   是换成 classic 整体重画（渐变色值由 prepare 按主题写死，必须重新 prepare）。
// - 主题必须在模块级注册（register.ts 的 registerCharts，带 done 标志、幂等），不能挂在组件生命周期里：离屏实例不挂 DOM、
//   不经过任何组件，init(div, "classic") 遇到没注册的主题名会静默回退默认主题，导出配色全错且不报错。所以这里在 init
//   之前自己调一次 registerCharts，不依赖屏幕上的 EChart 先挂载（exportPng.test「init 之前已注册」钉住）。
// - 尺寸为 0（容器 display:none）直接抛错，不让 getDataURL 静默产出坏图；EChart 接住显示"导出失败"。
// - dispose 在 finally：抛错也释放。
// - 下载用 data URL + <a download>：img-src 已允许 data:；不走 fetch 转 blob（connect-src 'self' 会拦，实测）。
import { init } from "echarts/core";
import { type ChartInput, prepare, type UiState } from "./prepare";
import { registerCharts } from "./register";
import type { ThemeName } from "./themes";

export const EXPORT_PIXEL_RATIO = 2;
export type Size = { width: number; height: number };

export function exportPng(spec: ChartInput, ui: UiState, theme: ThemeName, size: Size): string {
  if (!(size.width > 0 && size.height > 0)) throw new Error(`export size ${size.width}x${size.height}`);
  registerCharts();
  const chart = init(document.createElement("div"), theme, { renderer: "canvas", width: size.width, height: size.height });
  try {
    const option = prepare(spec, ui, theme);
    option.animation = false;
    chart.setOption(option, { notMerge: true });
    return chart.getDataURL({ type: "png", pixelRatio: EXPORT_PIXEL_RATIO });
  } finally {
    chart.dispose();
  }
}

/** 触发浏览器下载。a 不挂进 DOM。 */
export function download(dataUrl: string, filename: string): void {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}
