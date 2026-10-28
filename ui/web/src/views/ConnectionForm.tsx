import { type FormEvent, useId, useState } from "react";
import { type Client, errText } from "../client";
import type { Catalog, Connection, ConnectionIn, Protocol, Provider, ProviderGroup, Quirks, ThinkingParam } from "../types";

// 阶段 6.5 §5「编辑连接」：名称、服务商（分组下拉，选好后自动填 Base URL、显示「去申请 Key」）、自定义时选协议、Key（不需要 Key
// 的服务商隐藏）、Base URL（带「恢复默认」）、模型（可输入也可下拉，「获取模型列表」）、Azure 的部署名（走 v1 路径，不需要 API 版本）、「高级」里的怪癖开关。
// 怪癖只把和预设不同的那几项存成覆盖（extra.quirks），预设以后改了，没碰过的项跟着预设走。
export const GROUP_TEXT: Record<ProviderGroup, string> = { cn: "国内", global: "国外", local: "本地", custom: "自定义" };
export const PROTOCOL_TEXT: Record<Protocol, string> = {
  openai_chat: "OpenAI 兼容（Chat Completions）",
  openai_responses: "OpenAI Responses",
  azure: "Azure OpenAI",
  anthropic: "Anthropic",
};
const BOOL_QUIRKS: [keyof Omit<Quirks, "thinking_param">, string][] = [
  ["no_stream_options", "不发 stream_options（流式请求时有的网关会 400）"],
  ["no_array_content", "消息内容只发字符串（有的网关不认分段内容）"],
  ["reasoning_replay", "多轮工具调用时回传推理内容（DeepSeek 推理模型一类）"],
];

function presetQuirks(p: Provider | undefined): Quirks {
  const q = p?.quirks ?? {};
  return { no_stream_options: !!q.no_stream_options, no_array_content: !!q.no_array_content,
    reasoning_replay: !!q.reasoning_replay, thinking_param: q.thinking_param ?? null };
}

type Props = {
  c: Client;
  catalog: Catalog;
  conn?: Connection; // 没有 = 新建
  first?: boolean; // 首次启动引导（D2）
  onCancel: () => void;
  onSaved: (text: string, warn?: string) => void;
  onError: (e: unknown) => void;
};

export function ConnectionForm({ c, catalog, conn, first, onCancel, onSaved, onError }: Props) {
  const ids = useId();
  const byId = (id: string) => catalog.providers.find((p) => p.id === id);
  const initial = byId(conn?.provider ?? "deepseek") ?? catalog.providers[0];
  const [provider, setProvider] = useState(initial.id);
  const [name, setName] = useState(conn?.name ?? initial.name);
  const [nameTouched, setNameTouched] = useState(!!conn);
  const [protocol, setProtocol] = useState<Protocol>(conn?.protocol ?? initial.protocol);
  const [baseUrl, setBaseUrl] = useState(conn?.base_url ?? initial.base_url);
  const [model, setModel] = useState(conn?.model ?? initial.models[0] ?? "");
  const [deployment, setDeployment] = useState(conn?.extra.deployment ?? "");
  const [quirks, setQuirks] = useState<Quirks>(conn?.quirks ?? presetQuirks(initial));
  const [thinking, setThinking] = useState(!!conn?.extra.thinking);
  const [newKey, setNewKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [fetched, setFetched] = useState<string[]>([]);
  const [modelsNote, setModelsNote] = useState("");
  const [fetching, setFetching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localErr, setLocalErr] = useState("");

  const p = byId(provider) ?? initial;
  const custom = p.id === "custom";
  const azure = (custom ? protocol : p.protocol) === "azure";
  const needsKey = p.needs_key;
  const keySaved = !!conn && conn.key.configured && conn.provider === provider;
  const showKeyInput = needsKey && (!keySaved || replacing);
  const modelOptions = [...new Set([...p.models, ...fetched])];

  const pickProvider = (id: string) => {
    const np = byId(id);
    if (!np) return;
    const old = p;
    setProvider(id);
    setProtocol(np.protocol);
    setBaseUrl(np.base_url);
    // 模型名还是旧预设里的（或空），换成新预设的第一个；用户自己填的不动
    if (!model || old.models.includes(model) || fetched.includes(model)) setModel(np.models[0] ?? "");
    setFetched([]);
    setModelsNote("");
    setQuirks(presetQuirks(np));
    if (!nameTouched) setName(np.name);
  };

  const quirkOverride = (): Partial<Quirks> => {
    const base = presetQuirks(p);
    const out: Partial<Quirks> = {};
    (Object.keys(base) as (keyof Quirks)[]).forEach((k) => {
      if (quirks[k] !== base[k]) (out as Record<string, unknown>)[k] = quirks[k];
    });
    return out;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    const m = model.trim() || (azure ? deployment.trim() : "");
    if (!n) return setLocalErr("连接名称不能为空");
    if (!baseUrl.trim()) return setLocalErr("需要填 Base URL");
    if (!m) return setLocalErr(azure ? "填部署名或模型名" : "模型名不能为空");
    setLocalErr("");
    const body: ConnectionIn = {
      name: n, provider, model: m, base_url: baseUrl.trim(),
      ...(custom ? { protocol } : {}),
      extra: { deployment: azure ? deployment.trim() : "",
        thinking: quirks.thinking_param ? thinking : undefined, quirks: quirkOverride() },
    };
    setSaving(true);
    try {
      const saved = conn ? await c.updateConnection(conn.id, body) : await c.createConnection(body);
      const key = newKey.trim();
      setNewKey("");
      let warn: string | undefined;
      if (needsKey && key) {
        try {
          await c.setConnectionKey(saved.id, key);
        } catch (er) {
          warn = `连接已保存，但 API Key 没保存上：${errText(er)}`;
        }
      }
      onSaved(conn ? "连接已保存。" : first ? "第一个连接已建好并生效，可以测试一下。" : "连接已新建。", warn);
    } catch (er) {
      onError(er);
    } finally {
      setSaving(false);
    }
  };

  const fetchModels = () => {
    if (!conn) return;
    setFetching(true);
    c.connectionModels(conn.id).then(
      (r) => {
        setFetched(r.models);
        setModelsNote(r.source === "remote" ? `已获取 ${r.models.length} 个模型` : `没取到，下拉里是预设模型：${r.reason ?? ""}`);
      },
      (er) => setModelsNote(errText(er)),
    ).finally(() => setFetching(false));
  };

  return (
    <form onSubmit={submit} className="conn-form" data-testid="conn-form" aria-label={conn ? `编辑连接 ${conn.name}` : "新建连接"}>
      <div className="sec-head"><h3>{conn ? `编辑「${conn.name}」` : "新建连接"}</h3></div>
      {localErr ? <p className="banner danger" role="alert">{localErr}</p> : null}
      <label className="inline">
        名称
        <span className="ctl">
          <input aria-label="连接名称" value={name} maxLength={60} onChange={(e) => (setName(e.target.value), setNameTouched(true))} />
        </span>
      </label>
      <label className="inline">
        服务商
        <span className="ctl">
          <select aria-label="服务商" value={provider} onChange={(e) => pickProvider(e.target.value)}>
            {catalog.groups.map((g) => (
              <optgroup key={g} label={GROUP_TEXT[g]}>
                {catalog.providers.filter((x) => x.group === g).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </optgroup>
            ))}
          </select>
          {p.key_url ? <a href={p.key_url} target="_blank" rel="noreferrer noopener" data-testid="key-url">去申请 Key</a> : null}
        </span>
      </label>
      {custom ? (
        <label className="inline">
          协议
          <span className="ctl">
            <select aria-label="协议" value={protocol} onChange={(e) => setProtocol(e.target.value as Protocol)}>
              {catalog.custom_protocols.map((x) => <option key={x} value={x}>{PROTOCOL_TEXT[x]}</option>)}
            </select>
          </span>
        </label>
      ) : null}
      {needsKey ? (
        <div className="inline">
          API Key
          <span className="ctl">
            {showKeyInput ? (
              <span className="key-field">
                <input type="password" aria-label={keySaved ? "替换为新的 Key" : "API Key"} autoComplete="off" spellCheck={false}
                  value={newKey} maxLength={512} placeholder="粘贴 Key，保存后只存在本机系统凭据里" onChange={(e) => setNewKey(e.target.value)} />
                {replacing ? <button type="button" onClick={() => (setReplacing(false), setNewKey(""))}>取消</button> : null}
              </span>
            ) : (
              <span className="key-field">
                <input aria-label="当前 Key" value="已保存在系统凭据中" readOnly />
                <button type="button" onClick={() => setReplacing(true)}>更换</button>
              </span>
            )}
          </span>
        </div>
      ) : (
        <p className="hint" data-testid="no-key-needed">{p.name} 是本机服务，不需要 API Key。</p>
      )}
      <label className="inline">
        Base URL
        <span className="ctl">
          <input aria-label="Base URL" className="mono-input" value={baseUrl} maxLength={500} spellCheck={false}
            placeholder={azure ? "https://<资源名>.openai.azure.com" : "https://…/v1"} onChange={(e) => setBaseUrl(e.target.value)} />
          <button type="button" disabled={!p.base_url || baseUrl === p.base_url} onClick={() => setBaseUrl(p.base_url)}>恢复默认</button>
        </span>
      </label>
      {azure ? (
        <label className="inline">
          部署名
          <span className="ctl"><input aria-label="部署名" value={deployment} maxLength={200} onChange={(e) => setDeployment(e.target.value)} /></span>
        </label>
      ) : null}
      <label className="inline">
        {azure ? "模型名（可选）" : "模型"}
        <span className="ctl">
          <input aria-label="模型" className="mono-input" list={`${ids}-models`} value={model} maxLength={200} spellCheck={false}
            onChange={(e) => setModel(e.target.value)} />
          <datalist id={`${ids}-models`}>{modelOptions.map((m) => <option key={m} value={m} />)}</datalist>
          <button type="button" disabled={!conn || fetching} title={conn ? undefined : "先保存连接（和 Key），再获取"} onClick={fetchModels}>
            {fetching ? "获取中…" : "获取模型列表"}
          </button>
        </span>
      </label>
      {modelsNote ? <p className="hint" data-testid="models-note">{modelsNote}</p> : null}
      <details className="conn-advanced">
        <summary>高级</summary>
        {BOOL_QUIRKS.map(([k, label]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={quirks[k]} onChange={(e) => setQuirks({ ...quirks, [k]: e.target.checked })} />
            {label}
          </label>
        ))}
        <label className="inline">
          思考参数
          <span className="ctl">
            <select aria-label="思考参数" value={quirks.thinking_param ?? ""}
              onChange={(e) => setQuirks({ ...quirks, thinking_param: (e.target.value || null) as ThinkingParam })}>
              <option value="">不发送</option>
              <option value="enable_thinking">enable_thinking（Qwen 一类）</option>
              <option value="thinking">thinking（GLM、豆包一类）</option>
            </select>
            {quirks.thinking_param ? (
              <label className="check"><input type="checkbox" checked={thinking} onChange={(e) => setThinking(e.target.checked)} />开启思考</label>
            ) : null}
          </span>
        </label>
        <p className="hint">只在遇到对应报错时才需要改；默认值来自服务商预设。</p>
      </details>
      <div className="form-actions">
        <button type="submit" className="primary" disabled={saving}>{saving ? "保存中…" : conn ? "保存" : "新建并保存"}</button>
        <button type="button" onClick={onCancel}>取消</button>
      </div>
    </form>
  );
}
