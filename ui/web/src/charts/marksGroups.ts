// F4 迭代 V1（phase5「F4 迭代 V1」第 3、4 条）：标记卡 5 组、12 项，以及组 tile 的可用性和理由。
// 纪律是"不适用就不渲染"（第 2 条）：项的可见性只读 compat() / hasAxis()，和 applySwitches 的过滤读同一张 COMPAT，
// 所以隐藏只是视觉，生效规则不变。组理由是静态组文案，不从组内各项的 compat 理由拼接（各项理由互不相同）。
// 按现有 COMPAT，能走到的不可用情形只有三种（第 4 条的表）；marksGroups.test.ts 逐格枚举钉住，COMPAT 一改这里就红。
import { colorByAvailable, hasAxis } from "./layer1";
import { compat, KIND_LABEL, type Shape, type SwitchName } from "./switches";

export const GROUPS = ["color", "label", "shape", "axis", "text"] as const;
export type Group = (typeof GROUPS)[number];
export const GROUP_LABEL: Record<Group, string> = { color: "颜色", label: "标签", shape: "形状", axis: "轴", text: "文字" };
export const GROUP_ICON: Record<Group, string> = { color: "◐", label: "#", shape: "◢", axis: "↕", text: "A" };

/** 组内各项（按组内顺序）。F3 开关用开关名；F4 原有的四项用自己的名字。 */
// V2b：颜色组加「按列着色」（colorBy，B2，只对单系列柱图）、文字组加「标题」（title，B3）。
export type Item = SwitchName | "colors" | "other" | "range" | "font" | "colorBy" | "title";
export const GROUP_ITEMS: Record<Group, readonly Item[]> = {
  color: ["colorBy", "colors", "gradient", "other"],
  label: ["label", "legend"],
  shape: ["stack", "smooth", "radius"],
  axis: ["range", "zoom", "marks"],
  text: ["title", "font"],
};

/** 一项在这个图形状下是否渲染。 */
export function itemOn(item: Item, s: Shape): boolean {
  switch (item) {
    case "colors":
    case "font":
    case "title":
      return true;
    case "colorBy":
      return colorByAvailable(s.kind, s.series);
    case "other":
      return s.kind === "pie";
    case "range":
      return hasAxis(s.kind);
    default:
      return compat(item, s).ok;
  }
}

/** 组整组不可用时的静态文案。只有第 4 条表里的三种情形能走到；其余组合返回 null（组可用）。
 *  V2b B1：理由写在组头「当前值」的位置（原 .marks-why 一行删掉），文案不变。 */
export function groupReason(g: Group, s: Shape): string {
  switch (g) {
    case "shape": return `${KIND_LABEL[s.kind]}没有可调的形状`;
    case "axis": return "饼图没有 y 轴";
    case "label": return "散点图不显示数值标签，单系列也没有图例";
    default: return `${KIND_LABEL[s.kind]}没有可调的${GROUP_LABEL[g]}`; // 颜色、文字恒可用，走不到
  }
}

export type GroupState = { group: Group; ok: boolean; reason: string | null; items: Item[] };
export function groupStates(s: Shape): GroupState[] {
  return GROUPS.map((group) => {
    const items = GROUP_ITEMS[group].filter((i) => itemOn(i, s));
    const ok = items.length > 0;
    return { group, ok, reason: ok ? null : groupReason(group, s), items };
  });
}
