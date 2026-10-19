// F3 第五步：开关偏好按图型存（S 10-19，D）：localStorage 的 datachat.chartUi:<kind>，最多 5 个键，和 COMPAT 的维度一致。
// 语义是"饼图看百分比、柱图看原始值"这类图型偏好：新出的同图型图直接继承，删会话不留残留。
// 键名取换图型之后的图型（用户眼前的）。"换成什么图型"不持久化（对单张图的操作，刷新回到后端图型）。
// 读写都包 try/catch（F2 token.ts 的教训：隐私模式 / 配额满会抛）；写失败只是不持久化，不影响渲染。
import { DEFAULT_SWITCHES, type Kind, SWITCHES, SWITCH_VALUES, type Switches } from "./switches";

export const PREFS_PREFIX = "datachat.chartUi:";
const cache = new Map<Kind, Switches>();
const listeners = new Set<() => void>();

/** 逐字段校验：不认识的字段丢弃，不合法的值回退默认。 */
export function parseSwitches(raw: unknown): Switches {
  const out: Record<string, unknown> = { ...DEFAULT_SWITCHES };
  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    for (const s of SWITCHES) {
      const v = (raw as Record<string, unknown>)[s];
      if ((SWITCH_VALUES[s] as readonly unknown[]).includes(v)) out[s] = v;
    }
  }
  return out as Switches;
}

function read(kind: Kind): Switches {
  try {
    const raw = localStorage.getItem(PREFS_PREFIX + kind);
    return raw === null ? DEFAULT_SWITCHES : parseSwitches(JSON.parse(raw));
  } catch {
    return DEFAULT_SWITCHES;
  }
}

/** 同一图型返回同一个对象（useSyncExternalStore 要求快照稳定）。 */
export function getPrefs(kind: Kind): Switches {
  let v = cache.get(kind);
  if (!v) cache.set(kind, (v = read(kind)));
  return v;
}
export function setPrefs(kind: Kind, sw: Switches): void {
  const v = parseSwitches(sw);
  cache.set(kind, v);
  try {
    localStorage.setItem(PREFS_PREFIX + kind, JSON.stringify(v));
  } catch {
    /* 存不了就只在本页生效 */
  }
  for (const l of listeners) l();
}
export function subscribePrefs(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
/** 测试用：清掉内存缓存，下次从 localStorage 重读。 */
export function resetPrefsForTest(): void {
  cache.clear();
}
