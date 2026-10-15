import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Client, errText } from "../client";
import type { Agent, Dataset, DatasetDetail, KeyStatus, Session } from "../types";
import { DatasetView } from "./DatasetView";
import { SessionView } from "./SessionView";
import { SettingsView } from "./SettingsView";

type View = { kind: "home" } | { kind: "dataset"; id: string } | { kind: "session"; id: string } | { kind: "settings" };

export function Shell({ c, initialKey }: { c: Client; initialKey: KeyStatus }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [view, setView] = useState<View>(initialKey.configured ? { kind: "home" } : { kind: "settings" });
  const [key, setKey] = useState(initialKey);
  const [error, setError] = useState("");
  const [uploaded, setUploaded] = useState<DatasetDetail | undefined>(); // 上传响应（带预览）

  const reload = useCallback(
    () =>
      Promise.all([c.datasets(), c.sessions()])
        .then(([d, s]) => (setDatasets(d), setSessions(s)))
        .catch((e) => setError(errText(e))),
    [c],
  );
  useEffect(() => {
    reload();
  }, [reload]);

  const names = useMemo(() => Object.fromEntries(datasets.map((d) => [d.id, d.name])), [datasets]);

  const newSession = (datasetId: string, agent: Agent) =>
    c.createSession(datasetId, agent).then(
      (s) => (setSessions((xs) => [s, ...xs]), setView({ kind: "session", id: s.id })),
      (e) => setError(errText(e)),
    );

  return (
    <div className="shell" data-testid="ready">
      <aside className="sidebar">
        <h1>datachat</h1>
        <Upload
          c={c}
          onDone={(d) => (setUploaded(d), setDatasets((xs) => [d, ...xs]), setView({ kind: "dataset", id: d.id }))}
          onError={setError}
        />
        <nav aria-label="数据集">
          <h2>数据集</h2>
          {datasets.length === 0 && <p className="muted">还没有数据集</p>}
          <ul>
            {datasets.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  className={view.kind === "dataset" && view.id === d.id ? "nav active" : "nav"}
                  onClick={() => setView({ kind: "dataset", id: d.id })}
                >
                  {d.name}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="会话">
          <h2>
            会话 <span className="hint">按最近分析时间排序</span>
          </h2>
          {sessions.length === 0 && <p className="muted">还没有会话</p>}
          <ul>
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={view.kind === "session" && view.id === s.id ? "nav active" : "nav"}
                  onClick={() => setView({ kind: "session", id: s.id })}
                >
                  {s.title || "未命名会话"}
                  <span className="muted small">{names[s.dataset_id] ?? ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <button
          type="button"
          className={view.kind === "settings" ? "nav active settings-link" : "nav settings-link"}
          onClick={() => setView({ kind: "settings" })}
        >
          设置{key.configured ? "" : "（未设置 Key）"}
        </button>
      </aside>

      <main className="main">
        {error && (
          <p className="warn" role="alert">
            {error}{" "}
            <button type="button" className="link" onClick={() => setError("")}>
              关闭
            </button>
          </p>
        )}
        {!key.configured && view.kind !== "settings" && (
          <p className="warn">还没有设置 API Key，分析会失败。去"设置"里填写。</p>
        )}
        {view.kind === "home" && (
          <section className="view">
            <h2>开始</h2>
            <p>在左侧上传 CSV（可多选：多张表，或数据表加 *.dict.csv 字典），看预览确认数据读对了，再新建会话提问。</p>
          </section>
        )}
        {view.kind === "dataset" && (
          <DatasetView
            key={view.id}
            c={c}
            id={view.id}
            initial={uploaded}
            onNewSession={newSession}
            onDeleted={() => (setView({ kind: "home" }), reload())}
          />
        )}
        {view.kind === "session" && (
          <SessionView
            key={view.id}
            c={c}
            id={view.id}
            datasetName={names[sessions.find((s) => s.id === view.id)?.dataset_id ?? ""] ?? ""}
            onChanged={(s) => setSessions((xs) => xs.map((x) => (x.id === s.id ? s : x)))}
            onDeleted={() => (setView({ kind: "home" }), setSessions((xs) => xs.filter((x) => x.id !== view.id)))}
          />
        )}
        {view.kind === "settings" && <SettingsView c={c} onKeyChange={setKey} />}
      </main>
    </div>
  );
}

function Upload({ c, onDone, onError }: { c: Client; onDone: (d: DatasetDetail) => void; onError: (m: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const files = Array.from(input.current?.files ?? []);
    if (files.length === 0) return;
    setBusy(true);
    c.upload(files, name.trim())
      .then((d) => {
        onDone(d);
        setName("");
        if (input.current) input.current.value = "";
      }, (er) => onError(`上传失败：${errText(er)}`))
      .finally(() => setBusy(false));
  };

  return (
    <form className="upload" onSubmit={submit}>
      <input ref={input} type="file" accept=".csv" multiple aria-label="选择 CSV 文件" />
      <input placeholder="数据集名称（可选）" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      <button type="submit" disabled={busy}>
        {busy ? "上传中…" : "上传"}
      </button>
    </form>
  );
}
