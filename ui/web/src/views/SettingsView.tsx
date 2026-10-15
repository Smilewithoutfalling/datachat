import { type FormEvent, useEffect, useState } from "react";
import { type Client, errText } from "../client";
import type { KeyStatus, Settings } from "../types";

const SOURCE: Record<string, string> = { env: "环境变量 DEEPSEEK_API_KEY", keyring: "系统钥匙串" };

// API Key 只写不读：后端从不返回 Key 本身，这里也不保留输入值（保存后立即清空）
export function SettingsView({ c, onKeyChange }: { c: Client; onKeyChange: (k: KeyStatus) => void }) {
  const [key, setKey] = useState<KeyStatus | null>(null);
  const [form, setForm] = useState<{ model: string; base_url: string; timeout: string } | null>(null);
  const [newKey, setNewKey] = useState("");
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

  if (!key || !form) return <section className="view" aria-busy={!error}>{error || "加载中…"}</section>;

  return (
    <section className="view settings" data-testid="settings-view">
      <h2>设置</h2>
      {msg && <p className="ok" role="status">{msg}</p>}
      {error && <p className="warn" role="alert">{error}</p>}

      <form onSubmit={saveKey}>
        <h3>API Key</h3>
        <p data-testid="key-status">
          {key.configured ? `已设置（来源：${SOURCE[key.source ?? ""] ?? key.source}）` : "未设置"}
        </p>
        {key.source === "env" && <p className="muted">环境变量优先于钥匙串；要改用钥匙串里的 Key，先去掉环境变量。</p>}
        <label>
          {key.configured ? "替换为新的 Key" : "填入 Key"}
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={newKey}
            maxLength={512}
            onChange={(e) => setNewKey(e.target.value)}
          />
        </label>
        <div className="actions">
          <button type="submit" disabled={!newKey.trim()}>
            保存 Key
          </button>
          {key.source === "keyring" && (
            <button
              type="button"
              className="danger"
              onClick={() => c.deleteKey().then((k) => keyDone(k, "已从钥匙串删除。"), (er) => setError(errText(er)))}
            >
              从钥匙串删除
            </button>
          )}
        </div>
      </form>

      <form onSubmit={saveSettings}>
        <h3>模型</h3>
        <label>
          模型名
          <input value={form.model} maxLength={200} onChange={(e) => setForm({ ...form, model: e.target.value })} />
        </label>
        <label>
          Base URL
          <input
            value={form.base_url}
            maxLength={500}
            spellCheck={false}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
        </label>
        <label>
          单次请求超时（秒）
          <input
            type="number"
            inputMode="numeric"
            value={form.timeout}
            onChange={(e) => setForm({ ...form, timeout: e.target.value })}
          />
        </label>
        <div className="actions">
          <button type="submit">保存设置</button>
        </div>
      </form>
    </section>
  );
}

function toForm(s: Settings) {
  return { model: s.model, base_url: s.base_url, timeout: String(s.timeout) };
}
