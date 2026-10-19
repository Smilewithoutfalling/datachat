// F3 第六步：导出 PNG（docs/roadmap/phase5-frontend.md「F3 第六步」）。
// - 离屏实例：不挂 DOM 的 div，init 时给 width / height（实测可用，每张约 22 ms）。和屏幕走同一条 prepare，
//   导出结果只由 (spec, ui, theme, size) 决定；交互态在 ui.view 里，不从屏幕实例捞（S 10-19）。
// - animation: false 只在这里写、不进 prepare：setOption 后立刻 getDataURL 会拍到入场动画的半成品
//   （实测同一张 bar：保留动画非背景像素 21,921，关掉 365,183）。它不是开关产物，不进 FRONTEND_KEYS。
// - 背景来自主题；getDataURL 的 backgroundColor 参数盖不过不透明的主题背景（实测），所以"导出为浅色（经典配色）"
//   是换成 classic 整体重画（渐变色值由 prepare 按主题写死，必须重新 prepare）。
// - dispose 在 finally：抛错也释放。
// - 下载用 data URL + <a download>：img-src 已允许 data:；不走 fetch 转 blob（connect-src 'self' 会拦，实测）。
import { init } from "echarts/core";
import { type ChartInput, prepare, type UiState } from "./prepare";
import { registerCharts } from "./register";
import type { ThemeName } from "./themes";

export const EXPORT_PIXEL_RATIO = 2;
export type Size = { width: number; height: number };

export function exportPng(spec: ChartInput, ui: UiState, theme: ThemeName, size: Size): string {
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
