import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type Client, errText } from "../client";
import type { Catalog, Connection, ConnectionTest, KeyStatus, MemoryMode, Settings, SettingSource } from "../types";
import { ConnectionForm } from "./ConnectionForm";
import { ConfirmButton } from "./ConfirmButton";
import { IconCheck, IconPlus, IconWarn } from "./icons";
import { TestResult } from "./TestResult";
import { Topbar } from "./ui";

// 阶段 6.5（docs/roadmap/phase65-models.md §5）：「模型」一节改成连接卡片列表 + 编辑表单。
// - 卡片：名称、服务商、模型、最近一次测试的 ✓/✗（probe 按「连接 + 模型」），生效的那张高亮；设为生效、测试、编辑、删除（二次确认）。
// - 没有任何连接时只有一张只读卡「环境变量」（DEEPSEEK_*），浏览器模式和 CI 靠它；建了第一个连接它就不再生效。
// - 首次启动引导（D2）：没有可用的 Key 时直接打开「新建连接」表单。
// - 测试：两步（连接 + 工具调用），两行结果；测的是**已保存**的配置。失败沿用 V2c §2 的口径（标题 + 建议 + 编号，原文折叠）。
// - 超时仍是全局设置（§3），单独一张表单，走旧的 PUT /settings {timeout}。
// API Key 只写不读：后端从不返回 Key 本身，表单也不保留输入值（保存后立即清空）。
const SOURCE_TEXT: Record<SettingSource, string> = { settings: "来自本页设置", env: "来自环境变量", default: "是默认值", connection: "来自连接" };

type Edit = { kind: "new" } | { kind: "edit"; id: string } | null;
type TestState = { id: string; state: "running" } | { id: string; state: "done"; r: ConnectionTest; stamp: string } | { id: string; state: "error"; text: string };

export function SettingsView({ c, onKeyChange, onBack }: { c: Client; onKeyChange: (k: KeyStatus) => void; onBack?: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [items, setItems] = useState<Connection[] | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [timeout, setTimeoutText] = useState("");
  const [memory, setMemory] = useState<MemoryMode>("off");
  const [edit, setEdit] = useState<Edit>(null);
  const [test, setTest] = useState<TestState | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const applyList = useCallback((list: Connection[]) => {
    setItems(list);
    const act = list.find((x) => x.active);
    // Shell 用它决定提问前拦不拦：生效连接需要 Key 而没填 → 未配置
    if (act) onKeyChange({ configured: !act.key.needed || act.key.configured, source: act.key.source ?? (act.key.configured ? "keyring" : null) });
    return act;
  }, [onKeyChange]);

  const refresh = useCallback(
    () => Promise.all([c.connections(), c.settings()]).then(([l, s]) => (applyList(l.items), setSettings(s))),
    [c, applyList],
  );

  useEffect(() => {
    Promise.all([c.providers(), c.connections(), c.settings()])
      .then(([cat, l, s]) => {
        setCatalog(cat);
        const act = applyList(l.items);
        setSettings(s);
        setTimeoutText(String(s.timeout));
        setMemory(s.memory?.setting ?? "off");
        // D2：没有任何能用的连接（只有环境变量且没 Key）→ 直接新建第一个连接
        if (act?.readonly && !act.key.configured) setEdit({ kind: "new" });
      })
      .catch((e) => setError(errText(e)));
  }, [c, applyList]);

  const done = (text: string) => (setMsg(text), setError(""));
  const fail = (e: unknown) => setError(errText(e));

  const saveTimeout = (e: FormEvent) => {
    e.preventDefault();
    const t = Number(timeout);
    if (!Number.isFinite(t) || t < 5 || t > 600) {
      setError("超时需在 5–600 秒之间");
      return;
    }
    c.saveSettings({ timeout: t }).then((s) => (setSettings(s), setTimeoutText(String(s.timeout)), done("设置已保存。")), fail);
  };

  const saveMemory = (e: FormEvent) => {
    e.preventDefault();
    c.saveSettings({ memory_mode: memory }).then((s) => (setSettings(s), setMemory(s.memory?.setting ?? memory), done("设置已保存。")), fail);
  };

  const runTest = (id: string) => {
    setTest({ id, state: "running" });
    c.testConnection(id).then(
      (r) => {
        setTest({ id, state: "done", r, stamp: stampOf(items, id) });
        refresh().catch(fail); // probe 更新到卡片上
      },
      (er) => setTest({ id, state: "error", text: errText(er) }),
    );
  };

  const saved = msg ? <span className="badge success" role="status"><IconCheck size={10} />{msg}</span> : null;
  const top = <Topbar title="设置" sub="模型连接与请求参数" actions={saved} onBack={onBack} />;
  if (!catalog || !items || !settings) return <>{top}<div className="main" aria-busy={!error}>{error || "加载中…"}</div></>;

  const providerOf = (id: string) => catalog.providers.find((p) => p.id === id);
  const active = items.find((x) => x.active);
  const onboarding = !!active?.readonly && !active.key.configured;
  const editing = edit?.kind === "edit" ? items.find((x) => x.id === edit.id) : undefined;
  // 测试结果只对测的那一份配置有效（V2c §1）：连接改过（updated_at / model / key 变了）结果就不再显示
  const testFor = (x: Connection) => (test && test.id === x.id && (test.state !== "done" || test.stamp === stamp(x)) ? test : null);

  return (
    <>
      {top}
      <div className="main">
        <section className="settings" data-testid="settings-view">
          <h2 className="sr-only">设置</h2>
          {error && <p className="banner danger" role="alert">{error}</p>}
          {onboarding ? (
            <p className="banner" style={{ margin: 0 }} data-testid="onboarding">
              <IconWarn size={13} />还没有模型连接。新建一个连接：选服务商，先填 API Key 并保存，再上传 CSV。没有 Key 时提问会被拦下。
            </p>
          ) : null}

          <div className="conn-section">
            <div className="sec-head">
              <h3>模型连接</h3>
              <span className="aside">同一时间只有一个连接生效</span>
              <button type="button" className="pill-outline" onClick={() => setEdit({ kind: "new" })} disabled={edit?.kind === "new"}>
                <IconPlus size={12} />新建连接
              </button>
            </div>
            <ul className="conn-list" data-testid="conn-list">
              {items.map((x) =>
                editing?.id === x.id ? (
                  <li key={x.id} className="conn-card editing">
                    <ConnectionForm c={c} catalog={catalog} conn={x} onCancel={() => setEdit(null)}
                      onSaved={(text, warn) => refresh().then(() => (setEdit(null), done(text), warn ? setError(warn) : undefined), fail)} onError={fail} />
                  </li>
                ) : (
                  <ConnCard key={x.id} x={x} providerName={x.readonly ? "环境变量 DEEPSEEK_*" : providerOf(x.provider)?.name ?? x.provider}
                    test={testFor(x)} busy={test?.state === "running"}
                    onTest={() => runTest(x.id)}
                    onActivate={() => c.activateConnection(x.id).then((l) => (applyList(l.items), c.settings().then(setSettings), done(`已切换到「${x.name}」。`)), fail)}
                    onEdit={() => setEdit({ kind: "edit", id: x.id })}
                    onDelete={() => c.deleteConnection(x.id).then((l) => (applyList(l.items), c.settings().then(setSettings), setEdit(null), done("连接已删除。")), fail)} />
                ),
              )}
            </ul>
            {edit?.kind === "new" ? (
              <div className="conn-card editing" data-testid="conn-new">
                <ConnectionForm c={c} catalog={catalog} first={onboarding} onCancel={() => setEdit(null)}
                  onSaved={(text, warn) => refresh().then(() => (setEdit(null), done(text), warn ? setError(warn) : undefined), fail)} onError={fail} />
              </div>
            ) : null}
          </div>

          <form onSubmit={saveTimeout}>
            <div className="sec-head"><h3>请求</h3></div>
            <label className="inline">
              单次请求超时（秒）
              <span className="ctl">
                <input aria-label="单次请求超时（秒）" className="short" type="number" inputMode="numeric" value={timeout}
                  onChange={(e) => setTimeoutText(e.target.value)} />
                <span className="hint">5–600 秒，对所有连接生效</span>
              </span>
            </label>
            {settings.sources ? (
              <p className="hint" data-testid="settings-sources">{sourcesText(settings)}</p>
            ) : null}
            <div className="form-actions">
              <button type="submit" className="primary">保存设置</button>
            </div>
          </form>

          <form onSubmit={saveMemory} data-testid="memory-form">
            <div className="sec-head"><h3>会话记忆（实验）</h3></div>
            <label className="inline">
              追问时带上的上下文
              <span className="ctl">
                <select aria-label="会话记忆" value={memory} onChange={(e) => setMemory(e.target.value as MemoryMode)}>
                  <option value="off">关闭：只带最近几轮问答（默认）</option>
                  <option value="state">开启：再带上分析前提和失败的轮次</option>
                </select>
              </span>
            </label>
            <p className="hint" data-testid="memory-hint">
              开启后，追问时会附上此前各轮的问题、结论摘要、分组和筛选条件，被停止或失败的轮次也会带上。
              {settings.memory?.env ? `当前被环境变量 DATACHAT_MEMORY=${settings.memory.env} 覆盖，这里的选择暂不生效。` : ""}
            </p>
            <div className="form-actions">
              <button type="submit" className="primary">保存记忆设置</button>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}

function sourcesText(s: Settings): string {
  const src = s.sources!;
  const who = s.connection ? `连接「${s.connection.name}」，模型 ${s.model}` : `模型 ${s.model}`;
  const head = `当前生效：${who}，超时${SOURCE_TEXT[src.timeout]}。`;
  if (s.connection && s.connection.id !== "env") return head;
  return head + `模型名${SOURCE_TEXT[src.model]}，Base URL ${SOURCE_TEXT[src.base_url]}。桌面版不读取仓库里的 .env 文件，要用自己的网关请新建一个连接。`;
}

function stamp(x: Connection) {
  return `${x.updated_at}|${x.model}|${x.key.configured}`;
}
function stampOf(items: Connection[] | null, id: string) {
  const x = items?.find((i) => i.id === id);
  return x ? stamp(x) : "";
}

/** 卡片上的测试状态：probe 只在 model 对得上时才有（后端已按模型过滤）。 */
function probeText(x: Connection): { text: string; ok: boolean | null } {
  const p = x.probe;
  if (!p) return { text: "未测试", ok: null };
  if (!p.connect) return { text: "✗ 连接失败", ok: false };
  if (p.tools === false) return { text: "✓ 连接 · ✗ 工具调用", ok: false };
  if (p.tools === null) return { text: "✓ 连接 · 工具调用未测出", ok: null };
  return { text: "✓ 连接 · ✓ 工具调用", ok: true };
}

function ConnCard({ x, providerName, test, busy, onTest, onActivate, onEdit, onDelete }: {
  x: Connection; providerName: string; test: TestState | null; busy: boolean;
  onTest: () => void; onActivate: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const st = probeText(x);
  const needKey = x.key.needed && !x.key.configured;
  return (
    <li className={`conn-card${x.active ? " active" : ""}`} data-testid="conn-card" aria-current={x.active ? "true" : undefined}>
      <div className="conn-head">
        <span className="conn-avatar" aria-hidden="true">{providerName.slice(0, 1)}</span>
        <span className="conn-title">
          <span className="conn-name">{x.name}</span>
          <span className="conn-sub">{providerName} · <span className="mono">{x.model || "（未填模型）"}</span></span>
        </span>
        {x.active ? <span className="badge success" data-testid="conn-active"><IconCheck size={10} />生效中</span> : null}
        <span className={`conn-probe${st.ok === true ? " ok" : st.ok === false ? " bad" : ""}`} data-testid="conn-probe">{st.text}</span>
      </div>
      {x.readonly ? (
        <p className="hint">
          <span data-testid="key-status">
            {x.key.configured ? <span className="key-ok"><IconCheck size={11} />已设置（来源：{x.key.source === "env" ? "环境变量 DEEPSEEK_API_KEY" : "系统凭据"}）</span> : <span className="key-unset">未设置</span>}
          </span>
          <span> 只读：没有任何连接时才生效。要改用别的服务商或网关，新建一个连接。</span>
        </p>
      ) : needKey ? (
        <p className="hint key-unset" data-testid="key-status">未填 API Key</p>
      ) : null}
      <div className="form-actions">
        {!x.active && !x.readonly ? <button type="button" className="primary" onClick={onActivate}>设为生效</button> : null}
        <button type="button" disabled={busy} onClick={onTest}>{test?.state === "running" ? "测试中…" : "测试连接"}</button>
        {!x.readonly ? <button type="button" onClick={onEdit}>编辑</button> : null}
        {!x.readonly ? <ConfirmButton label="删除" confirmLabel="确认删除（Key 一并删除）" onConfirm={onDelete} /> : null}
      </div>
      {test?.state === "done" ? <TestResult r={test.r} /> : null}
      {test?.state === "error" ? <p className="banner danger test-fail" role="alert">{test.text}</p> : null}
    </li>
  );
}
