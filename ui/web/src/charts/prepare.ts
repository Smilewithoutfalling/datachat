// F3 prepare v0：深拷贝 → 按 banned_keys.json 递归删除被禁键 → 强制 tooltip.renderMode='richText'。
// 纵深防御：第一道是后端 validate_spec（app/tools/charts.py），这里只在后端校验有漏洞时兜底；不是前端校验，也不回验。
// 不修改输入。renderMode 本身也在禁用键里（后端不许决定它），删完之后由这里统一写成 richText（THREAT_MODEL §2.3）。
import generated from "../generated/banned_keys.json";

export const BANNED_KEYS: ReadonlySet<string> = new Set(generated.banned_keys);

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

function strip(node: Json): Json {
  if (Array.isArray(node)) return node.map(strip);
  if (node !== null && typeof node === "object") {
    const out: { [k: string]: Json } = {};
    for (const [k, v] of Object.entries(node)) if (!BANNED_KEYS.has(k)) out[k] = strip(v);
    return out;
  }
  return node;
}

export function prepare(option: Record<string, unknown>): Record<string, unknown> {
  // JSON 往返就是深拷贝：option 来自 JSON 响应，本来就只有 JSON 值
  const out = strip(JSON.parse(JSON.stringify(option)) as Json) as { [k: string]: Json };
  const t = out.tooltip;
  if (Array.isArray(t)) {
    out.tooltip = t.map((x) => (x !== null && typeof x === "object" && !Array.isArray(x) ? { ...x, renderMode: "richText" } : { renderMode: "richText" }));
  } else if (t !== null && typeof t === "object") {
    out.tooltip = { ...t, renderMode: "richText" };
  } else {
    out.tooltip = { renderMode: "richText" };
  }
  return out;
}
