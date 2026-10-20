// issue #49：矮画布紧凑几何。grid.top 60、grid.bottom 30/50、x 轴 nameGap 28 是固定像素，1200×220 时三者共 118px（54%），
// plot 区只剩 26%；值轴刻度 0–3 按 0.5 一档排 7 个，在 58px 里互相重叠，hideOverlap 把 0 和 3 吞掉——图在"说谎"。
// 修法：容器高 < COMPACT_BELOW 时（EChart 用 ResizeObserver 量，导出用同一个尺寸）收紧这三个数，并让值轴少分几档、首末刻度必画。
// 只在前端渲染期做，后端 spec 不变（几何契约 GEOMETRY 不动）；写出的键登记在 COMPACT_KEYS，compact.test.ts 做机制测试。
import type { Json, Option } from "./prepare";

export const COMPACT_BELOW = 300; // 默认卡片 360 不触发；220 触发
export const COMPACT = { topTitled: 36, topBare: 16, bottomCut: 16, bottomMin: 14, nameGap: 22, splitNumber: 3 } as const;
export const COMPACT_KEYS = ["grid.top", "grid.bottom", "xAxis.nameGap", "yAxis.splitNumber", "yAxis.axisLabel.showMinLabel", "yAxis.axisLabel.showMaxLabel"] as const;

const isObj = (v: Json | undefined): v is { [k: string]: Json } => v !== null && typeof v === "object" && !Array.isArray(v);

export function isCompact(height: number): boolean {
  return Number.isFinite(height) && height > 0 && height < COMPACT_BELOW;
}

/** 就地改。只收紧不放宽：已有值比紧凑值还小就不动。饼图没有 grid / 轴，原样返回。 */
export function applyCompactTo(option: Option): Option {
  const grid = option.grid;
  if (!isObj(grid)) return option;
  const titled = isObj(option.title) && typeof option.title.text === "string" && option.title.text !== "";
  const top = titled ? COMPACT.topTitled : COMPACT.topBare;
  if (typeof grid.top === "number" && grid.top > top) grid.top = top;
  if (typeof grid.bottom === "number") grid.bottom = Math.max(COMPACT.bottomMin, grid.bottom - COMPACT.bottomCut);
  if (isObj(option.xAxis) && typeof option.xAxis.nameGap === "number" && option.xAxis.nameGap > COMPACT.nameGap) option.xAxis.nameGap = COMPACT.nameGap;
  if (isObj(option.yAxis) && option.yAxis.type === "value") {
    option.yAxis.splitNumber = COMPACT.splitNumber;
    const al = isObj(option.yAxis.axisLabel) ? option.yAxis.axisLabel : (option.yAxis.axisLabel = {});
    al.showMinLabel = true;
    al.showMaxLabel = true;
  }
  return option;
}
