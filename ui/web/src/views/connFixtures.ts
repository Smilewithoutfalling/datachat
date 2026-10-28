// 阶段 6.5 测试夹具：服务商目录（app/core/providers.json 的子集，字段同形）和一个有状态的连接假后端。
import type { Catalog, Connection, ConnectionIn, Quirks } from "../types";

export const CATALOG: Catalog = {
  protocols: ["openai_chat", "openai_responses", "azure", "anthropic"],
  custom_protocols: ["openai_chat", "openai_responses", "anthropic"],
  groups: ["cn", "global", "local", "custom"],
  providers: [
    { id: "deepseek", name: "DeepSeek", group: "cn", protocol: "openai_chat", base_url: "https://api.deepseek.com", needs_key: true,
      key_url: "https://platform.deepseek.com/api_keys", models: ["deepseek-flash", "deepseek-v4-pro"], quirks: { reasoning_replay: true } },
    { id: "zhipu", name: "智谱", group: "cn", protocol: "openai_chat", base_url: "https://open.bigmodel.cn/api/paas/v4", needs_key: true,
      key_url: "https://bigmodel.cn/usercenter/proj-mgmt/apikeys", models: ["glm-5.3"], quirks: { thinking_param: "thinking" } },
    { id: "anthropic", name: "Anthropic", group: "global", protocol: "anthropic", base_url: "https://api.anthropic.com", needs_key: true,
      key_url: "https://platform.claude.com/settings/keys", models: ["claude-sonnet-5-5"], quirks: {} },
    { id: "azure", name: "Azure OpenAI", group: "global", protocol: "azure", base_url: "", needs_key: true,
      key_url: "https://portal.azure.com/", models: [], quirks: {} },
    { id: "ollama", name: "Ollama", group: "local", protocol: "openai_chat", base_url: "http://localhost:11434/v1", needs_key: false,
      key_url: null, models: [], quirks: {} },
    { id: "custom", name: "自定义", group: "custom", protocol: "openai_chat", base_url: "", needs_key: true, key_url: null, models: [], quirks: {} },
  ],
};

const Q0: Quirks = { no_stream_options: false, no_array_content: false, reasoning_replay: false, thinking_param: null };

export function envConn(over: Partial<Connection> = {}): Connection {
  return {
    id: "env", name: "环境变量", provider: "deepseek", protocol: "openai_chat", base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat", extra: {}, quirks: Q0, probe: null, created_at: null, updated_at: null, active: true, readonly: true,
    key: { needed: true, configured: false, source: null }, ...over,
  };
}

export function conn(over: Partial<Connection> = {}): Connection {
  return {
    id: "c1", name: "DeepSeek 个人", provider: "deepseek", protocol: "openai_chat", base_url: "https://api.deepseek.com",
    model: "deepseek-flash", extra: {}, quirks: { ...Q0, reasoning_replay: true }, probe: null, created_at: "t1", updated_at: "u1",
    active: true, readonly: false, key: { needed: true, configured: true }, ...over,
  };
}

/** 有状态的连接后端：POST / PUT / DELETE / activate / api-key 真的改 items，GET /connections 读当前状态。 */
export function connRoutes(initial: Connection[], extra: { settingsTimeout?: number } = {}) {
  const st = { items: [...initial], n: 0, keys: {} as Record<string, string> };
  const list = () => {
    if (!st.items.length) return { active: "env", items: [envConn()] };
    if (!st.items.some((x) => x.active)) st.items[0] = { ...st.items[0], active: true };
    return { active: st.items.find((x) => x.active)!.id, items: st.items };
  };
  const idOf = (path: string) => decodeURIComponent(path.split("/")[2]);
  const routes: Record<string, unknown> = {
    "GET /providers": CATALOG,
    "GET /connections": () => list(),
    "GET /settings": () => {
      const a = list().items.find((x) => x.active)!;
      return { model: a.model, base_url: a.base_url, timeout: extra.settingsTimeout ?? 60,
        sources: { model: a.readonly ? "default" : "connection", base_url: a.readonly ? "default" : "connection", timeout: "default" },
        connection: { id: a.id, name: a.name } };
    },
    "PUT /settings": (b: unknown) => ({ ...(routes["GET /settings"] as () => object)(), ...(b as object) }),
    "POST /connections": (b: unknown) => {
      const body = b as ConnectionIn;
      const p = CATALOG.providers.find((x) => x.id === body.provider)!;
      const first = !st.items.length;
      const c = conn({ id: `c${++st.n + 100}`, name: body.name, provider: body.provider, protocol: body.protocol ?? p.protocol,
        base_url: body.base_url || p.base_url, model: body.model, extra: body.extra ?? {}, active: first,
        key: { needed: p.needs_key, configured: false }, updated_at: `u${st.n}` });
      st.items.push(c);
      return c;
    },
  };
  // 带 id 的路由：fakeBackend 按完整路径匹配，所以按实际会用到的 id 现生成
  const withId = (id: string) => {
    routes[`PUT /connections/${id}`] = (b: unknown) => {
      const i = st.items.findIndex((x) => x.id === id);
      st.items[i] = { ...st.items[i], ...(b as object), updated_at: `u${++st.n}` } as Connection;
      return st.items[i];
    };
    routes[`DELETE /connections/${id}`] = () => ((st.items = st.items.filter((x) => x.id !== id)), list());
    routes[`POST /connections/${id}/activate`] = () => ((st.items = st.items.map((x) => ({ ...x, active: x.id === id }))), list());
    routes[`PUT /connections/${id}/api-key`] = (b: unknown, path: string) => {
      st.keys[idOf(path)] = (b as { api_key: string }).api_key;
      const i = st.items.findIndex((x) => x.id === id);
      st.items[i] = { ...st.items[i], key: { needed: true, configured: true }, updated_at: `u${++st.n}` };
      return { needed: true, configured: true };
    };
  };
  ["c1", "c2", "c101", "c102"].forEach(withId);
  return { routes, st };
}
