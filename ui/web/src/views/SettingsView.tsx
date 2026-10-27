import { type FormEvent, useEffect, useRef, useState } from "react";
import { type Client, errText } from "../client";
import type { KeyStatus, Settings, SettingSource, SettingsTest } from "../types";
import { IconCheck, IconChevronDown, IconChevronUp, IconWarn } from "./icons";
import { llmErrorText } from "./llmErrorText";
import { Topbar } from "./ui";

// API Key 只写不读：后端从不返回 Key 本身，这里也不保留输入值（保存后立即清空）。
// V2a §5.1：凭证三态——env（只读，说明原因）/ keyring（可更换、可删除）/ 未设置（黄色提示 + 输入框）。
// 验收 P1-15：「钥匙串」是 macOS 叫法，界面统一写「系统凭据」。
// 阶段 5 收尾 C：凭证卡和模型三项下面一个「测试连接」。测的是**已保存**的配置（POST /settings/test），所以表单有未保存的
// 改动（模型三项和保存时不同、或填了新 Key 没保存）时按钮不可点，旁边写「先保存再测试」，避免"测的和用的不是一份"。
// 结果三态：测试中 / 连接正常 · 0.8s · 模型名（绿）/ 失败显示 message；auth、no_key 时焦点移到 Key 输入框。
// 阶段 6 收尾（S 10-27）：每项标出当前生效值的来源，桌面端没读到 .env 时一眼能看出用的是默认值
const SOURCE_TEXT: Record<SettingSource, string> = { settings: "来自本页设置", env: "来自环境变量", default: "是默认值" };

export function SettingsView({ c, onKeyChange, onBack }: { c: Client; onKeyChange: (k: KeyStatus) => void; onBack?: () => void }) {
  const [key, setKey] = useState<KeyStatus | null>(null);
  const [form, setForm] = useState<{ model: string; base_url: string; timeout: string } | null>(null);
  const [savedForm, setSavedForm] = useState<{ model: string; base_url: string; timeout: string } | null>(null);
  const [sources, setSources] = useState<Settings["sources"]>(undefined);
  const [testRaw, setTest] = useState<
    (({ state: "running" } | { state: "done"; r: SettingsTest } | { state: "error"; text: string }) & { at: TestAt }) | null
  >(null);
  const keyInput = useRef<HTMLInputElement | null>(null);
  const [newKey, setNewKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  // V2c §1：测试结果只对"测的那一份配置"有效。结果带着发起时的 form / newKey / key 引用（at）；任何字段改动、填新 Key、
  // 保存或删除 Key 都换掉其中一个引用，结果就不再显示。在飞的测试同理：回来时 at 已不是当前的，写进去也看不见。
  // 用派生而不是 effect 里 setTest(null)（react-hooks/set-state-in-effect）。
  const formRef = useRef(form), newKeyRef = useRef(newKey), keyRef = useRef(key);
  useEffect(() => {
    formRef.current = form;
    newKeyRef.current = newKey;
    keyRef.current = key;
  }, [form, newKey, key]);
  const test = testRaw && testRaw.at.form === form && testRaw.at.newKey === newKey && testRaw.at.key === key ? testRaw : null;

  useEffect(() => {
    Promise.all([c.keyStatus(), c.settings()])
      .then(([k, s]) => (setKey(k), setForm(toForm(s)), setSavedForm(toForm(s)), setSources(s.sources)))
      .catch((e) => setError(errText(e)));
  }, [c]);

  const keyDone = (k: KeyStatus, text: string) => {
    setKey(k);
    onKeyChange(k);
    setMsg(text);
    setError("");
    setReplacing(false);
  };

  const saveKey = (e: FormEvent) => {
    e.preventDefault();
    const v = newKey.trim();
    setNewKey("");
    if (!v) return;
    c.setKey(v).then((k) => keyDone(k, "API Key 已保存。"), (er) => setError(errText(er)));
  };

  const saveSettings = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const t = Number(form.timeout);
    if (!Number.isFinite(t) || t < 5 || t > 600) {
      setError("超时需在 5–600 秒之间");
      return;
    }
    c.saveSettings({ model: form.model, base_url: form.base_url, timeout: t }).then(
      (s) => (setForm(toForm(s)), setSavedForm(toForm(s)), setSources(s.sources), setMsg("设置已保存。"), setError("")),
      (er) => setError(errText(er)),
    );
  };

  const runTest = () => {
    const at: TestAt = { form, newKey, key };
    const current = () => at.form === formRef.current && at.newKey === newKeyRef.current && at.key === keyRef.current;
    setTest({ state: "running", at });
    c.testSettings().then(
      (r) => {
        setTest({ state: "done", r, at });
        if (current() && !r.ok && (r.llm_kind === "auth" || r.llm_kind === "no_key")) keyInput.current?.focus();
      },
      (er) => setTest({ state: "error", text: errText(er), at }),
    );
  };

  const saved = msg ? <span className="badge success" role="status"><IconCheck size={10} />{msg}</span> : null;
  const top = <Topbar title="设置" sub="模型凭证与连接参数" actions={saved} onBack={onBack} />;
  if (!key || !form) return <>{top}<div className="main" aria-busy={!error}>{error || "加载中…"}</div></>;

  const env = key.source === "env";
  const editable = !key.configured || replacing;
  const unsaved = !!newKey.trim() || !savedForm || form.model !== savedForm.model || form.base_url !== savedForm.base_url
    || form.timeout !== savedForm.timeout;
  return (
    <>
      {top}
      <div className="main">
        <section className="settings" data-testid="settings-view">
          <h2 className="sr-only">设置</h2>
          {error && <p className="banner danger" role="alert">{error}</p>}

          <form onSubmit={saveKey}>
            <div className="sec-head">
              <h3>模型凭证</h3>
              {/* 验收 P2-42：已设置是成功状态，绿色加勾；来源跟在后面 */}
              <span className="aside" data-testid="key-status">
                {key.configured ? (
                  <span className="key-ok"><IconCheck size={11} />已设置（来源：{env ? "环境变量 DEEPSEEK_API_KEY" : key.source === "keyring" ? "系统凭据" : key.source}）</span>
                ) : (
                  <span className="key-unset">未设置</span>
                )}
              </span>
            </div>
            {!key.configured ? (
              <p className="banner" style={{ margin: 0 }}><IconWarn size={13} />还没有 API Key：先填 API Key 并保存，再上传 CSV。没有 Key 时提问会被拦下。</p>
            ) : null}
            <div className="stack">
              API Key
              {env ? (
                <>
                  <div className="key-field readonly"><input aria-label="API Key（只读）" value="来自环境变量 DEEPSEEK_API_KEY" readOnly disabled /></div>
                  <p className="hint">环境变量优先级更高，这里改了也不生效。要改用保存在本机的 Key，先去掉环境变量。</p>
                </>
              ) : editable ? (
                <>
                  <div className="key-field">
                    <input key="new" ref={keyInput} type="password" aria-label={key.configured ? "替换为新的 Key" : "填入 Key"} autoComplete="off" spellCheck={false}
                      value={newKey} maxLength={512} placeholder="sk-…" onChange={(e) => setNewKey(e.target.value)} />
                    {replacing ? <button type="button" onClick={() => (setReplacing(false), setNewKey(""))}>取消</button> : null}
                  </div>
                  <p className="hint">只保存在本机的系统凭据里（Windows 凭据管理器 / macOS 钥匙串），不上传。</p>
                </>
              ) : (
                <>
                  <div className="key-field">
                    <input key="current" ref={keyInput} aria-label="当前 Key" value="已保存在系统凭据中" readOnly />
                    <button type="button" onClick={() => setReplacing(true)}>更换</button>
                  </div>
                  <p className="hint">只保存在本机的系统凭据里（Windows 凭据管理器 / macOS 钥匙串），不上传。</p>
                </>
              )}
            </div>
            {!env ? (
              <div className="form-actions">
                {editable ? <button type="submit" className="primary" disabled={!newKey.trim()}>保存 Key</button> : null}
                {key.source === "keyring" ? (
                  <button type="button" className="danger"
                    onClick={() => c.deleteKey().then((k) => keyDone(k, "已从本机删除。"), (er) => setError(errText(er)))}>
                    从本机删除
                  </button>
                ) : null}
              </div>
            ) : null}
          </form>

          <form onSubmit={saveSettings}>
            <div className="sec-head"><h3>模型</h3></div>
            <label className="inline">
              模型名
              <span className="ctl"><input aria-label="模型名" value={form.model} maxLength={200} onChange={(e) => setForm({ ...form, model: e.target.value })} /></span>
            </label>
            <label className="inline">
              Base URL
              <span className="ctl">
                <input aria-label="Base URL" className="mono-input" value={form.base_url} maxLength={500} spellCheck={false}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              </span>
            </label>
            <label className="inline">
              单次请求超时（秒）
              <span className="ctl">
                <input aria-label="单次请求超时（秒）" className="short" type="number" inputMode="numeric" value={form.timeout}
                  onChange={(e) => setForm({ ...form, timeout: e.target.value })} />
                <span className="hint">5–600 秒</span>
              </span>
            </label>
            {sources ? (
              <p className="hint" data-testid="settings-sources">
                当前生效：模型名{SOURCE_TEXT[sources.model]}，Base URL {SOURCE_TEXT[sources.base_url]}，超时{SOURCE_TEXT[sources.timeout]}。
                桌面版不读取仓库里的 .env 文件，要用自己的网关请在这里填写并保存。
              </p>
            ) : null}
            <div className="form-actions">
              <button type="submit" className="primary">保存设置</button>
            </div>
          </form>

          <div className="test-conn" data-testid="settings-test">
            <div className="form-actions">
              <button type="button" disabled={unsaved || test?.state === "running"} onClick={runTest}>
                {test?.state === "running" ? "测试中…" : "测试连接"}
              </button>
              {unsaved ? <span className="hint" data-testid="test-unsaved">先保存再测试</span> : null}
              {test?.state === "done" && test.r.ok ? (
                <span className="key-ok" role="status" data-testid="test-result">
                  <IconCheck size={11} />连接正常 · {(test.r.latency_ms / 1000).toFixed(1)}s · {test.r.model}
                </span>
              ) : null}
            </div>
            {test?.state === "done" && !test.r.ok ? <TestFail kind={test.r.llm_kind} message={test.r.message} /> : null}
            {test?.state === "error" ? <p className="banner danger test-fail" role="alert">{test.text}</p> : null}
          </div>
        </section>
      </div>
    </>
  );
}

/** V2c §2：失败和分析的错误卡一个口径——正文是标题 + 建议 + 编号，后端原文（含上游 message）收进默认折叠的「技术详情」。
 *  原文不去掉：模型名写错、Base URL 少 /v1 这类配置错误，上游原文是最直接的线索（S 10-25 定折叠保留）。 */
function TestFail({ kind, message }: { kind: string; message: string }) {
  const [tech, setTech] = useState(false);
  const t = llmErrorText(kind, "settings");
  const code = /（编号 ([0-9a-f]+)）$/.exec(message)?.[1];
  return (
    <div className="banner danger test-fail" role="alert" data-testid="test-result">
      <p className="test-fail-title">{t.title}</p>
      <p className="test-fail-hint">{t.hint}{code ? `（编号 ${code}）` : ""}</p>
      <button type="button" className="tech-toggle" aria-expanded={tech} onClick={() => setTech(!tech)}>
        技术详情{tech ? <IconChevronUp size={10} /> : <IconChevronDown size={10} />}
      </button>
      <p className="tech-body" hidden={!tech} data-testid="test-tech">{message}</p>
    </div>
  );
}

type TestAt = { form: unknown; newKey: string; key: KeyStatus | null };

function toForm(s: Settings) {
  return { model: s.model, base_url: s.base_url, timeout: String(s.timeout) };
}
