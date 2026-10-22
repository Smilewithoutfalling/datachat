import { type FormEvent, useEffect, useState } from "react";
import { type Client, errText } from "../client";
import type { KeyStatus, Settings } from "../types";
import { IconCheck, IconWarn } from "./icons";
import { Topbar } from "./ui";

// API Key 只写不读：后端从不返回 Key 本身，这里也不保留输入值（保存后立即清空）。
// V2a §5.1：凭证三态——env（只读，说明原因）/ keyring（可更换、可删除）/ 未设置（黄色提示 + 输入框）。
// 验收 P1-15：「钥匙串」是 macOS 叫法，界面统一写「系统凭据」。
export function SettingsView({ c, onKeyChange }: { c: Client; onKeyChange: (k: KeyStatus) => void }) {
  const [key, setKey] = useState<KeyStatus | null>(null);
  const [form, setForm] = useState<{ model: string; base_url: string; timeout: string } | null>(null);
  const [newKey, setNewKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([c.keyStatus(), c.settings()])
      .then(([k, s]) => (setKey(k), setForm(toForm(s))))
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
      (s) => (setForm(toForm(s)), setMsg("设置已保存。"), setError("")),
      (er) => setError(errText(er)),
    );
  };

  const saved = msg ? <span className="badge success" role="status"><IconCheck size={10} />{msg}</span> : null;
  const top = <Topbar title="设置" sub="模型凭证与连接参数" actions={saved} />;
  if (!key || !form) return <>{top}<div className="main" aria-busy={!error}>{error || "加载中…"}</div></>;

  const env = key.source === "env";
  const editable = !key.configured || replacing;
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
              <p className="banner" style={{ margin: 0 }}><IconWarn size={13} />还没有 API Key，提问会被拦下。填写后保存。</p>
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
                    <input key="new" type="password" aria-label={key.configured ? "替换为新的 Key" : "填入 Key"} autoComplete="off" spellCheck={false}
                      value={newKey} maxLength={512} placeholder="sk-…" onChange={(e) => setNewKey(e.target.value)} />
                    {replacing ? <button type="button" onClick={() => (setReplacing(false), setNewKey(""))}>取消</button> : null}
                  </div>
                  <p className="hint">只保存在本机的系统凭据里（Windows 凭据管理器 / macOS 钥匙串），不上传。</p>
                </>
              ) : (
                <>
                  <div className="key-field">
                    <input key="current" aria-label="当前 Key" value="已保存在系统凭据中" readOnly />
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
            <div className="form-actions">
              <button type="submit" className="primary">保存设置</button>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}

function toForm(s: Settings) {
  return { model: s.model, base_url: s.base_url, timeout: String(s.timeout) };
}
