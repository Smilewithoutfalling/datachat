// V2b P2-19（phase5「阶段 5 收尾」A1）：y 轴留顶。数值标签开着时，最大值正好落在整刻度上（夹具 bar 最大 8，ECharts 自动上限
// 也是 8），最高的柱顶数值会画到网格外。这里按数据量级挑一个整齐的步长，写 yAxis.max = n × step 和 yAxis.interval = step。
// - 只在数值标签解析为开、图型是柱 / 线 / 面积、y 是值轴、且层 1 之后 yAxis.min / max 都没设时触发（用户填了就以用户为准）。
//   随数值标签走，所以"全关 = 后端原样"契约和 chart_fixtures 都不受影响；放前端是因为数值标签的默认值在前端（P2-18）。
// - 必须同时写 interval：只写 max 时 ECharts 按 splitNumber 选间隔，不一定整除上限（SSR 实测：max 12.5 → 0,3,6,9,12,12.5）。
// - 判据写死：t = dmax × 1.08；候选步长 [1, 2, 2.5, 5] × 10^k 升序，k 从 floor(log10(t / 6)) 起；取第一个
//   ceil(t / step) ≤ N 的（N 非紧凑 6、紧凑 3，紧凑不把 issue #49 收掉的刻度密度加回去）。
// - 写出的键登记在 HEADROOM_KEYS（M13 §12「数值标签」一行的"前端实际写出"同步列出），headroom.test.ts 做机制测试。
import type { Json, Option } from "./prepare";
import { compat, type Shape, type Switches } from "./switches";

export const HEADROOM_KEYS = ["yAxis.max", "yAxis.interval"] as const;
export const HEADROOM_PAD = 1.08;
export const HEADROOM_BASES = [1, 2, 2.5, 5] as const;
export const HEADROOM_N = { normal: 6, compact: 3 } as const;

const isObj = (v: Json | undefined): v is { [k: string]: Json } => v !== null && typeof v === "object" && !Array.isArray(v);
const num = (v: Json): number | null => {
  const x = typeof v === "number" ? v : isObj(v) && typeof v.value === "number" ? v.value : null;
  return x !== null && Number.isFinite(x) ? x : null;
};

/** 步长的小数位数：b × 10^k，k < 0 时 -k 位，2.5 再多一位。 */
function decimals(b: number, k: number): number {
  return Math.max(0, -k + (b === 2.5 ? 1 : 0));
}

/** 纯函数：最大值 → { max, interval }；dmax ≤ 0 或非有限数返回 null（全负的图标签在下面，不顶上沿）。 */
export function niceMax(dmax: number, compact = false): { max: number; interval: number } | null {
  if (!Number.isFinite(dmax) || dmax <= 0) return null;
  const n = compact ? HEADROOM_N.compact : HEADROOM_N.normal;
  const t = dmax * HEADROOM_PAD;
  for (let k = Math.floor(Math.log10(t / HEADROOM_N.normal)); k < 400; k++) {
    for (const b of HEADROOM_BASES) {
      const d = decimals(b, k);
      const step = Number((b * 10 ** k).toFixed(Math.min(d, 100)));
      const cells = Math.ceil(t / step - 1e-12);
      if (cells <= n) return { max: Number((cells * step).toFixed(Math.min(d, 100))), interval: step };
    }
  }
  return null;
}

/** 系列值的最大值；stacked 时取每个类目同号（正）堆叠和的最大值（ECharts 默认 samesign 堆叠，负值往下堆，不顶上沿）。 */
export function dataMax(o: Option, stacked: boolean): number {
  const series = Array.isArray(o.series) ? o.series.filter(isObj) : [];
  let best = -Infinity;
  if (stacked) {
    const sums: number[] = [];
    for (const s of series) {
      if (!Array.isArray(s.data)) continue;
      s.data.forEach((v, i) => {
        const x = num(v);
        if (x !== null && x > 0) sums[i] = (sums[i] ?? 0) + x;
      });
    }
    for (const x of sums) if (x !== undefined && x > best) best = x;
    return best;
  }
  for (const s of series) if (Array.isArray(s.data)) for (const v of s.data) { const x = num(v); if (x !== null && x > best) best = x; }
  return best;
}

/** 就地改。shape 是换图型之后的形状，sw 是解析后的开关。 */
export function applyHeadroomTo(o: Option, shape: Shape, sw: Switches, compact: boolean): Option {
  if (shape.kind !== "bar" && shape.kind !== "line" && shape.kind !== "area") return o;
  if (!sw.label || !compat("label", shape).ok) return o;
  const y = o.yAxis;
  if (!isObj(y) || y.type !== "value") return o;
  if (y.min !== undefined || y.max !== undefined) return o;
  const stacked = sw.stack && compat("stack", shape).ok;
  const r = niceMax(dataMax(o, stacked), compact);
  if (!r) return o;
  y.max = r.max;
  y.interval = r.interval;
  return o;
}
